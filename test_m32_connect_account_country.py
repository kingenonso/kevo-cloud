"""
Tests for the explicit, validated country field on /me/connect/account
(the Stripe Connect onboarding step for a KEVO user to receive real
payouts), 2026-10-23 - part of closing out the M32 gap where country
was hardcoded to "US" as a placeholder.

Mocks wallet_client entirely, same discipline as test_m32_wallet.py.
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

from models import Base, User as UserModel
from app import app, get_db, hash_password, create_access_token


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
        email=f"connect{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type="participant",
        kyc_status="verified",
        hashed_password=hash_password("password123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_create_connect_account_accepts_nigeria(client, db_session):
    user = make_user(db_session, "ng1")
    fake_response = {"connectAccountId": "acct_fake", "country": "NG"}

    with patch("wallet_client.create_connect_account", return_value=fake_response) as mock_create:
        resp = client.post(
            "/me/connect/account",
            json={"country": "ng"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    assert resp.json() == fake_response
    mock_create.assert_called_once_with(user.id, "NG", user.email)


def test_create_connect_account_accepts_united_states(client, db_session):
    user = make_user(db_session, "us1")
    fake_response = {"connectAccountId": "acct_fake2", "country": "US"}

    with patch("wallet_client.create_connect_account", return_value=fake_response) as mock_create:
        resp = client.post(
            "/me/connect/account",
            json={"country": "US"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    mock_create.assert_called_once_with(user.id, "US", user.email)


def test_create_connect_account_rejects_unsupported_country(client, db_session):
    user = make_user(db_session, "zz1")

    with patch("wallet_client.create_connect_account") as mock_create:
        resp = client.post(
            "/me/connect/account",
            json={"country": "ZZ"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 400
    assert "ZZ" in resp.json()["detail"]
    mock_create.assert_not_called()


def test_create_connect_account_unauthenticated_401(client, db_session):
    resp = client.post("/me/connect/account", json={"country": "US"})
    assert resp.status_code == 401
