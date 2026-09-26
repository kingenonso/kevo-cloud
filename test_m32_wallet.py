"""
Tests for the M32 wallet step-up withdrawal confirmation flow and the
/me/bank-accounts* endpoints, 2026-09-26 - part of the M32 automated test
suite (item 2 of the post-security-review plan).

These tests mock wallet_client entirely rather than requiring the real
kevo-wallet-service (Java) to be running - same discipline as
test_forgot_password.py mocking email_client.send_email rather than making
a real Mailgun call. The underlying Java business logic (bank-account
ownership, cooling-off, velocity limits, ledger correctness) already has
its own real-Postgres integration tests in kevo-wallet-service itself
(WithdrawalConcurrencyTest.java, DepositAndFundLockConcurrencyTest.java).
What these tests cover is what's uniquely KEVO's own responsibility: that
every wallet call is scoped to current_user.id, the step-up threshold
branch, the confirmation token lifecycle, and error handling when the
wallet service is unreachable.

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

from models import Base, User as UserModel, WithdrawalConfirmation
from app import app, get_db, hash_password, create_access_token

GENERIC_CONFIRM_ERROR = "Invalid or expired confirmation token"


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


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_user(db, suffix="1"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"wallet{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type="participant",
        hashed_password=hash_password("password123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _extract_token(mock_send):
    email_body = mock_send.call_args.args[2]
    assert "token=" in email_body
    return email_body.split("token=")[1].split("\n")[0].strip()


# ---------------------------------------------------------------------------
# Bank accounts - every call must be scoped to current_user.id
# ---------------------------------------------------------------------------

def test_add_bank_account_scoped_to_current_user(client, db_session):
    user = make_user(db_session, "addbank1")
    fake_response = {
        "id": 5, "accountHolderName": "Test User", "bankName": "Test Bank",
        "lastFour": "6789", "status": "UNVERIFIED", "createdAt": "2026-09-26T10:00:00",
    }

    with patch("wallet_client.add_bank_account", return_value=fake_response) as mock_add:
        resp = client.post(
            "/me/bank-accounts",
            json={"account_holder_name": "Test User", "bank_name": "Test Bank", "account_number": "0000123456789"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    assert resp.json() == fake_response
    mock_add.assert_called_once_with(user.id, "Test User", "Test Bank", "0000123456789")


def test_add_bank_account_wallet_service_unavailable_502(client, db_session):
    user = make_user(db_session, "addbank2")

    with patch("wallet_client.add_bank_account", side_effect=RuntimeError("Wallet service error 500: boom")):
        resp = client.post(
            "/me/bank-accounts",
            json={"account_holder_name": "Test User", "bank_name": "Test Bank", "account_number": "0000123456789"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 502


def test_add_bank_account_unauthenticated_401(client, db_session):
    resp = client.post(
        "/me/bank-accounts",
        json={"account_holder_name": "Test User", "bank_name": "Test Bank", "account_number": "0000123456789"},
    )
    assert resp.status_code == 401


def test_list_bank_accounts_scoped_to_current_user(client, db_session):
    user = make_user(db_session, "listbank1")
    fake_list = [{"id": 5, "accountHolderName": "Test User", "bankName": "Test Bank",
                  "lastFour": "6789", "status": "VERIFIED", "createdAt": "2026-09-26T10:00:00"}]

    with patch("wallet_client.list_bank_accounts", return_value=fake_list) as mock_list:
        resp = client.get("/me/bank-accounts", headers=auth_headers(user))

    assert resp.status_code == 200
    assert resp.json() == fake_list
    mock_list.assert_called_once_with(user.id)


def test_verify_bank_account_scoped_to_current_user(client, db_session):
    user = make_user(db_session, "verifybank1")
    fake_response = {"id": 5, "accountHolderName": "Test User", "bankName": "Test Bank",
                      "lastFour": "6789", "status": "VERIFIED", "createdAt": "2026-09-26T10:00:00"}

    with patch("wallet_client.verify_bank_account", return_value=fake_response) as mock_verify:
        resp = client.post("/me/bank-accounts/5/verify", headers=auth_headers(user))

    assert resp.status_code == 200
    mock_verify.assert_called_once_with(user.id, 5)


def test_disable_bank_account_scoped_to_current_user(client, db_session):
    user = make_user(db_session, "disablebank1")
    fake_response = {"id": 5, "accountHolderName": "Test User", "bankName": "Test Bank",
                      "lastFour": "6789", "status": "DISABLED", "createdAt": "2026-09-26T10:00:00"}

    with patch("wallet_client.disable_bank_account", return_value=fake_response) as mock_disable:
        resp = client.post("/me/bank-accounts/5/disable", headers=auth_headers(user))

    assert resp.status_code == 200
    mock_disable.assert_called_once_with(user.id, 5)


# ---------------------------------------------------------------------------
# Withdrawals below the step-up threshold - process immediately
# ---------------------------------------------------------------------------

def test_withdraw_below_threshold_calls_wallet_client_immediately(client, db_session):
    user = make_user(db_session, "withdraw1")
    fake_response = {
        "id": 1, "status": "COMPLETED", "amount": 500.0, "currency": "USD",
        "destinationReference": "Demo Bank ****6789", "failureReason": None,
        "providerReference": "demo-ref-123", "bankAccountId": 42,
    }

    with patch("wallet_client.withdraw", return_value=fake_response) as mock_withdraw:
        resp = client.post(
            "/me/funds/withdraw",
            json={"amount": 500.0, "currency": "USD", "bank_account_id": 42, "idempotency_key": "test-key-1"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    assert resp.json() == fake_response
    mock_withdraw.assert_called_once_with(user.id, 500.0, "USD", 42, "test-key-1")


def test_withdraw_just_below_threshold_processes_immediately(client, db_session):
    user = make_user(db_session, "withdrawboundary1")
    fake_response = {
        "id": 2, "status": "COMPLETED", "amount": 999.99, "currency": "USD",
        "destinationReference": "Demo Bank ****6789", "failureReason": None,
        "providerReference": "demo-ref-124", "bankAccountId": 42,
    }

    with patch("wallet_client.withdraw", return_value=fake_response) as mock_withdraw, \
         patch("email_client.send_email") as mock_send:
        resp = client.post(
            "/me/funds/withdraw",
            json={"amount": 999.99, "currency": "USD", "bank_account_id": 42, "idempotency_key": "test-key-boundary1"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "COMPLETED"
    mock_withdraw.assert_called_once()
    mock_send.assert_not_called()


def test_withdraw_below_threshold_failure_returns_400(client, db_session):
    user = make_user(db_session, "withdraw2")
    fake_response = {
        "id": 1, "status": "FAILED", "amount": 500.0, "currency": "USD",
        "destinationReference": None, "failureReason": "Insufficient available funds",
        "providerReference": None, "bankAccountId": 42,
    }

    with patch("wallet_client.withdraw", return_value=fake_response):
        resp = client.post(
            "/me/funds/withdraw",
            json={"amount": 500.0, "currency": "USD", "bank_account_id": 42, "idempotency_key": "test-key-2"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Insufficient available funds"


def test_withdraw_wallet_service_unavailable_502(client, db_session):
    user = make_user(db_session, "withdraw3")

    with patch("wallet_client.withdraw", side_effect=RuntimeError("Wallet service error 500: boom")):
        resp = client.post(
            "/me/funds/withdraw",
            json={"amount": 500.0, "currency": "USD", "bank_account_id": 42, "idempotency_key": "test-key-3"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Withdrawals at/above the step-up threshold - confirmation required first
# ---------------------------------------------------------------------------

def test_withdraw_at_threshold_requires_confirmation_and_does_not_move_money_yet(client, db_session):
    user = make_user(db_session, "stepup1")

    with patch("wallet_client.withdraw") as mock_withdraw, patch("email_client.send_email") as mock_send:
        resp = client.post(
            "/me/funds/withdraw",
            json={"amount": 1000.0, "currency": "USD", "bank_account_id": 42, "idempotency_key": "test-key-stepup1"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "CONFIRMATION_REQUIRED"
    mock_withdraw.assert_not_called()
    mock_send.assert_called_once()
    assert mock_send.call_args.args[0] == user.email

    confirmations = db_session.query(WithdrawalConfirmation).filter(WithdrawalConfirmation.user_id == user.id).all()
    assert len(confirmations) == 1
    assert confirmations[0].used_at is None
    assert float(confirmations[0].amount) == 1000.0
    assert confirmations[0].bank_account_id == 42
    assert confirmations[0].idempotency_key == "test-key-stepup1"


def test_withdraw_above_threshold_email_not_configured_502(client, db_session):
    user = make_user(db_session, "stepup2")

    with patch("wallet_client.withdraw") as mock_withdraw, \
         patch("email_client.send_email", side_effect=RuntimeError("EMAIL_API_KEY and EMAIL_DOMAIN must be set")):
        resp = client.post(
            "/me/funds/withdraw",
            json={"amount": 1000.0, "currency": "USD", "bank_account_id": 42, "idempotency_key": "test-key-stepup2"},
            headers=auth_headers(user),
        )

    assert resp.status_code == 502
    mock_withdraw.assert_not_called()


def test_withdraw_confirm_round_trip_completes_withdrawal(client, db_session):
    user = make_user(db_session, "confirmround1")
    fake_response = {
        "id": 9, "status": "COMPLETED", "amount": 1500.0, "currency": "USD",
        "destinationReference": "Demo Bank ****6789", "failureReason": None,
        "providerReference": "demo-ref-999", "bankAccountId": 42,
    }

    with patch("wallet_client.withdraw", return_value=fake_response) as mock_withdraw, \
         patch("email_client.send_email") as mock_send:
        resp = client.post(
            "/me/funds/withdraw",
            json={"amount": 1500.0, "currency": "USD", "bank_account_id": 42, "idempotency_key": "test-key-round1"},
            headers=auth_headers(user),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "CONFIRMATION_REQUIRED"
        raw_token = _extract_token(mock_send)
        mock_withdraw.assert_not_called()

        confirm_resp = client.post(
            "/me/funds/withdraw/confirm",
            json={"token": raw_token},
            headers=auth_headers(user),
        )

    assert confirm_resp.status_code == 200
    assert confirm_resp.json() == fake_response
    mock_withdraw.assert_called_once_with(user.id, 1500.0, "USD", 42, "test-key-round1")

    confirmation = db_session.query(WithdrawalConfirmation).filter(WithdrawalConfirmation.user_id == user.id).first()
    assert confirmation.used_at is not None


def test_withdraw_confirm_reused_token_rejected(client, db_session):
    user = make_user(db_session, "confirmreuse1")
    fake_response = {
        "id": 9, "status": "COMPLETED", "amount": 1500.0, "currency": "USD",
        "destinationReference": "Demo Bank ****6789", "failureReason": None,
        "providerReference": "demo-ref-999", "bankAccountId": 42,
    }

    with patch("wallet_client.withdraw", return_value=fake_response), patch("email_client.send_email") as mock_send:
        client.post(
            "/me/funds/withdraw",
            json={"amount": 1500.0, "currency": "USD", "bank_account_id": 42, "idempotency_key": "test-key-reuse1"},
            headers=auth_headers(user),
        )
        raw_token = _extract_token(mock_send)

        first_confirm = client.post("/me/funds/withdraw/confirm", json={"token": raw_token}, headers=auth_headers(user))
        assert first_confirm.status_code == 200

        second_confirm = client.post("/me/funds/withdraw/confirm", json={"token": raw_token}, headers=auth_headers(user))

    assert second_confirm.status_code == 400
    assert second_confirm.json()["detail"] == GENERIC_CONFIRM_ERROR


def test_withdraw_confirm_invalid_token_400(client, db_session):
    user = make_user(db_session, "confirminvalid1")

    resp = client.post(
        "/me/funds/withdraw/confirm",
        json={"token": "totally-bogus-token"},
        headers=auth_headers(user),
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == GENERIC_CONFIRM_ERROR


def test_withdraw_confirm_expired_token_400(client, db_session):
    user = make_user(db_session, "confirmexpired1")
    raw_token = "expired-withdrawal-token-1234567890"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    expired_row = WithdrawalConfirmation(
        user_id=user.id,
        token_hash=token_hash,
        amount=1000.00,
        currency="USD",
        bank_account_id=42,
        idempotency_key="expired-key-1",
        created_at=datetime.utcnow() - timedelta(hours=1),
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        used_at=None,
    )
    db_session.add(expired_row)
    db_session.commit()

    resp = client.post(
        "/me/funds/withdraw/confirm",
        json={"token": raw_token},
        headers=auth_headers(user),
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == GENERIC_CONFIRM_ERROR


def test_withdraw_confirm_wrong_user_400_and_message_identical_to_other_failures(client, db_session):
    owner = make_user(db_session, "confirmowner1")
    attacker = make_user(db_session, "confirmattacker1")
    raw_token = "someone-elses-token-1234567890"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    row = WithdrawalConfirmation(
        user_id=owner.id,
        token_hash=token_hash,
        amount=1000.00,
        currency="USD",
        bank_account_id=42,
        idempotency_key="owner-key-1",
        created_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(minutes=15),
        used_at=None,
    )
    db_session.add(row)
    db_session.commit()

    resp = client.post(
        "/me/funds/withdraw/confirm",
        json={"token": raw_token},
        headers=auth_headers(attacker),
    )

    assert resp.status_code == 400
    # Same message as every other failure mode (not found / used / expired) -
    # deliberate, so a response can't be used to fingerprint which case it hit.
    assert resp.json()["detail"] == GENERIC_CONFIRM_ERROR


def test_withdraw_confirm_unauthenticated_401(client, db_session):
    resp = client.post("/me/funds/withdraw/confirm", json={"token": "whatever"})
    assert resp.status_code == 401
