"""
Tests for the real (Stripe Connect) withdrawal endpoints,
/me/funds/withdraw/real and /me/funds/withdraw/real/confirm, 2026-10-23 -
closes the M32 gap where real withdrawals existed only in the Java wallet
service with no way for a KEVO user to actually trigger one.

Mocks wallet_client.withdraw_real and email_client.send_email entirely,
same discipline as test_m32_wallet.py's demo withdrawal tests - the real
Transfer+Payout call to Stripe itself is verified by hand, not here.
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

from models import Base, User as UserModel, RealWithdrawalConfirmation
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
        email=f"realwd{suffix}-{id(object())}@example.com",
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


def _extract_token(mock_send):
    email_body = mock_send.call_args.args[2]
    assert "token=" in email_body
    return email_body.split("token=")[1].split("&")[0].split("\n")[0].strip()


def test_real_withdraw_below_threshold_calls_wallet_client_immediately(client, db_session):
    user = make_user(db_session, "realwd1")
    fake_response = {
        "id": 1, "status": "PENDING", "amount": 500.0, "currency": "USD",
        "destinationReference": "Stripe Connect payout to acct_fake", "failureReason": None,
        "providerReference": "po_fake123", "bankAccountId": None,
    }

    with patch("wallet_client.withdraw_real", return_value=fake_response) as mock_withdraw:
        resp = client.post(
            "/me/funds/withdraw/real",
            json={"amount": 500.0, "currency": "USD", "idempotency_key": "real-test-key-1"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    assert resp.json() == fake_response
    mock_withdraw.assert_called_once_with(user.id, 500.0, "USD", "real-test-key-1")


def test_real_withdraw_below_threshold_failure_returns_400(client, db_session):
    user = make_user(db_session, "realwd2")
    fake_response = {
        "id": 1, "status": "FAILED", "amount": 500.0, "currency": "USD",
        "destinationReference": None, "failureReason": "Stripe payout onboarding is not complete yet - finish connecting a payout account first",
        "providerReference": None, "bankAccountId": None,
    }

    with patch("wallet_client.withdraw_real", return_value=fake_response):
        resp = client.post(
            "/me/funds/withdraw/real",
            json={"amount": 500.0, "currency": "USD", "idempotency_key": "real-test-key-2"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 400
    assert "onboarding" in resp.json()["detail"]


def test_real_withdraw_wallet_service_unavailable_502(client, db_session):
    user = make_user(db_session, "realwd3")

    with patch("wallet_client.withdraw_real", side_effect=RuntimeError("Wallet service error 500: boom")):
        resp = client.post(
            "/me/funds/withdraw/real",
            json={"amount": 500.0, "currency": "USD", "idempotency_key": "real-test-key-3"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 502


def test_real_withdraw_at_threshold_requires_confirmation_and_does_not_move_money_yet(client, db_session):
    user = make_user(db_session, "realstepup1")

    with patch("wallet_client.withdraw_real") as mock_withdraw, patch("email_client.send_email") as mock_send:
        resp = client.post(
            "/me/funds/withdraw/real",
            json={"amount": 1000.0, "currency": "USD", "idempotency_key": "real-test-key-stepup1"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "CONFIRMATION_REQUIRED"
    mock_withdraw.assert_not_called()
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == user.email

    confirmations = db_session.query(RealWithdrawalConfirmation).filter(RealWithdrawalConfirmation.user_id == user.id).all()
    assert len(confirmations) == 1
    assert confirmations[0].used_at is None
    assert float(confirmations[0].amount) == 1000.0
    assert confirmations[0].idempotency_key == "real-test-key-stepup1"


def test_real_withdraw_confirm_round_trip_completes_withdrawal(client, db_session):
    user = make_user(db_session, "realconfirmround1")
    fake_response = {
        "id": 9, "status": "PENDING", "amount": 1500.0, "currency": "USD",
        "destinationReference": "Stripe Connect payout to acct_fake", "failureReason": None,
        "providerReference": "po_fake999", "bankAccountId": None,
    }

    with patch("wallet_client.withdraw_real", return_value=fake_response) as mock_withdraw, \
         patch("email_client.send_email") as mock_send:
        resp = client.post(
            "/me/funds/withdraw/real",
            json={"amount": 1500.0, "currency": "USD", "idempotency_key": "real-test-key-round1"},
            headers=auth_headers(user),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "CONFIRMATION_REQUIRED"
        raw_token = _extract_token(mock_send)
        mock_withdraw.assert_not_called()

        confirm_resp = client.post(
            "/me/funds/withdraw/real/confirm",
            json={"token": raw_token},
            headers=auth_headers(user),
        )

    assert confirm_resp.status_code == 200
    assert confirm_resp.json() == fake_response
    mock_withdraw.assert_called_once_with(user.id, 1500.0, "USD", "real-test-key-round1")

    confirmation = db_session.query(RealWithdrawalConfirmation).filter(RealWithdrawalConfirmation.user_id == user.id).first()
    assert confirmation.used_at is not None


def test_real_withdraw_confirm_reused_token_rejected(client, db_session):
    user = make_user(db_session, "realconfirmreuse1")
    fake_response = {
        "id": 9, "status": "PENDING", "amount": 1500.0, "currency": "USD",
        "destinationReference": "Stripe Connect payout to acct_fake", "failureReason": None,
        "providerReference": "po_fake998", "bankAccountId": None,
    }

    with patch("wallet_client.withdraw_real", return_value=fake_response), \
         patch("email_client.send_email") as mock_send:
        resp = client.post(
            "/me/funds/withdraw/real",
            json={"amount": 1500.0, "currency": "USD", "idempotency_key": "real-test-key-reuse1"},
            headers=auth_headers(user),
        )
        raw_token = _extract_token(mock_send)

        first = client.post("/me/funds/withdraw/real/confirm", json={"token": raw_token}, headers=auth_headers(user))
        assert first.status_code == 200

        second = client.post("/me/funds/withdraw/real/confirm", json={"token": raw_token}, headers=auth_headers(user))

    assert second.status_code == 400
    assert second.json()["detail"] == "Invalid or expired confirmation token"


def test_real_withdraw_confirm_invalid_token_400(client, db_session):
    user = make_user(db_session, "realconfirminvalid1")

    resp = client.post(
        "/me/funds/withdraw/real/confirm",
        json={"token": "not-a-real-token"},
        headers=auth_headers(user),
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired confirmation token"


def test_real_withdraw_confirm_wrong_user_400_and_message_identical_to_other_failures(client, db_session):
    owner = make_user(db_session, "realconfirmowner1")
    attacker = make_user(db_session, "realconfirmattacker1")

    with patch("wallet_client.withdraw_real"), patch("email_client.send_email") as mock_send:
        client.post(
            "/me/funds/withdraw/real",
            json={"amount": 1500.0, "currency": "USD", "idempotency_key": "real-test-key-wronguser1"},
            headers=auth_headers(owner),
        )
        raw_token = _extract_token(mock_send)

    resp = client.post(
        "/me/funds/withdraw/real/confirm",
        json={"token": raw_token},
        headers=auth_headers(attacker),
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired confirmation token"


def test_real_withdraw_unauthenticated_401(client, db_session):
    resp = client.post("/me/funds/withdraw/real", json={"amount": 100.0, "currency": "USD", "idempotency_key": "x"})
    assert resp.status_code == 401
