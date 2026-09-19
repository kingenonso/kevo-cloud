"""
Tests for M26B's first slice (2026-09-19): Share-Backed Lending Marketplace,
broker/matcher only.

KEVO never originates a loan, never funds one, and never takes or holds
collateral. POST /loan-requests lets a holder request a loan against their
own verified ownership record. Admin-only endpoints record a match to a
real external lender, decline a request, or close it once the real lender
has taken over. State machine: requested -> matched -> closed, or
requested -> withdrawn (holder) / declined (admin).
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base, User as UserModel, OwnershipRecord, LoanRequest,
)
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


def make_user(db, suffix="1", role="buyer", account_type="participant", kyc_status="not_started"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m26buser{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_ownership_record(db, seller, quantity=1000, verification_status="verified"):
    record = OwnershipRecord(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=quantity, verification_status=verification_status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def make_loan_request(db, holder, ownership_record, requested_amount=10000.0, status="requested"):
    loan_request = LoanRequest(
        holder_id=holder.id, ownership_record_id=ownership_record.id,
        requested_amount=requested_amount, status=status,
    )
    db.add(loan_request)
    db.commit()
    db.refresh(loan_request)
    return loan_request


# --- POST /loan-requests ---

def test_holder_can_create_loan_request(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder)

    resp = client.post(
        "/loan-requests", headers=auth_headers(holder),
        params={"ownership_record_id": record.id, "requested_amount": 5000.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "requested"
    assert body["holder_id"] == holder.id
    assert body["ownership_record_id"] == record.id
    assert float(body["requested_amount"]) == 5000.0


def test_create_against_others_record_403(client, db_session):
    holder = make_user(db_session, "1")
    other = make_user(db_session, "2")
    record = make_ownership_record(db_session, other)

    resp = client.post(
        "/loan-requests", headers=auth_headers(holder),
        params={"ownership_record_id": record.id, "requested_amount": 5000.0},
    )
    assert resp.status_code == 403


def test_create_against_unverified_record_400(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder, verification_status="pending")

    resp = client.post(
        "/loan-requests", headers=auth_headers(holder),
        params={"ownership_record_id": record.id, "requested_amount": 5000.0},
    )
    assert resp.status_code == 400


def test_create_unknown_ownership_record_404(client, db_session):
    holder = make_user(db_session, "1")
    resp = client.post(
        "/loan-requests", headers=auth_headers(holder),
        params={"ownership_record_id": 999999, "requested_amount": 5000.0},
    )
    assert resp.status_code == 404


def test_create_non_positive_amount_400(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder)

    resp = client.post(
        "/loan-requests", headers=auth_headers(holder),
        params={"ownership_record_id": record.id, "requested_amount": 0},
    )
    assert resp.status_code == 400


def test_create_unauthenticated_401(client, db_session):
    resp = client.post("/loan-requests", params={"ownership_record_id": 1, "requested_amount": 5000.0})
    assert resp.status_code == 401


# --- PUT /loan-requests/{id}/withdraw ---

def test_holder_can_withdraw_own_request(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.put(f"/loan-requests/{loan_request.id}/withdraw", headers=auth_headers(holder))
    assert resp.status_code == 200
    assert resp.json()["status"] == "withdrawn"


def test_non_holder_cannot_withdraw_403(client, db_session):
    holder = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.put(f"/loan-requests/{loan_request.id}/withdraw", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_withdraw_wrong_status_400(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record, status="matched")

    resp = client.put(f"/loan-requests/{loan_request.id}/withdraw", headers=auth_headers(holder))
    assert resp.status_code == 400


def test_withdraw_unknown_id_404(client, db_session):
    holder = make_user(db_session, "1")
    resp = client.put("/loan-requests/999999/withdraw", headers=auth_headers(holder))
    assert resp.status_code == 404


def test_withdraw_unauthenticated_401(client, db_session):
    resp = client.put("/loan-requests/1/withdraw")
    assert resp.status_code == 401


# --- PUT /loan-requests/{id}/match ---

def test_admin_can_match_loan_request(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.put(
        f"/loan-requests/{loan_request.id}/match", headers=auth_headers(admin),
        params={"external_lender_name": "Real Lender LLC", "external_lender_reference": "LN-001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "matched"
    assert body["external_lender_name"] == "Real Lender LLC"
    assert body["external_lender_reference"] == "LN-001"
    assert body["matched_at"] is not None


def test_non_admin_cannot_match_403(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.put(
        f"/loan-requests/{loan_request.id}/match", headers=auth_headers(holder),
        params={"external_lender_name": "Real Lender LLC"},
    )
    assert resp.status_code == 403


def test_match_wrong_status_400(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record, status="withdrawn")

    resp = client.put(
        f"/loan-requests/{loan_request.id}/match", headers=auth_headers(admin),
        params={"external_lender_name": "Real Lender LLC"},
    )
    assert resp.status_code == 400


def test_match_unknown_id_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put(
        "/loan-requests/999999/match", headers=auth_headers(admin),
        params={"external_lender_name": "Real Lender LLC"},
    )
    assert resp.status_code == 404


def test_match_unauthenticated_401(client, db_session):
    resp = client.put("/loan-requests/1/match", params={"external_lender_name": "Real Lender LLC"})
    assert resp.status_code == 401


# --- PUT /loan-requests/{id}/decline ---

def test_admin_can_decline_loan_request(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.put(f"/loan-requests/{loan_request.id}/decline", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"


def test_non_admin_cannot_decline_403(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.put(f"/loan-requests/{loan_request.id}/decline", headers=auth_headers(holder))
    assert resp.status_code == 403


def test_decline_wrong_status_400(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record, status="matched")

    resp = client.put(f"/loan-requests/{loan_request.id}/decline", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_decline_unknown_id_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put("/loan-requests/999999/decline", headers=auth_headers(admin))
    assert resp.status_code == 404


# --- PUT /loan-requests/{id}/close ---

def test_admin_can_close_matched_request(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record, status="matched")

    resp = client.put(f"/loan-requests/{loan_request.id}/close", headers=auth_headers(admin))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None


def test_non_admin_cannot_close_403(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record, status="matched")

    resp = client.put(f"/loan-requests/{loan_request.id}/close", headers=auth_headers(holder))
    assert resp.status_code == 403


def test_close_wrong_status_400(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record, status="requested")

    resp = client.put(f"/loan-requests/{loan_request.id}/close", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_close_unknown_id_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put("/loan-requests/999999/close", headers=auth_headers(admin))
    assert resp.status_code == 404


# --- GET /loan-requests (list) ---

def test_list_scoped_to_own_requests(client, db_session):
    holder = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    record = make_ownership_record(db_session, holder)
    make_loan_request(db_session, holder, record)

    resp_holder = client.get("/loan-requests", headers=auth_headers(holder))
    assert resp_holder.status_code == 200
    assert len(resp_holder.json()) == 1

    resp_stranger = client.get("/loan-requests", headers=auth_headers(stranger))
    assert resp_stranger.status_code == 200
    assert len(resp_stranger.json()) == 0


def test_admin_sees_all_in_list(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_ownership_record(db_session, holder)
    make_loan_request(db_session, holder, record)

    resp = client.get("/loan-requests", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_unauthenticated_401(client, db_session):
    resp = client.get("/loan-requests")
    assert resp.status_code == 401


# --- GET /loan-requests/{id} ---

def test_get_by_id_holder_succeeds(client, db_session):
    holder = make_user(db_session, "1")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.get(f"/loan-requests/{loan_request.id}", headers=auth_headers(holder))
    assert resp.status_code == 200


def test_get_by_id_admin_succeeds(client, db_session):
    holder = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.get(f"/loan-requests/{loan_request.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_get_by_id_non_holder_403(client, db_session):
    holder = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    record = make_ownership_record(db_session, holder)
    loan_request = make_loan_request(db_session, holder, record)

    resp = client.get(f"/loan-requests/{loan_request.id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_get_by_id_unknown_404(client, db_session):
    holder = make_user(db_session, "1")
    resp = client.get("/loan-requests/999999", headers=auth_headers(holder))
    assert resp.status_code == 404


def test_get_by_id_unauthenticated_401(client, db_session):
    resp = client.get("/loan-requests/1")
    assert resp.status_code == 401
