"""
Tests for the real (Stripe ACH) deposit endpoint, /me/funds/deposit/real,
2026-10-23 - closes the M32 gap where real deposits existed only in the
Java wallet service (RealDepositController) with no way for a KEVO user to
actually trigger one through the app itself.

Mocks wallet_client.deposit_real entirely, same discipline as
test_m32_withdraw_real.py - the real PaymentIntent call to Stripe itself
is verified by hand, not here.
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
        email=f"realdep{suffix}-{id(object())}@example.com",
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


def test_real_deposit_calls_wallet_client_and_returns_pending(client, db_session):
    user = make_user(db_session, "realdep1")
    fake_response = {"depositId": 1, "paymentIntentId": "pi_fake123", "status": "PENDING"}

    with patch("wallet_client.deposit_real", return_value=fake_response) as mock_deposit:
        resp = client.post(
            "/me/funds/deposit/real",
            json={"bank_account_id": 7, "amount": 250.0, "idempotency_key": "real-dep-key-1"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    assert resp.json() == fake_response
    mock_deposit.assert_called_once_with(user.id, 7, 250.0, "real-dep-key-1")


def test_real_deposit_failure_returns_400(client, db_session):
    user = make_user(db_session, "realdep2")
    fake_response = {"depositId": None, "paymentIntentId": None, "status": "FAILED",
                      "failureReason": "Bank account is not verified"}

    with patch("wallet_client.deposit_real", return_value=fake_response):
        resp = client.post(
            "/me/funds/deposit/real",
            json={"bank_account_id": 7, "amount": 250.0, "idempotency_key": "real-dep-key-2"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 400
    assert "not verified" in resp.json()["detail"]


def test_real_deposit_wallet_service_unavailable_502(client, db_session):
    user = make_user(db_session, "realdep3")

    with patch("wallet_client.deposit_real", side_effect=RuntimeError("Wallet service error 500: boom")):
        resp = client.post(
            "/me/funds/deposit/real",
            json={"bank_account_id": 7, "amount": 250.0, "idempotency_key": "real-dep-key-3"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 502


def test_real_deposit_requires_verification(client, db_session):
    user = UserModel(
        name="Unverified User",
        email=f"realdepunverified-{id(object())}@example.com",
        role="buyer",
        account_type="participant",
        kyc_status="pending",
        hashed_password=hash_password("password123"),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    resp = client.post(
        "/me/funds/deposit/real",
        json={"bank_account_id": 7, "amount": 250.0, "idempotency_key": "real-dep-key-4"},
        headers=auth_headers(user),
    )

    assert resp.status_code == 403


def test_real_deposit_unauthenticated_401(client, db_session):
    resp = client.post(
        "/me/funds/deposit/real",
        json={"bank_account_id": 7, "amount": 250.0, "idempotency_key": "x"},
    )
    assert resp.status_code == 401
