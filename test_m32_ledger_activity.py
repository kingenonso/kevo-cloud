"""
Tests for M32's ledger/activity-history endpoint, GET /me/funds/activity,
2026-10-25 - the itemized transaction/activity list over the wallet's
double-entry ledger ("bank-app style"), the one remaining named gap in the
M32 wallet milestone.

Same discipline as test_m32_wallet.py: this mocks wallet_client entirely
rather than requiring the real kevo-wallet-service (Java) to be running.
The underlying Java pagination/ordering logic (WalletService.getLedgerEntries,
the GET /internal/wallets/{kevoUserId}/ledger-entries endpoint) has its own
real-Postgres tests in kevo-wallet-service itself
(WalletLedgerEntriesTest.java). What this file covers is what's uniquely
KEVO's own responsibility: that the endpoint is scoped to current_user.id,
that limit/offset pass through unmodified, and error handling when the
wallet service is unreachable.

Written against the REAL ~/KEVO implementation. Like the rest of this
session's work, this was NOT run against a live server - this sandbox has
no .env file for the Python app, so pytest cannot start here. These tests
are hand-verified against app.py/wallet_client.py's actual code, following
test_m32_wallet.py's exact fixture/mocking pattern, but not executed.
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


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_user(db, suffix="1"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"ledgeract{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type="participant",
        kyc_status="verified",
        hashed_password=hash_password("password123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


FAKE_ENTRIES = [
    {
        "id": 42, "ledgerTransactionId": 7, "direction": "CREDIT", "bucket": "AVAILABLE",
        "entryType": "DEPOSIT", "amount": 100.00, "currency": "USD",
        "description": "Wallet funding via DemoProvider", "relatedMarketplaceTransactionId": None,
        "reversesEntryId": None, "createdAt": "2026-10-20T10:00:00",
    },
    {
        "id": 41, "ledgerTransactionId": 6, "direction": "DEBIT", "bucket": "AVAILABLE",
        "entryType": "WITHDRAWAL", "amount": 25.00, "currency": "USD",
        "description": "Withdrawal to bank account", "relatedMarketplaceTransactionId": None,
        "reversesEntryId": None, "createdAt": "2026-10-19T10:00:00",
    },
]


def test_get_activity_scoped_to_current_user(client, db_session):
    user = make_user(db_session, "activity1")

    with patch("wallet_client.get_ledger_entries", return_value=FAKE_ENTRIES) as mock_get:
        resp = client.get("/me/funds/activity", headers=auth_headers(user))

    assert resp.status_code == 200
    assert resp.json() == FAKE_ENTRIES
    mock_get.assert_called_once_with(user.id, 50, 0)


def test_get_activity_passes_through_limit_and_offset(client, db_session):
    user = make_user(db_session, "activity2")

    with patch("wallet_client.get_ledger_entries", return_value=[]) as mock_get:
        resp = client.get("/me/funds/activity?limit=10&offset=20", headers=auth_headers(user))

    assert resp.status_code == 200
    mock_get.assert_called_once_with(user.id, 10, 20)


def test_get_activity_wallet_service_unavailable_502(client, db_session):
    user = make_user(db_session, "activity3")

    with patch("wallet_client.get_ledger_entries", side_effect=RuntimeError("Wallet service error 500: boom")):
        resp = client.get("/me/funds/activity", headers=auth_headers(user))

    assert resp.status_code == 502


def test_get_activity_unauthenticated_401(client, db_session):
    resp = client.get("/me/funds/activity")
    assert resp.status_code == 401


def test_get_activity_two_users_isolated_by_id(client, db_session):
    user_a = make_user(db_session, "activity4a")
    user_b = make_user(db_session, "activity4b")

    with patch("wallet_client.get_ledger_entries", return_value=[]) as mock_get:
        client.get("/me/funds/activity", headers=auth_headers(user_a))
        client.get("/me/funds/activity", headers=auth_headers(user_b))

    called_user_ids = [call.args[0] for call in mock_get.call_args_list]
    assert called_user_ids == [user_a.id, user_b.id]
    assert user_a.id != user_b.id
