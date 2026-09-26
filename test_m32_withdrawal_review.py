"""
Tests for the admin withdrawal-review endpoints added while closing out
M32 item 5 (Section 21 API security pass), 2026-09-26.

WithdrawalRiskService (kevo-wallet-service, Java) can hold a withdrawal as
PENDING_REVIEW instead of processing it - but until this change, nothing
in KEVO's own Python API could ever list one or resolve it, so a held
withdrawal was stuck forever with no recovery path. These three endpoints
close that gap: GET /admin/withdrawals/pending-review, and PUT .../approve
and .../reject.

Same discipline as test_m32_wallet.py: mocks wallet_client entirely rather
than requiring the real Java service to be running. What's KEVO's own
responsibility here - and what these tests actually cover - is that these
are genuinely admin-only (not just any logged-in user), that the wallet
service is called with the right arguments, that a reject reason is
passed through, that each action is audit-logged, and that a wallet
service outage surfaces as a clean 502 rather than a crash.
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

from models import Base, User as UserModel, AuditLogEntry
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


def make_user(db, suffix="1", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"review{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type=account_type,
        hashed_password=hash_password("password123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_admin(db, suffix="admin1"):
    return make_user(db, suffix, account_type="admin")


PENDING_REVIEW_LISTING = [
    {
        "id": 42, "kevoUserId": 999, "walletId": 7, "amount": 4200.00, "currency": "USD",
        "bankAccountId": 3, "riskLevel": "HIGH",
        "reviewNotes": "NEW_DESTINATION_ACCOUNT: ... | AMOUNT_FAR_ABOVE_HISTORY: ...",
        "createdAt": "2026-09-26T10:00:00",
    }
]


def test_pending_review_listing_rejects_non_admin(client, db_session):
    user = make_user(db_session, "notadmin1")
    resp = client.get("/admin/withdrawals/pending-review", headers=auth_headers(user))
    assert resp.status_code == 403


def test_pending_review_listing_allows_admin(client, db_session):
    admin = make_admin(db_session, "admin1")
    with patch("wallet_client.list_pending_review_withdrawals", return_value=PENDING_REVIEW_LISTING) as mock_list:
        resp = client.get("/admin/withdrawals/pending-review", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json() == PENDING_REVIEW_LISTING
    mock_list.assert_called_once_with()


def test_pending_review_listing_unauthenticated_401(client, db_session):
    resp = client.get("/admin/withdrawals/pending-review")
    assert resp.status_code == 401


def test_pending_review_listing_wallet_service_unavailable_502(client, db_session):
    admin = make_admin(db_session, "admin2")
    with patch("wallet_client.list_pending_review_withdrawals", side_effect=RuntimeError("Wallet service error 500: boom")):
        resp = client.get("/admin/withdrawals/pending-review", headers=auth_headers(admin))
    assert resp.status_code == 502


def test_approve_withdrawal_rejects_non_admin(client, db_session):
    user = make_user(db_session, "notadmin2")
    resp = client.put("/admin/withdrawals/999/42/approve", headers=auth_headers(user))
    assert resp.status_code == 403


def test_approve_withdrawal_allows_admin_and_audit_logs(client, db_session):
    admin = make_admin(db_session, "admin3")
    fake_response = {"id": 42, "status": "COMPLETED", "amount": 4200.00, "currency": "USD"}

    with patch("wallet_client.approve_withdrawal", return_value=fake_response) as mock_approve:
        resp = client.put("/admin/withdrawals/999/42/approve", headers=auth_headers(admin))

    assert resp.status_code == 200
    assert resp.json() == fake_response
    mock_approve.assert_called_once_with(999, 42)

    entries = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "withdrawal_approved_after_review",
        AuditLogEntry.target_id == 999,
    ).all()
    assert len(entries) == 1
    assert entries[0].actor_user_id == admin.id
    assert "42" in entries[0].detail


def test_approve_withdrawal_wallet_service_unavailable_502(client, db_session):
    admin = make_admin(db_session, "admin4")
    with patch("wallet_client.approve_withdrawal", side_effect=RuntimeError("Wallet service error 409: not pending review")):
        resp = client.put("/admin/withdrawals/999/42/approve", headers=auth_headers(admin))
    assert resp.status_code == 502


def test_reject_withdrawal_rejects_non_admin(client, db_session):
    user = make_user(db_session, "notadmin3")
    resp = client.put("/admin/withdrawals/999/42/reject", json={"reason": "looks fraudulent"}, headers=auth_headers(user))
    assert resp.status_code == 403


def test_reject_withdrawal_allows_admin_passes_reason_and_audit_logs(client, db_session):
    admin = make_admin(db_session, "admin5")
    fake_response = {"id": 42, "status": "FAILED", "failureReason": "looks fraudulent"}

    with patch("wallet_client.reject_withdrawal", return_value=fake_response) as mock_reject:
        resp = client.put(
            "/admin/withdrawals/999/42/reject",
            json={"reason": "looks fraudulent"},
            headers=auth_headers(admin),
        )

    assert resp.status_code == 200
    assert resp.json() == fake_response
    mock_reject.assert_called_once_with(999, 42, "looks fraudulent")

    entries = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "withdrawal_rejected_after_review",
        AuditLogEntry.target_id == 999,
    ).all()
    assert len(entries) == 1
    assert "looks fraudulent" in entries[0].detail


def test_reject_withdrawal_unauthenticated_401(client, db_session):
    resp = client.put("/admin/withdrawals/999/42/reject", json={"reason": "x"})
    assert resp.status_code == 401
