"""
Tests for the new PUT /investor-eligibility/{id}/verify endpoint,
2026-09-21 - closes a real design inconsistency found while building the
InvestorEligibility frontend: unlike Evidence/KYCFact/ROFR/LoanRequest,
InvestorEligibility previously had no self-submit/admin-verify PUT
endpoint at all - the only way to mark a record "verified" was for an
admin to create a brand-new record directly. This adds the missing
verify endpoint, mirroring PUT /kyc-facts/{id}/verify exactly.
Written against the REAL ~/KEVO implementation.
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

from models import Base, User as UserModel, InvestorEligibility
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
        email=f"eligverify{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_eligibility(db, buyer, classification="accredited", status="pending"):
    record = InvestorEligibility(
        buyer_id=buyer.id,
        investor_type="individual",
        classification=classification,
        status=status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


# --- PUT /investor-eligibility/{id}/verify ---

def test_admin_can_verify_record(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_eligibility(db_session, buyer, status="pending")

    resp = client.put(
        f"/investor-eligibility/{record.id}/verify",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["investor_eligibility"]["status"] == "verified"

    db_session.refresh(record)
    assert record.status == "verified"


def test_admin_can_reject_record(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_eligibility(db_session, buyer, status="pending")

    resp = client.put(
        f"/investor-eligibility/{record.id}/verify",
        params={"status": "rejected"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["investor_eligibility"]["status"] == "rejected"


def test_participant_cannot_verify_403(client, db_session):
    buyer = make_user(db_session, "1")
    stranger = make_user(db_session, "2")
    record = make_eligibility(db_session, buyer, status="pending")

    resp = client.put(
        f"/investor-eligibility/{record.id}/verify",
        params={"status": "verified"},
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 403


def test_buyer_cannot_self_verify_403(client, db_session):
    buyer = make_user(db_session, "1")
    record = make_eligibility(db_session, buyer, status="pending")

    resp = client.put(
        f"/investor-eligibility/{record.id}/verify",
        params={"status": "verified"},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 403


def test_verify_invalid_status_400(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_eligibility(db_session, buyer, status="pending")

    resp = client.put(
        f"/investor-eligibility/{record.id}/verify",
        params={"status": "bogus"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400


def test_verify_not_found_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")

    resp = client.put(
        "/investor-eligibility/999999/verify",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 404


def test_verify_unauthenticated_401(client, db_session):
    buyer = make_user(db_session, "1")
    record = make_eligibility(db_session, buyer, status="pending")

    resp = client.put(
        f"/investor-eligibility/{record.id}/verify",
        params={"status": "verified"},
    )
    assert resp.status_code == 401


def test_verify_response_includes_full_record(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    record = make_eligibility(db_session, buyer, classification="sophisticated", status="pending")

    resp = client.put(
        f"/investor-eligibility/{record.id}/verify",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    body = resp.json()["investor_eligibility"]
    assert body["id"] == record.id
    assert body["buyer_id"] == buyer.id
    assert body["classification"] == "sophisticated"
    assert body["status"] == "verified"
