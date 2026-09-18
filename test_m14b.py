"""
Tests for the M14B audit fix (2026-09-11): GET /offering-exemptions/{offering_id}
Written against the REAL ~/KEVO implementation.

Design: evaluate_offering_exemptions(offering, db) runs six real, independent
exemption-pathway checks (506(b), 506(c), Reg CF, Reg A+ Tier 1, Reg A+ Tier 2,
Reg S) against real OfferingFact/OfferingExemptionRule data, each returning its
own status (eligible/ineligible/needs_evidence/conflict) with real reasons.
No invented weighting, no single combined verdict across pathways.

The audit found GET /offering-exemptions/{offering_id} was writing a full set
of OfferingExemptionAssessment rows to the database on every call (the same
write-on-GET bug found and fixed in M14's transferability endpoint, though no
downstream feature depended on the polluted table this time). Fixed to a pure
read - this file covers both the fix (no persistence) and first-time real
coverage of the six exemption functions themselves.
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
    Base, User, Offering, OfferingFact, OfferingExemptionRule, OfferingExemptionAssessment,
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
    auth_user = User(
        name="Auth Test User",
        email="__test_auth_user__@kevo.local",
        role="buyer",
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def make_offering(db_session, jurisdiction="United States", general_solicitation_used=False,
                   target_raise_amount=None, status="open"):
    offering = Offering(
        issuer_name="Test Issuer LLC", jurisdiction=jurisdiction,
        general_solicitation_used=general_solicitation_used,
        target_raise_amount=target_raise_amount, status=status
    )
    db_session.add(offering)
    db_session.commit()
    return offering


def add_fact(db_session, offering_id, fact_type, fact_value, verification_status="verified"):
    fact = OfferingFact(
        offering_id=offering_id, fact_type=fact_type, fact_value=fact_value,
        verification_status=verification_status
    )
    db_session.add(fact)
    db_session.commit()
    return fact


def add_rule(db_session, exemption_code, jurisdiction, requirement_type, requirement_value):
    rule = OfferingExemptionRule(
        exemption_code=exemption_code, jurisdiction=jurisdiction,
        requirement_type=requirement_type, requirement_value=requirement_value,
        source_reference="test source"
    )
    db_session.add(rule)
    db_session.commit()
    return rule


def clear_facts_for_506b(db_session, offering_id):
    add_fact(db_session, offering_id, "bad_actor_disqualification_clear", "true")
    add_fact(db_session, offering_id, "non_accredited_investor_count", "0")


def test_404_for_unknown_offering(client):
    response = client.get("/offering-exemptions/999999")
    assert response.status_code == 404


def test_returns_six_assessments(client, db_session):
    offering = make_offering(db_session)
    response = client.get("/offering-exemptions/" + str(offering.id))
    assert response.status_code == 200
    body = response.json()
    codes = [a["exemption_code"] for a in body["assessments"]]
    assert sorted(codes) == sorted([
        "US-REG-D-506B", "US-REG-D-506C", "US-REG-CF",
        "US-REG-A-TIER1", "US-REG-A-TIER2", "US-REG-S"
    ])


def test_endpoint_does_not_persist_anything(client, db_session):
    offering = make_offering(db_session)
    count_before = db_session.query(OfferingExemptionAssessment).count()

    client.get("/offering-exemptions/" + str(offering.id))
    client.get("/offering-exemptions/" + str(offering.id))

    assert db_session.query(OfferingExemptionAssessment).count() == count_before


def test_506b_ineligible_when_general_solicitation_used(client, db_session):
    offering = make_offering(db_session, general_solicitation_used=True)
    clear_facts_for_506b(db_session, offering.id)
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-D-506B")
    assert a["status"] == "ineligible"
    assert "general solicitation" in "; ".join(a["reasons"])


def test_506b_eligible_when_no_general_solicitation_and_facts_clear(client, db_session):
    offering = make_offering(db_session, general_solicitation_used=False)
    clear_facts_for_506b(db_session, offering.id)
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-D-506B")
    assert a["status"] == "eligible"


def test_506b_needs_evidence_when_bad_actor_fact_missing(client, db_session):
    offering = make_offering(db_session, general_solicitation_used=False)
    add_fact(db_session, offering.id, "non_accredited_investor_count", "0")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-D-506B")
    assert a["status"] == "needs_evidence"


def test_506c_eligible_when_all_facts_true(client, db_session):
    offering = make_offering(db_session)
    add_fact(db_session, offering.id, "bad_actor_disqualification_clear", "true")
    add_fact(db_session, offering.id, "all_investors_accredited", "true")
    add_fact(db_session, offering.id, "accreditation_verification_documented", "true")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-D-506C")
    assert a["status"] == "eligible"


def test_506c_ineligible_when_not_all_investors_accredited(client, db_session):
    offering = make_offering(db_session)
    add_fact(db_session, offering.id, "bad_actor_disqualification_clear", "true")
    add_fact(db_session, offering.id, "all_investors_accredited", "false")
    add_fact(db_session, offering.id, "accreditation_verification_documented", "true")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-D-506C")
    assert a["status"] == "ineligible"


def test_regcf_ineligible_when_raise_exceeds_cap(client, db_session):
    offering = make_offering(db_session, target_raise_amount=6000000)
    add_rule(db_session, "US-REG-CF", "United States", "raise_cap_12mo", "5000000")
    add_fact(db_session, offering.id, "bad_actor_disqualification_clear", "true")
    add_fact(db_session, offering.id, "funding_portal_or_broker_dealer_used", "true")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-CF")
    assert a["status"] == "ineligible"
    assert "exceeds" in "; ".join(a["reasons"])


def test_regcf_needs_evidence_when_no_cap_rule_for_jurisdiction(client, db_session):
    offering = make_offering(db_session, target_raise_amount=1000000)
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-CF")
    assert a["status"] == "needs_evidence"


def test_reg_a_tier1_eligible_within_cap_and_facts_clear(client, db_session):
    offering = make_offering(db_session, target_raise_amount=5000000)
    add_rule(db_session, "US-REG-A-TIER1", "United States", "raise_cap_12mo", "20000000")
    add_fact(db_session, offering.id, "bad_actor_disqualification_clear", "true")
    add_fact(db_session, offering.id, "sec_qualification_obtained", "true")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-A-TIER1")
    assert a["status"] == "eligible"


def test_reg_a_tier2_ineligible_when_non_accredited_limits_not_documented(client, db_session):
    offering = make_offering(db_session, target_raise_amount=5000000)
    add_rule(db_session, "US-REG-A-TIER2", "United States", "raise_cap_12mo", "75000000")
    add_fact(db_session, offering.id, "bad_actor_disqualification_clear", "true")
    add_fact(db_session, offering.id, "sec_qualification_obtained", "true")
    add_fact(db_session, offering.id, "tier2_non_accredited_limits_compliance_documented", "false")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-A-TIER2")
    assert a["status"] == "ineligible"


def test_reg_s_needs_evidence_when_jurisdiction_not_united_states(client, db_session):
    offering = make_offering(db_session, jurisdiction="Canada")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-S")
    assert a["status"] == "needs_evidence"
    assert "not yet modeled" in "; ".join(a["reasons"])


def test_reg_s_eligible_when_all_facts_true_and_us_jurisdiction(client, db_session):
    offering = make_offering(db_session, jurisdiction="United States")
    add_fact(db_session, offering.id, "offshore_transaction_confirmed", "true")
    add_fact(db_session, offering.id, "no_directed_selling_efforts_in_us", "true")
    add_fact(db_session, offering.id, "reg_s_purchaser_certification_documented", "true")
    add_fact(db_session, offering.id, "reg_s_transfer_legend_applied", "true")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-S")
    assert a["status"] == "eligible"


def test_conflict_status_when_facts_have_conflicting_verified_values(client, db_session):
    offering = make_offering(db_session)
    add_fact(db_session, offering.id, "bad_actor_disqualification_clear", "true")
    add_fact(db_session, offering.id, "all_investors_accredited", "true")
    add_fact(db_session, offering.id, "accreditation_verification_documented", "true")
    add_fact(db_session, offering.id, "accreditation_verification_documented", "false")
    response = client.get("/offering-exemptions/" + str(offering.id))
    body = response.json()
    a = next(x for x in body["assessments"] if x["exemption_code"] == "US-REG-D-506C")
    assert a["status"] == "conflict"
