"""
Tests for the forgot-password / reset-password flow (Batch B, group 3
item 15), 2026-09-24 - closes the last piece of M28's password gap:
a locked-out user with no way to prove identity by email had no path
back in until now.

None of these tests make a real network call - email_client.send_email
is mocked in every test that would otherwise trigger it, same discipline
as test_email_client.py and test_m26e_escrow_integration.py. Real
Mailgun sandbox verification is a separate step, once Eze has a real
Mailgun account.

Written against the REAL ~/KEVO implementation.
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import hashlib
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User as UserModel, PasswordResetToken
from app import app, get_db, hash_password, verify_password

GENERIC_MESSAGE = "If an account with that email exists, a password reset link has been sent."


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    session = TestingSessionLocal()
    yield session
    session.close()
    app.dependency_overrides.clear()


@pytest.fixture()
def client(db_session):
    return TestClient(app)


def make_user(db, suffix="1"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"forgotpw{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type="participant",
        hashed_password=hash_password("originalpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_forgot_password_existing_user_returns_generic_message_and_creates_token(client, db_session):
    user = make_user(db_session, "exists1")

    with patch("email_client.send_email") as mock_send:
        resp = client.post("/forgot-password", json={"email": user.email})

    assert resp.status_code == 200
    assert resp.json()["message"] == GENERIC_MESSAGE
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == user.email

    tokens = db_session.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).all()
    assert len(tokens) == 1
    assert tokens[0].used_at is None


def test_forgot_password_nonexistent_email_returns_same_generic_message_no_email_sent(client, db_session):
    with patch("email_client.send_email") as mock_send:
        resp = client.post("/forgot-password", json={"email": "nobody-here@example.com"})

    assert resp.status_code == 200
    assert resp.json()["message"] == GENERIC_MESSAGE
    mock_send.assert_not_called()

    tokens = db_session.query(PasswordResetToken).all()
    assert len(tokens) == 0


def test_forgot_password_raises_when_email_not_configured(client, db_session):
    user = make_user(db_session, "unconfigured1")

    with patch("email_client.send_email", side_effect=RuntimeError("EMAIL_API_KEY and EMAIL_DOMAIN must be set")):
        with pytest.raises(RuntimeError):
            client.post("/forgot-password", json={"email": user.email})


def test_forgot_password_reset_password_round_trip(client, db_session):
    user = make_user(db_session, "roundtrip1")

    with patch("email_client.send_email") as mock_send:
        resp = client.post("/forgot-password", json={"email": user.email})
    assert resp.status_code == 200

    email_body = mock_send.call_args.args[2]
    assert "token=" in email_body
    raw_token = email_body.split("token=")[1].split("\n")[0].strip()

    reset_resp = client.post(
        "/reset-password",
        json={"token": raw_token, "new_password": "newpassword456"},
    )
    assert reset_resp.status_code == 200
    assert reset_resp.json()["message"] == "Password reset successfully"

    db_session.refresh(user)
    assert verify_password("newpassword456", user.hashed_password)
    assert not verify_password("originalpass123", user.hashed_password)

    reuse_resp = client.post(
        "/reset-password",
        json={"token": raw_token, "new_password": "yetanother789"},
    )
    assert reuse_resp.status_code == 400


def test_reset_password_invalid_token_400(client, db_session):
    resp = client.post(
        "/reset-password",
        json={"token": "totally-bogus-token", "new_password": "whatever123"},
    )
    assert resp.status_code == 400


def test_reset_password_expired_token_400(client, db_session):
    user = make_user(db_session, "expired1")
    raw_token = "expired-test-token-1234567890"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    expired_row = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        created_at=datetime.utcnow() - timedelta(hours=1),
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        used_at=None,
    )
    db_session.add(expired_row)
    db_session.commit()

    resp = client.post(
        "/reset-password",
        json={"token": raw_token, "new_password": "whatever123"},
    )
    assert resp.status_code == 400


def test_reset_password_already_used_token_400(client, db_session):
    user = make_user(db_session, "used1")
    raw_token = "used-test-token-1234567890"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    used_row = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        used_at=datetime.utcnow(),
    )
    db_session.add(used_row)
    db_session.commit()

    resp = client.post(
        "/reset-password",
        json={"token": raw_token, "new_password": "whatever123"},
    )
    assert resp.status_code == 400
