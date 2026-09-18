"""
Tests for M13 (Compliance Engine, single-engine remediation, 2026-09-09):
  - _resolve_compliance_fact() reusing existing data (OwnershipRecord /
    InvestorEligibility verification status, and the same Listing/User
    columns M14 already reads) before treating a fact as unresolved
  - assess_compliance()'s tier/precedence structure: blocked (Tier 0 hard
    gates, or a rule's decision_if_unmet="blocked"), needs_evidence
    (Tier 1 missing jurisdiction, or an unresolved rule fact), review
    (Tier 2 no seeded rules for the combination, or a rule requiring
    judgment), eligible_pending_review
  - find_applicable_rules() scoping, unchanged under the new schema
  - find_matches() now surfaces the real four-state match_status instead
    of the old three-state mapping that could never actually reach
    "eligible" (dead branch found in the 2026-09-09 M13 audit)
  - /compliance-rules/matches/{buyer_id}/{listing_id} now backed by the
    same assess_compliance() engine as find_matches() - one engine, not
    two disconnected ones

IMPORTANT: every ComplianceRule created below uses a rule_code prefixed
TEST- and a source_reference explicitly marked as a test fixture. None of
this is real regulatory content. Per the M13 architecture review
(2026-09-09), real compliance rules are only seeded after a dedicated
jurisdiction-by-jurisdiction regulatory research pass with cited sources -
the same discipline seed_transferability_rules.py already applied for M14.

Runs against an isolated in-memory SQLite database, same pattern as
test_app.py / test_m14.py - does not touch the real Postgres config.
"""

import os

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base,
    User as UserModel,
    Listing as ListingModel,
    OwnershipRecord,
    InvestorEligibility,
    ComplianceRule,
)
from app import app, get_db, assess_compliance, _resolve_compliance_fact, find_applicable_rules, _check_investor_classification, hash_password, create_access_token

