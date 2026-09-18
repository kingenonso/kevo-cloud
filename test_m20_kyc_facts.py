"""
Tests for M20 KYC/AML architecture, first slice (2026-09-18) - structured,
evidence-backed KYCFact records, mirroring the InvestorEligibility
self-submit / admin-verify pattern and staying fully M19-compliant
(identity-to-resource authorization). Written against the REAL ~/KEVO
implementation, per the design approved in
claude/kevo-m20-kyc-aml-architecture-design.md.

Scope of this slice: users can self-submit their own KYCFact (starts
"pending"), only an admin can verify/reject it. User.kyc_status is
deliberately NOT auto-linked to KYCFact state in this slice - that
remains a manual admin decision via the pre-existing
PUT /users/{id}/kyc-status endpoint.
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

from models import Base, User as UserModel, Evidence, KYCFact
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
        email=f"m20user{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_evidence(db, user):
    evidence = Evidence(
        user_id=user.id,
        evidence_type="government_id",
        description="Passport scan",
    )
    db.add(evidence)
    db.commit()
    db.refresh(evidence)
    return evidence


def kyc_fact_payload(user_id, **overrides):
    payload = {
        "user_id": user_id,
        "jurisdiction": "United States",
        "fact_type": "identity_verified",
        "fact_value": "true",
    }
    payload.update(overrides)
    return payload


# --- POST /kyc-facts: self-submit ---

def test_self_submit_own_fact_succeeds(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(buyer)
    )
    assert resp.status_code == 200
    body = resp.json()["kyc_fact"]
    assert body["user_id"] == buyer.id
    assert body["fact_type"] == "identity_verified"
    assert body["verification_status"] == "pending"


def test_submit_fact_for_another_user_403(client, db_session):
    buyer = make_user(db_session, "1")
    other = make_user(db_session, "2")
    resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(other.id), headers=auth_headers(buyer)
    )
    assert resp.status_code == 403


def test_admin_can_submit_fact_for_another_user(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(admin)
    )
    assert resp.status_code == 200
    assert resp.json()["kyc_fact"]["user_id"] == buyer.id


def test_submit_fact_unauthenticated_401(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post("/kyc-facts", json=kyc_fact_payload(buyer.id))
    assert resp.status_code == 401


def test_submit_fact_nonexistent_user_404(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(999999), headers=auth_headers(buyer)
    )
    assert resp.status_code == 404


def test_submit_fact_with_evidence_and_as_of_date(client, db_session):
    buyer = make_user(db_session, "1")
    evidence = make_evidence(db_session, buyer)
    resp = client.post(
        "/kyc-facts",
        json=kyc_fact_payload(
            buyer.id,
            fact_type="sanctions_screening_clear",
            fact_value="clear",
            evidence_id=evidence.id,
            as_of_date="2026-09-18",
            source_reference="Manual review by admin",
        ),
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    body = resp.json()["kyc_fact"]
    assert body["evidence_id"] == evidence.id
    assert body["as_of_date"] == "2026-09-18"
    assert body["source_reference"] == "Manual review by admin"


# --- PUT /kyc-facts/{id}/verify: admin-only ---

def test_admin_verify_succeeds(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    create_resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(buyer)
    )
    fact_id = create_resp.json()["kyc_fact"]["id"]

    resp = client.put(
        f"/kyc-facts/{fact_id}/verify",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["kyc_fact"]["verification_status"] == "verified"


def test_admin_reject_succeeds(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    create_resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(buyer)
    )
    fact_id = create_resp.json()["kyc_fact"]["id"]

    resp = client.put(
        f"/kyc-facts/{fact_id}/verify",
        params={"status": "rejected"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["kyc_fact"]["verification_status"] == "rejected"


def test_participant_cannot_verify_403(client, db_session):
    buyer = make_user(db_session, "1")
    participant = make_user(db_session, "2")
    create_resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(buyer)
    )
    fact_id = create_resp.json()["kyc_fact"]["id"]

    resp = client.put(
        f"/kyc-facts/{fact_id}/verify",
        params={"status": "verified"},
        headers=auth_headers(participant),
    )
    assert resp.status_code == 403


def test_verify_cannot_self_verify_without_admin(client, db_session):
    buyer = make_user(db_session, "1")
    create_resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(buyer)
    )
    fact_id = create_resp.json()["kyc_fact"]["id"]

    resp = client.put(
        f"/kyc-facts/{fact_id}/verify",
        params={"status": "verified"},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 403


def test_verify_unauthenticated_401(client, db_session):
    buyer = make_user(db_session, "1")
    create_resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(buyer)
    )
    fact_id = create_resp.json()["kyc_fact"]["id"]

    resp = client.put(f"/kyc-facts/{fact_id}/verify", params={"status": "verified"})
    assert resp.status_code == 401


def test_verify_invalid_status_400(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    create_resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(buyer)
    )
    fact_id = create_resp.json()["kyc_fact"]["id"]

    resp = client.put(
        f"/kyc-facts/{fact_id}/verify",
        params={"status": "not_a_real_status"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400


def test_verify_nonexistent_fact_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put(
        "/kyc-facts/999999/verify",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 404


def test_user_kyc_status_not_auto_linked(client, db_session):
    """Confirms the deliberate design choice: verifying a KYCFact does NOT
    change User.kyc_status. That stays a separate, manual admin action via
    the pre-existing PUT /users/{id}/kyc-status endpoint."""
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    create_resp = client.post(
        "/kyc-facts", json=kyc_fact_payload(buyer.id), headers=auth_headers(buyer)
    )
    fact_id = create_resp.json()["kyc_fact"]["id"]

    client.put(
        f"/kyc-facts/{fact_id}/verify",
        params={"status": "verified"},
        headers=auth_headers(admin),
    )

    db_session.refresh(buyer)
    assert buyer.kyc_status == "not_started"
