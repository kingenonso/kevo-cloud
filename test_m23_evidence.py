"""
Tests for M23 (2026-09-18), first slice - the real gap found during the
audit: Evidence (referenced by KYCFact, TransferabilityFact,
OfferingFact, PositionEvent, and read directly by the Deal Health
Score's documentation dimension and M14B's completion-trigger logic)
had zero endpoints anywhere, meaning nobody could ever actually create
a record - real row count was 0. Adds self-submit/admin-verify create,
admin-verify, and scoped list/get, mirroring the established KYCFact
and InvestorEligibility patterns, plus a file_hash tamper-evidence
field. Written against the REAL ~/KEVO implementation.
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

from models import Base, User as UserModel, Listing, OwnershipRecord, Transaction, Evidence
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


def make_user(db, suffix="1", role="buyer", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m23user{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller):
    listing = Listing(
        seller_id=seller.id,
        company="Acme Private Co",
        asset_type="common_stock",
        quantity=100,
        asking_price=10000,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_transaction(db, listing, buyer, seller):
    txn = Transaction(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        quantity=10,
        agreed_price=1000,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_ownership_record(db, seller):
    record = OwnershipRecord(
        seller_id=seller.id,
        company="Acme Private Co",
        asset_type="common_stock",
        quantity=100,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def evidence_payload(user_id, **overrides):
    payload = {
        "user_id": user_id,
        "evidence_type": "identity_document",
        "description": "Passport scan",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Create (self-submit / admin-submit)
# ---------------------------------------------------------------------------

def test_self_submit_evidence_succeeds_pending(client, db_session):
    user = make_user(db_session, "1")
    resp = client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    assert resp.status_code == 200
    body = resp.json()["evidence"]
    assert body["user_id"] == user.id
    assert body["verification_status"] == "pending"


def test_submit_evidence_for_another_user_403(client, db_session):
    user = make_user(db_session, "1")
    other = make_user(db_session, "2")
    resp = client.post("/evidence", json=evidence_payload(other.id), headers=auth_headers(user))
    assert resp.status_code == 403


def test_admin_can_submit_evidence_for_another_user(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    other = make_user(db_session, "2")
    resp = client.post("/evidence", json=evidence_payload(other.id), headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["evidence"]["user_id"] == other.id


def test_submit_evidence_unauthenticated_401(client, db_session):
    user = make_user(db_session, "1")
    resp = client.post("/evidence", json=evidence_payload(user.id))
    assert resp.status_code == 401


def test_submit_evidence_nonexistent_user_404(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    resp = client.post("/evidence", json=evidence_payload(999999), headers=auth_headers(admin))
    assert resp.status_code == 404


def test_file_reference_without_hash_rejected_400(client, db_session):
    user = make_user(db_session, "1")
    resp = client.post(
        "/evidence",
        json=evidence_payload(user.id, file_reference="https://example.com/doc.pdf"),
        headers=auth_headers(user),
    )
    assert resp.status_code == 400


def test_file_reference_with_hash_succeeds(client, db_session):
    user = make_user(db_session, "1")
    resp = client.post(
        "/evidence",
        json=evidence_payload(
            user.id,
            file_reference="https://example.com/doc.pdf",
            file_hash="a" * 64,
        ),
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["evidence"]["file_hash"] == "a" * 64


def test_submit_evidence_with_real_linked_resources_succeeds(client, db_session):
    user = make_user(db_session, "1")
    listing = make_listing(db_session, user)
    txn = make_transaction(db_session, listing, buyer=make_user(db_session, "2"), seller=user)
    record = make_ownership_record(db_session, user)

    resp = client.post(
        "/evidence",
        json=evidence_payload(
            user.id,
            listing_id=listing.id,
            transaction_id=txn.id,
            ownership_record_id=record.id,
        ),
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    body = resp.json()["evidence"]
    assert body["listing_id"] == listing.id
    assert body["transaction_id"] == txn.id
    assert body["ownership_record_id"] == record.id


def test_submit_evidence_nonexistent_listing_404(client, db_session):
    user = make_user(db_session, "1")
    resp = client.post(
        "/evidence",
        json=evidence_payload(user.id, listing_id=999999),
        headers=auth_headers(user),
    )
    assert resp.status_code == 404


def test_submit_evidence_nonexistent_transaction_404(client, db_session):
    user = make_user(db_session, "1")
    resp = client.post(
        "/evidence",
        json=evidence_payload(user.id, transaction_id=999999),
        headers=auth_headers(user),
    )
    assert resp.status_code == 404


def test_submit_evidence_nonexistent_ownership_record_404(client, db_session):
    user = make_user(db_session, "1")
    resp = client.post(
        "/evidence",
        json=evidence_payload(user.id, ownership_record_id=999999),
        headers=auth_headers(user),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Verify (admin-only)
# ---------------------------------------------------------------------------

def test_admin_verify_succeeds(client, db_session):
    user = make_user(db_session, "1")
    admin = make_user(db_session, "admin", account_type="admin")
    create_resp = client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    evidence_id = create_resp.json()["evidence"]["id"]

    resp = client.put(f"/evidence/{evidence_id}/verify?status=verified", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["evidence"]["verification_status"] == "verified"


def test_admin_reject_succeeds(client, db_session):
    user = make_user(db_session, "1")
    admin = make_user(db_session, "admin", account_type="admin")
    create_resp = client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    evidence_id = create_resp.json()["evidence"]["id"]

    resp = client.put(f"/evidence/{evidence_id}/verify?status=rejected", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["evidence"]["verification_status"] == "rejected"


def test_non_admin_cannot_verify_403(client, db_session):
    user = make_user(db_session, "1")
    create_resp = client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    evidence_id = create_resp.json()["evidence"]["id"]

    resp = client.put(f"/evidence/{evidence_id}/verify?status=verified", headers=auth_headers(user))
    assert resp.status_code == 403


def test_verify_unauthenticated_401(client, db_session):
    resp = client.put("/evidence/1/verify?status=verified")
    assert resp.status_code == 401


def test_verify_invalid_status_400(client, db_session):
    user = make_user(db_session, "1")
    admin = make_user(db_session, "admin", account_type="admin")
    create_resp = client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    evidence_id = create_resp.json()["evidence"]["id"]

    resp = client.put(f"/evidence/{evidence_id}/verify?status=maybe", headers=auth_headers(admin))
    assert resp.status_code == 400


def test_verify_nonexistent_evidence_404(client, db_session):
    admin = make_user(db_session, "admin", account_type="admin")
    resp = client.put("/evidence/999999/verify?status=verified", headers=auth_headers(admin))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List / get-by-id
# ---------------------------------------------------------------------------

def test_list_evidence_own_only(client, db_session):
    user = make_user(db_session, "1")
    other = make_user(db_session, "2")
    admin = make_user(db_session, "admin", account_type="admin")
    client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    client.post("/evidence", json=evidence_payload(other.id), headers=auth_headers(admin))

    resp = client.get("/evidence", headers=auth_headers(user))
    assert resp.status_code == 200
    records = resp.json()
    assert len(records) == 1
    assert records[0]["user_id"] == user.id


def test_list_evidence_admin_sees_all(client, db_session):
    user = make_user(db_session, "1")
    other = make_user(db_session, "2")
    admin = make_user(db_session, "admin", account_type="admin")
    client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    client.post("/evidence", json=evidence_payload(other.id), headers=auth_headers(admin))

    resp = client.get("/evidence", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_evidence_unauthenticated_401(client, db_session):
    resp = client.get("/evidence")
    assert resp.status_code == 401


def test_get_evidence_by_id_owner_200(client, db_session):
    user = make_user(db_session, "1")
    create_resp = client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    evidence_id = create_resp.json()["evidence"]["id"]

    resp = client.get(f"/evidence/{evidence_id}", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["evidence"]["id"] == evidence_id


def test_get_evidence_by_id_stranger_403(client, db_session):
    user = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    create_resp = client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    evidence_id = create_resp.json()["evidence"]["id"]

    resp = client.get(f"/evidence/{evidence_id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_get_evidence_by_id_admin_200(client, db_session):
    user = make_user(db_session, "1")
    admin = make_user(db_session, "admin", account_type="admin")
    create_resp = client.post("/evidence", json=evidence_payload(user.id), headers=auth_headers(user))
    evidence_id = create_resp.json()["evidence"]["id"]

    resp = client.get(f"/evidence/{evidence_id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_get_evidence_by_id_404_unknown(client, db_session):
    user = make_user(db_session, "1")
    resp = client.get("/evidence/999999", headers=auth_headers(user))
    assert resp.status_code == 404