TEST_SOURCE = "TEST FIXTURE - not real regulatory content, M13 engine test only"


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
    auth_user = UserModel(
        name="Auth User",
        email=f"authuser{id(object())}@example.com",
        role="seller",
        account_type="admin",
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_buyer(db, jurisdiction="United States", kyc_status="verified"):
    user = UserModel(
        name="Buyer",
        email="buyer@example.com",
        role="buyer",
        kyc_status=kyc_status,
        jurisdiction=jurisdiction,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_seller(db):
    user = UserModel(
        name="Seller",
        email="seller@example.com",
        role="seller",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller_id, jurisdiction="United States", asset_type="common_stock",
                  is_transferable=True, issuer_reporting_status=None,
                  issuer_current_information_available=None):
    listing = ListingModel(
        seller_id=seller_id,
        company="Acme Inc",
        asset_type=asset_type,
        quantity=1000,
        asking_price=80.0,
        is_transferable=is_transferable,
        issuer_jurisdiction=jurisdiction,
        issuer_reporting_status=issuer_reporting_status,
        issuer_current_information_available=issuer_current_information_available,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_ownership(db, listing_id, seller_id, verification_status="verified", acquisition_date=None):
    record = OwnershipRecord(
        seller_id=seller_id,
        listing_id=listing_id,
        company="Acme Inc",
        asset_type="common_stock",
        quantity=1000,
        acquisition_date=acquisition_date,
        verification_status=verification_status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def make_eligibility(db, buyer_id, classification="accredited_investor", status="verified", effective_date=None):
    record = InvestorEligibility(
        buyer_id=buyer_id,
        investor_type="individual",
        classification=classification,
        status=status,
        effective_date=effective_date,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def make_rule(db, rule_code, fact_type, requirement, decision_if_unmet,
              buyer_jurisdiction="United States", issuer_jurisdiction="United States",
              asset_type="common_stock", investor_classification=None, active=True,
              fact_validity_days=None):
    rule = ComplianceRule(
        buyer_jurisdiction=buyer_jurisdiction,
        issuer_jurisdiction=issuer_jurisdiction,
        asset_type=asset_type,
        investor_classification=investor_classification,
        rule_code=rule_code,
        description="Test fixture rule for M13 engine tests.",
        fact_type=fact_type,
        requirement=requirement,
        decision_if_unmet=decision_if_unmet,
        requires_human_review=True,
        active=active,
        fact_validity_days=fact_validity_days,
        source_reference=TEST_SOURCE,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


# ---------------------------------------------------------------------------
# _resolve_compliance_fact
# ---------------------------------------------------------------------------

def test_resolve_ownership_verified_true_when_verified_record_exists(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_ownership(db_session, listing.id, seller.id, verification_status="verified")

    value, evidenced, as_of_date = _resolve_compliance_fact("ownership_verified", buyer, listing, db_session)
    assert evidenced is True
    assert value == "verified"


def test_resolve_ownership_verified_false_when_unverified(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_ownership(db_session, listing.id, seller.id, verification_status="pending")

    value, evidenced, as_of_date = _resolve_compliance_fact("ownership_verified", buyer, listing, db_session)
    assert evidenced is False
    assert value is None


def test_resolve_eligibility_verified_true_when_verified_record_exists(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_eligibility(db_session, buyer.id, status="verified")

    value, evidenced, as_of_date = _resolve_compliance_fact("eligibility_verified", buyer, listing, db_session)
    assert evidenced is True
    assert value == "verified"


def test_resolve_eligibility_verified_false_when_missing(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)

    value, evidenced, as_of_date = _resolve_compliance_fact("eligibility_verified", buyer, listing, db_session)
    assert evidenced is False
    assert value is None


def test_resolve_reuses_listing_issuer_reporting_status(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, issuer_reporting_status="Reporting")

    value, evidenced, as_of_date = _resolve_compliance_fact("issuer_reporting_status", buyer, listing, db_session)
    assert evidenced is True
    assert value == "reporting"


# ---------------------------------------------------------------------------
# assess_compliance - Tier 0 hard gates
# ---------------------------------------------------------------------------

def test_blocked_when_kyc_not_verified(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session, kyc_status="pending")
    listing = make_listing(db_session, seller.id)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "blocked"
    assert "KYC" in result["explanation"]


def test_blocked_when_asset_not_transferable(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, is_transferable=False)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "blocked"
    assert "transferable" in result["explanation"]


# ---------------------------------------------------------------------------
# assess_compliance - Tier 1 jurisdiction presence
# ---------------------------------------------------------------------------

def test_needs_evidence_when_buyer_jurisdiction_missing(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session, jurisdiction=None)
    listing = make_listing(db_session, seller.id)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "needs_evidence"
    assert "Buyer jurisdiction" in result["explanation"]


def test_needs_evidence_when_issuer_jurisdiction_missing(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, jurisdiction=None)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "needs_evidence"
    assert "Issuer jurisdiction" in result["explanation"]


# ---------------------------------------------------------------------------
# assess_compliance - Tier 2 rule coverage
# ---------------------------------------------------------------------------

def test_review_when_no_rules_seeded_for_combination(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session, jurisdiction="Nigeria")
    listing = make_listing(db_session, seller.id, jurisdiction="Nigeria")

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "review"
    assert result["applicable_rule_codes"] == []


# ---------------------------------------------------------------------------
# assess_compliance - Tier 3 per-rule fact evaluation
# ---------------------------------------------------------------------------

def test_needs_evidence_when_rule_fact_unresolved(db_session):
    make_rule(db_session, "TEST-M13-001", "eligibility_verified", "verified", "blocked")

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    # No InvestorEligibility record created at all.

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "needs_evidence"
    assert "TEST-M13-001" in result["explanation"]


def test_unverified_eligibility_counts_as_needs_evidence_not_unmet(db_session):
    make_rule(db_session, "TEST-M13-002", "eligibility_verified", "verified", "blocked")

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_eligibility(db_session, buyer.id, status="pending")  # recorded, not verified

    result = assess_compliance(buyer, listing, db_session)
    # An unverified eligibility record is "not evidenced" - same as an
    # unverified TransferabilityFact in M14 - not a met OR unmet fact.
    assert result["status"] == "needs_evidence"
    assert "TEST-M13-002" in result["explanation"]


def test_blocked_when_rule_requirement_actually_unmet(db_session):
    make_rule(db_session, "TEST-M13-003", "issuer_reporting_status", "reporting", "blocked")

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, issuer_reporting_status="non_reporting")

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "blocked"
    assert "TEST-M13-003" in result["explanation"]


def test_review_when_rule_requirement_unmet_and_decision_review(db_session):
    make_rule(db_session, "TEST-M13-004", "issuer_reporting_status", "reporting", "review")

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, issuer_reporting_status="non_reporting")

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "review"
    assert "TEST-M13-004" in result["explanation"]


def test_eligible_pending_review_when_all_rules_met(db_session):
    make_rule(db_session, "TEST-M13-005", "issuer_reporting_status", "reporting", "blocked")
    make_rule(db_session, "TEST-M13-006", "eligibility_verified", "verified", "blocked")

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, issuer_reporting_status="reporting")
    make_eligibility(db_session, buyer.id, status="verified")

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "eligible_pending_review"
    assert "TEST-M13-005" in result["applicable_rule_codes"]
    assert "TEST-M13-006" in result["applicable_rule_codes"]


def test_inactive_rule_is_excluded(db_session):
    make_rule(db_session, "TEST-M13-007", "eligibility_verified", "verified", "blocked", active=False)

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "review"
    assert "TEST-M13-007" not in result["applicable_rule_codes"]


def test_blocked_takes_precedence_over_needs_evidence(db_session):
    # One rule is unmet-and-blocked, another rule's fact is entirely
    # missing - blocked must win, same precedence assess_transferability
    # already proves for M14.
    make_rule(db_session, "TEST-M13-008", "issuer_reporting_status", "reporting", "blocked")
    make_rule(db_session, "TEST-M13-009", "eligibility_verified", "verified", "blocked")

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, issuer_reporting_status="non_reporting")
    # No eligibility record at all -> TEST-M13-009 would be needs_evidence.

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "blocked"
    assert "TEST-M13-008" in result["explanation"]


# ---------------------------------------------------------------------------
# find_applicable_rules - scoping unchanged under the new schema
# ---------------------------------------------------------------------------

def test_find_applicable_rules_no_longer_filters_by_investor_classification(db_session):
    # Gap 2 fix (2026-09-09): investor_classification is no longer a
    # scoping filter in find_applicable_rules() - a rule that names a
    # required classification is always returned once jurisdiction/
    # asset_type match, regardless of what the buyer is actually
    # classified as. The old behavior silently dropped this rule for a
    # buyer with the wrong (or no) classification, so the engine never
    # said anything was wrong. assess_compliance() now does that check
    # explicitly via _check_investor_classification() - see the tests
    # below.
    make_rule(
        db_session, "TEST-M13-010", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited_investor",
    )

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_eligibility(db_session, buyer.id, classification="retail_investor", status="verified")

    applicable = find_applicable_rules(buyer, listing, db_session)
    assert len(applicable) == 1
    assert applicable[0].rule_code == "TEST-M13-010"


# ---------------------------------------------------------------------------
# find_matches() - full four-state status, "eligible" is actually reachable
# ---------------------------------------------------------------------------

def test_find_matches_reaches_eligible_pending_review(client, db_session):
    make_rule(db_session, "TEST-M13-011", "eligibility_verified", "verified", "blocked")

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_eligibility(db_session, buyer.id, status="verified")

    interest_response = client.post("/buyer-interests", json={
        "buyer_id": buyer.id,
        "company": "Acme Inc",
        "asset_type": "common_stock",
        "desired_quantity": 500,
        "maximum_price": 100.0,
    }, headers=auth_headers(buyer))
    assert interest_response.status_code == 200
    interest_id = interest_response.json()["buyer_interest"]["id"]

    response = client.get(f"/buyer-interests/{interest_id}/matches", headers=auth_headers(buyer))
    assert response.status_code == 200
    matches = response.json()["matches"]
    assert len(matches) == 1
    assert matches[0]["match_status"] == "eligible_pending_review"
    assert matches[0]["compliance_status"] == "eligible_pending_review"


def test_find_matches_blocked_when_kyc_not_verified(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session, kyc_status="pending")
    listing = make_listing(db_session, seller.id)

    interest_response = client.post("/buyer-interests", json={
        "buyer_id": buyer.id,
        "company": "Acme Inc",
        "asset_type": "common_stock",
        "desired_quantity": 500,
        "maximum_price": 100.0,
    }, headers=auth_headers(buyer))
    interest_id = interest_response.json()["buyer_interest"]["id"]

    response = client.get(f"/buyer-interests/{interest_id}/matches", headers=auth_headers(buyer))
    matches = response.json()["matches"]
    assert matches[0]["match_status"] == "blocked"


# ---------------------------------------------------------------------------
# /compliance-rules/matches/{buyer_id}/{listing_id} - now backed by the
# same assess_compliance() engine, not a separate implementation
# ---------------------------------------------------------------------------

def test_compliance_rules_matches_endpoint_uses_shared_engine(client, db_session):
    make_rule(db_session, "TEST-M13-012", "eligibility_verified", "verified", "blocked")

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_eligibility(db_session, buyer.id, status="verified")

    response = client.get(f"/compliance-rules/matches/{buyer.id}/{listing.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "eligible_pending_review"
    assert "TEST-M13-012" in body["applicable_rule_codes"]


def test_compliance_rules_matches_endpoint_404_for_unknown_buyer(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id)

    response = client.get(f"/compliance-rules/matches/999999/{listing.id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# ComplianceRule CRUD endpoints - new schema fields
# ---------------------------------------------------------------------------

def test_create_compliance_rule_endpoint_new_schema(client, db_session):
    response = client.post("/compliance-rules", json={
        "rule_code": "TEST-M13-013",
        "description": "Test fixture rule.",
        "fact_type": "eligibility_verified",
        "requirement": "verified",
        "decision_if_unmet": "blocked",
        "source_reference": TEST_SOURCE,
    })
    assert response.status_code == 200
    body = response.json()["compliance_rule"]
    assert body["fact_type"] == "eligibility_verified"
    assert body["requirement"] == "verified"
    assert body["decision_if_unmet"] == "blocked"


def test_create_compliance_rule_endpoint_rejects_duplicate_code(client, db_session):
    payload = {
        "rule_code": "TEST-M13-014",
        "description": "Test fixture rule.",
        "fact_type": "eligibility_verified",
        "requirement": "verified",
        "decision_if_unmet": "blocked",
        "source_reference": TEST_SOURCE,
    }
    first = client.post("/compliance-rules", json=payload)
    assert first.status_code == 200

    second = client.post("/compliance-rules", json=payload)
    assert second.status_code == 400


def test_get_compliance_rules_endpoint(client, db_session):
    make_rule(db_session, "TEST-M13-015", "eligibility_verified", "verified", "blocked")

    response = client.get("/compliance-rules")
    assert response.status_code == 200
    codes = [r["rule_code"] for r in response.json()]
    assert "TEST-M13-015" in codes



# ---------------------------------------------------------------------------
# _check_investor_classification - missing vs. wrong vs. not applicable
# (Gap 2: classification mismatch design, 2026-09-09)
# ---------------------------------------------------------------------------

def test_classification_check_not_applicable_when_rule_has_no_classification(db_session):
    rule = make_rule(db_session, "TEST-M13-016", "eligibility_verified", "verified", "blocked")
    buyer = make_buyer(db_session)

    outcome = _check_investor_classification(rule, buyer, db_session)
    assert outcome == "not_applicable"


def test_classification_check_missing_evidence_when_no_eligibility_record(db_session):
    rule = make_rule(
        db_session, "TEST-M13-017", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited",
    )
    buyer = make_buyer(db_session)

    outcome = _check_investor_classification(rule, buyer, db_session)
    assert outcome == "missing_evidence"


def test_classification_check_missing_evidence_when_eligibility_unverified(db_session):
    rule = make_rule(
        db_session, "TEST-M13-018", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited",
    )
    buyer = make_buyer(db_session)
    make_eligibility(db_session, buyer.id, classification="accredited", status="pending")

    outcome = _check_investor_classification(rule, buyer, db_session)
    assert outcome == "missing_evidence"


def test_classification_check_met_when_classification_matches(db_session):
    rule = make_rule(
        db_session, "TEST-M13-019", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited",
    )
    buyer = make_buyer(db_session)
    make_eligibility(db_session, buyer.id, classification="Accredited", status="verified")

    outcome = _check_investor_classification(rule, buyer, db_session)
    assert outcome == "met"


def test_classification_check_blocked_when_classification_mismatches_and_decision_blocked(db_session):
    rule = make_rule(
        db_session, "TEST-M13-020", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited",
    )
    buyer = make_buyer(db_session)
    make_eligibility(db_session, buyer.id, classification="retail_investor", status="verified")

    outcome = _check_investor_classification(rule, buyer, db_session)
    assert outcome == "blocked"


def test_classification_check_review_when_classification_mismatches_and_decision_review(db_session):
    rule = make_rule(
        db_session, "TEST-M13-021", "eligibility_verified", "verified", "review",
        investor_classification="accredited",
    )
    buyer = make_buyer(db_session)
    make_eligibility(db_session, buyer.id, classification="retail_investor", status="verified")

    outcome = _check_investor_classification(rule, buyer, db_session)
    assert outcome == "review"


# ---------------------------------------------------------------------------
# assess_compliance - classification mismatch surfaced end-to-end
# ---------------------------------------------------------------------------

def test_assess_compliance_blocked_when_buyer_has_wrong_classification(db_session):
    make_rule(
        db_session, "TEST-M13-022", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited",
    )

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_eligibility(db_session, buyer.id, classification="retail_investor", status="verified")

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "blocked"
    assert "TEST-M13-022" in result["explanation"]
    assert "does not match required" in result["explanation"]


def test_assess_compliance_needs_evidence_when_buyer_not_yet_classified(db_session):
    make_rule(
        db_session, "TEST-M13-023", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited",
    )

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "needs_evidence"
    assert "TEST-M13-023" in result["explanation"]


def test_assess_compliance_eligible_when_classification_and_primary_fact_both_met(db_session):
    make_rule(
        db_session, "TEST-M13-024", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited",
    )

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_eligibility(db_session, buyer.id, classification="accredited", status="verified")

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "eligible_pending_review"
    assert "TEST-M13-024" in result["applicable_rule_codes"]


# ---------------------------------------------------------------------------
# fact_validity_days - expiring facts
# (Gap 1: expiring compliance facts design, 2026-09-09)
# ---------------------------------------------------------------------------

def test_resolve_eligibility_verified_returns_effective_date_as_third_value(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    certified_on = date(2026, 1, 10)
    make_eligibility(db_session, buyer.id, status="verified", effective_date=certified_on)

    value, evidenced, as_of_date = _resolve_compliance_fact("eligibility_verified", buyer, listing, db_session)
    assert evidenced is True
    assert as_of_date == certified_on


def test_assess_compliance_needs_evidence_when_classification_certification_expired(db_session):
    make_rule(
        db_session, "TEST-M13-025", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited", fact_validity_days=180,
    )

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    stale_date = date.today() - timedelta(days=200)
    make_eligibility(db_session, buyer.id, classification="accredited", status="verified", effective_date=stale_date)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "needs_evidence"
    assert "TEST-M13-025" in result["explanation"]


def test_assess_compliance_eligible_when_classification_certification_still_current(db_session):
    make_rule(
        db_session, "TEST-M13-026", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited", fact_validity_days=180,
    )

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    fresh_date = date.today() - timedelta(days=30)
    make_eligibility(db_session, buyer.id, classification="accredited", status="verified", effective_date=fresh_date)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "eligible_pending_review"
    assert "TEST-M13-026" in result["applicable_rule_codes"]


def test_assess_compliance_needs_evidence_when_validity_required_but_no_effective_date(db_session):
    make_rule(
        db_session, "TEST-M13-027", "eligibility_verified", "verified", "blocked",
        investor_classification="accredited", fact_validity_days=180,
    )

    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_eligibility(db_session, buyer.id, classification="accredited", status="verified", effective_date=None)

    result = assess_compliance(buyer, listing, db_session)
    assert result["status"] == "needs_evidence"
    assert "TEST-M13-027" in result["explanation"]
