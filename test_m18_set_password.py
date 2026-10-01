"""
Tests for the admin-initiated password-setup flow (Batch B, item 16),
2026-10-01 - replaces the old POST /users/{user_id}/set-password, which
could be called by anyone who merely knew a user's numeric id with zero
proof of identity. Now reuses the same email-token mechanism already
proven for forgot-password: an admin triggers POST
/users/{user_id}/request-password-setup, the real account owner receives
a one-time link by email, and sets their password through the existing,
unchanged POST /reset-password endpoint.

None of these tests make a real network call - email_client.send_email is
mocked in every test that would otherwise trigger it, same discipline as
test_forgot_password.py.

Written against the REAL ~/KEVO implementation.
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User as UserModel, PasswordResetToken
from app import app, get_db, hash_password, verify_password


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


_email_counter = [0]


def make_legacy_user(db, name="Legacy User"):
    _email_counter[0] += 1
    user = UserModel(
        name=name,
        email=f"legacy{_email_counter[0]}@test.com",
        role="seller",
        account_type="participant",
        hashed_password=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_user_with_password(db, plain_password="already-set-password", name="Has Password"):
    _email_counter[0] += 1
    user = UserModel(
        name=name,
        email=f"haspw{_email_counter[0]}@test.com",
        role="seller",
        account_type="participant",
        hashed_password=hash_password(plain_password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_admin(db, plain_password="adminpass123", name="Admin User"):
    _email_counter[0] += 1
    user = UserModel(
        name=name,
        email=f"admin{_email_counter[0]}@test.com",
        role="seller",
        account_type="admin",
        hashed_password=hash_password(plain_password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(client, email, password):
    resp = client.post("/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_request_password_setup_requires_auth(client, db_session):
    legacy = make_legacy_user(db_session)
    resp = client.post(f"/users/{legacy.id}/request-password-setup")
    assert resp.status_code == 401


def test_request_password_setup_rejected_for_non_admin(client, db_session):
    legacy = make_legacy_user(db_session)
    non_admin = make_user_with_password(db_session, plain_password="participantpass1")
    headers = auth_headers(client, non_admin.email, "participantpass1")

    with patch("email_client.send_email") as mock_send:
        resp = client.post(f"/users/{legacy.id}/request-password-setup", headers=headers)

    assert resp.status_code == 403
    mock_send.assert_not_called()


def test_request_password_setup_admin_succeeds_for_legacy_user(client, db_session):
    legacy = make_legacy_user(db_session)
    admin = make_admin(db_session)
    headers = auth_headers(client, admin.email, "adminpass123")

    with patch("email_client.send_email") as mock_send:
        resp = client.post(f"/users/{legacy.id}/request-password-setup", headers=headers)

    assert resp.status_code == 200
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == legacy.email

    tokens = db_session.query(PasswordResetToken).filter(PasswordResetToken.user_id == legacy.id).all()
    assert len(tokens) == 1
    assert tokens[0].used_at is None


def test_request_password_setup_rejected_when_user_already_has_password(client, db_session):
    user = make_user_with_password(db_session)
    admin = make_admin(db_session)
    headers = auth_headers(client, admin.email, "adminpass123")

    with patch("email_client.send_email") as mock_send:
        resp = client.post(f"/users/{user.id}/request-password-setup", headers=headers)

    assert resp.status_code == 400
    mock_send.assert_not_called()


def test_request_password_setup_404_for_unknown_user(client, db_session):
    admin = make_admin(db_session)
    headers = auth_headers(client, admin.email, "adminpass123")

    with patch("email_client.send_email") as mock_send:
        resp = client.post("/users/999999/request-password-setup", headers=headers)

    assert resp.status_code == 404
    mock_send.assert_not_called()


def test_request_password_setup_reset_password_round_trip(client, db_session):
    legacy = make_legacy_user(db_session)
    admin = make_admin(db_session)
    headers = auth_headers(client, admin.email, "adminpass123")

    with patch("email_client.send_email") as mock_send:
        resp = client.post(f"/users/{legacy.id}/request-password-setup", headers=headers)
    assert resp.status_code == 200

    email_body = mock_send.call_args.args[2]
    assert "token=" in email_body
    raw_token = email_body.split("token=")[1].split("\n")[0].strip()

    reset_resp = client.post(
        "/reset-password",
        json={"token": raw_token, "new_password": "brand-new-password1"},
    )
    assert reset_resp.status_code == 200

    db_session.refresh(legacy)
    assert legacy.hashed_password is not None
    assert verify_password("brand-new-password1", legacy.hashed_password)

    login_resp = client.post("/login", json={"email": legacy.email, "password": "brand-new-password1"})
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()

    reuse_resp = client.post(
        "/reset-password",
        json={"token": raw_token, "new_password": "yetanother789"},
    )
    assert reuse_resp.status_code == 400
