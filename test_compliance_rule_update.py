"""
Tests for the new PUT /compliance-rules/{rule_id} endpoint, 2026-09-21 -
closes the first item of the full gap-closure pass (Batch B / group 1):
unlocks M27's future rule-change impact alerts, which have nothing to
trigger off until ComplianceRule can actually be updated. Admin-only,
partial update (only fields explicitly sent are changed), mirroring the
verify-endpoint pattern used across KEVO (KYCFact, InvestorEligibility).

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

from models import Base, User as UserModel, ComplianceRule
from app import app, get_db, hash_password, create_access_token

TEST_SOURCE = "TEST FIXTURE - not real regulatory content, update-endpoint test only"


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
        email=f"compliancerule{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_rule(db, rule_code, active=True):
    rule = ComplianceRule(
        buyer_jurisdiction="United States",
        issuer_jurisdiction="United States",
        asset_type="common_stock",
        investor_classification=None,
        rule_code=rule_code,
        description="Original description.",
        fact_type="kyc_status",
        requirement="Buyer KYC must be verified.",
        decision_if_unmet="blocked",
        requires_human_review=True,
        active=active,
        source_reference=TEST_SOURCE,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def test_admin_can_update_rule(client, db_session):
    admin = make_user(db_session, "admin1", account_type="admin")
    rule = make_rule(db_session, "TEST-RULE-001")

    resp = client.put(
        f"/compliance-rules/{rule.id}",
        json={"description": "Updated description.", "active": False},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    body = resp.json()["compliance_rule"]
    assert body["description"] == "Updated description."
    assert body["active"] is False
    # Untouched fields stay the same
    assert body["rule_code"] == "TEST-RULE-001"
    assert body["requirement"] == "Buyer KYC must be verified."


def test_partial_update_leaves_other_fields_untouched(client, db_session):
    admin = make_user(db_session, "admin2", account_type="admin")
    rule = make_rule(db_session, "TEST-RULE-002")

    resp = client.put(
        f"/compliance-rules/{rule.id}",
        json={"fact_validity_days": 180},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    body = resp.json()["compliance_rule"]
    assert body["fact_validity_days"] == 180
    assert body["description"] == "Original description."
    assert body["active"] is True


def test_participant_cannot_update_rule_403(client, db_session):
    participant = make_user(db_session, "p1", account_type="participant")
    rule = make_rule(db_session, "TEST-RULE-003")

    resp = client.put(
        f"/compliance-rules/{rule.id}",
        json={"description": "Hijacked."},
        headers=auth_headers(participant),
    )
    assert resp.status_code == 403


def test_update_nonexistent_rule_404(client, db_session):
    admin = make_user(db_session, "admin3", account_type="admin")

    resp = client.put(
        "/compliance-rules/999999",
        json={"description": "Doesn't matter."},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 404


def test_update_unauthenticated_401(client, db_session):
    rule = make_rule(db_session, "TEST-RULE-004")

    resp = client.put(
        f"/compliance-rules/{rule.id}",
        json={"description": "Doesn't matter."},
    )
    assert resp.status_code == 401


def test_update_rule_code_conflict_400(client, db_session):
    admin = make_user(db_session, "admin4", account_type="admin")
    rule_a = make_rule(db_session, "TEST-RULE-005")
    rule_b = make_rule(db_session, "TEST-RULE-006")

    resp = client.put(
        f"/compliance-rules/{rule_b.id}",
        json={"rule_code": "TEST-RULE-005"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400


def test_update_rule_code_to_same_value_allowed(client, db_session):
    admin = make_user(db_session, "admin5", account_type="admin")
    rule = make_rule(db_session, "TEST-RULE-007")

    resp = client.put(
        f"/compliance-rules/{rule.id}",
        json={"rule_code": "TEST-RULE-007", "description": "Still fine."},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["compliance_rule"]["rule_code"] == "TEST-RULE-007"


def test_update_response_includes_full_record(client, db_session):
    admin = make_user(db_session, "admin6", account_type="admin")
    rule = make_rule(db_session, "TEST-RULE-008")

    resp = client.put(
        f"/compliance-rules/{rule.id}",
        json={"description": "Full record check."},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    body = resp.json()["compliance_rule"]
    for field in [
        "id", "buyer_jurisdiction", "issuer_jurisdiction", "asset_type",
        "investor_classification", "rule_code", "description", "fact_type",
        "fact_validity_days", "requirement", "decision_if_unmet",
        "requires_human_review", "active", "source_reference",
    ]:
        assert field in body
