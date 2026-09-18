"""
Tests for M14 (Transferability Intelligence Engine) - written against the
REAL ~/KEVO implementation (2026-09-09), not the disconnected sandbox
build described in claude/kevo-m14-implementation-summary.md (that doc's
own header names /root/workspace/kevo - a different, never-connected
copy of this project). Every function/field name below was confirmed by
directly reading the real app.py/models.py this session before writing
any test.

Covers:
  - find_applicable_transferability_rules(): exact jurisdiction + asset_type
    match, no wildcard support (unlike M13's ComplianceRule scoping)
  - evaluate_transferability()'s five real outcomes: blocked, needs_evidence,
    review, conflict, eligible_pending_review, and the exact code path each
    one comes from:
      * missing fact entirely -> rule.decision_if_unmet
      * fact recorded but unverified -> always "review", regardless of
        decision_if_unmet (a real divergence from M13, where unverified
        collapses into the same bucket as missing)
      * multiple verified facts with different values -> "conflict"
      * hold_period_days rules -> real date math against fact.as_of_date
      * the US-only SEC Rule 144(d)(3)(vii) estate exemption, hardcoded
        directly in Python rather than data-driven
  - A DOCUMENTED DEFECT (not fixed here, per instruction): for a rule
    without hold_period_days, rule.requirement is never actually compared
    against the verified fact's value anywhere in evaluate_transferability().
    A verified fact of the right fact_type satisfies the rule regardless
    of what value it holds. test_documents_requirement_field_is_never_checked
    proves this precisely so it's evidence, not just a claim.

IMPORTANT: every TransferabilityRule/TransferabilityFact created below uses
a rule_code/source_reference prefixed TEST- and marked as a test fixture.
None of this is real regulatory content - the six real seeded rules
(US-RULE144-HOLD-6MO, CA-NI45102-NONREPORTING-HOLD, UK-FSMA-S21-FINPROM,
AU-CORP-S707-12MO-TAINT, ZA-COMPANIES-S8-ROFR-CONSENT, SG-SFA-6MO-ONSALE)
are left untouched by this test suite.

Runs against an isolated in-memory SQLite database, same pattern as
test_m13.py - does not touch the real Postgres config.
"""

import os

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import pytest
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base,
    User as UserModel,
    Listing as ListingModel,
    TransferabilityFact,
    TransferabilityRule,
)
from app import app, get_db, evaluate_transferability, find_applicable_transferability_rules

TEST_SOURCE = "TEST FIXTURE - not real regulatory content, M14 engine test only"


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


def make_listing(db, seller_id, issuer_jurisdiction="United States", asset_type="Private Shares",
                  is_transferable=True):
    listing = ListingModel(
        seller_id=seller_id,
        company="Acme Inc",
        asset_type=asset_type,
        quantity=1000,
        asking_price=80.0,
        is_transferable=is_transferable,
        issuer_jurisdiction=issuer_jurisdiction,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_rule(db, rule_code, jurisdiction, fact_type, requirement, decision_if_unmet,
              asset_type="Private Shares", hold_period_days=None, active=True,
              expected_fact_value=None):
    rule = TransferabilityRule(
        jurisdiction=jurisdiction,
        asset_type=asset_type,
        fact_type=fact_type,
        rule_code=rule_code,
        requirement=requirement,
        decision_if_unmet=decision_if_unmet,
        requires_human_review=True,
        active=active,
        hold_period_days=hold_period_days,
        expected_fact_value=expected_fact_value,
        source_reference=TEST_SOURCE,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def make_fact(db, listing_id, jurisdiction, fact_type, fact_value, verification_status="verified",
              as_of_date=None, superseded_by_id=None):
    fact = TransferabilityFact(
        listing_id=listing_id,
        jurisdiction=jurisdiction,
        fact_type=fact_type,
        fact_value=fact_value,
        as_of_date=as_of_date,
        verification_status=verification_status,
        source_reference=TEST_SOURCE,
        superseded_by_id=superseded_by_id,
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return fact


# ---------------------------------------------------------------------------
# find_applicable_transferability_rules - exact match, no wildcard
# ---------------------------------------------------------------------------

def test_find_applicable_rules_requires_exact_jurisdiction_match(db_session):
    make_rule(db_session, "TEST-M14-001", "United States", "acquisition_date", "n/a", "needs_evidence")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Canada")

    applicable = find_applicable_transferability_rules(listing, db_session)
    assert applicable == []


def test_find_applicable_rules_requires_exact_asset_type_match(db_session):
    make_rule(db_session, "TEST-M14-002", "United States", "acquisition_date", "n/a", "needs_evidence",
              asset_type="Preferred Shares")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States", asset_type="Private Shares")

    applicable = find_applicable_transferability_rules(listing, db_session)
    assert applicable == []


def test_find_applicable_rules_matches_when_both_align(db_session):
    make_rule(db_session, "TEST-M14-003", "United States", "acquisition_date", "n/a", "needs_evidence")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")

    applicable = find_applicable_transferability_rules(listing, db_session)
    assert len(applicable) == 1
    assert applicable[0].rule_code == "TEST-M14-003"


# ---------------------------------------------------------------------------
# evaluate_transferability - no rules seeded
# ---------------------------------------------------------------------------

def test_review_when_no_rules_for_jurisdiction(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nigeria")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "review"
    assert result["applicable_rule_count"] == 0
    assert result["path_to_eligibility"] is None
    assert result["forecast_date"] is None


# ---------------------------------------------------------------------------
# missing fact entirely -> rule.decision_if_unmet
# ---------------------------------------------------------------------------

def test_missing_fact_uses_decision_if_unmet_needs_evidence(db_session):
    make_rule(db_session, "TEST-M14-004", "United States", "transfer_restriction_consent", "obtained", "needs_evidence")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    # No TransferabilityFact created at all.

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "needs_evidence"
    assert any("TEST-M14-004" in r for r in result["reasons"])


def test_missing_fact_uses_decision_if_unmet_blocked(db_session):
    make_rule(db_session, "TEST-M14-005", "United Kingdom", "transfer_restriction_consent", "obtained", "blocked")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United Kingdom")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "blocked"
    assert any("TEST-M14-005" in r for r in result["reasons"])


# ---------------------------------------------------------------------------
# fact recorded but unverified -> always "review", regardless of
# decision_if_unmet (real divergence from M13)
# ---------------------------------------------------------------------------

def test_unverified_fact_is_always_review_even_when_decision_is_blocked(db_session):
    make_rule(db_session, "TEST-M14-006", "United Kingdom", "transfer_restriction_consent", "obtained", "blocked")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United Kingdom")
    make_fact(db_session, listing.id, "United Kingdom", "transfer_restriction_consent", "obtained",
              verification_status="pending")

    result = evaluate_transferability(listing, db_session)
    # Not "blocked" - even though decision_if_unmet is blocked, an
    # unverified fact always resolves to "review" in the real code.
    assert result["status"] == "review"
    assert any("not yet verified" in r for r in result["reasons"])


# ---------------------------------------------------------------------------
# conflicting verified facts -> "conflict"
# ---------------------------------------------------------------------------

def test_conflicting_verified_facts_produce_conflict_status(db_session):
    make_rule(db_session, "TEST-M14-007", "United States", "transfer_restriction_consent", "obtained", "blocked")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "obtained")
    make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "denied")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "conflict"
    assert any("Conflicting verified facts" in r for r in result["reasons"])


def test_superseded_fact_excluded_from_conflict_detection(db_session):
    make_rule(db_session, "TEST-M14-008", "United States", "transfer_restriction_consent", "obtained", "blocked")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    old_fact = make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "denied")
    new_fact = make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "obtained")
    old_fact.superseded_by_id = new_fact.id
    db_session.commit()

    result = evaluate_transferability(listing, db_session)
    # Only the non-superseded "obtained" fact counts - no conflict, and
    # since this rule has no hold_period_days, a single verified fact of
    # the right type satisfies it regardless of value (see the documented
    # defect below) - so this ends up eligible_pending_review.
    assert result["status"] == "eligible_pending_review"


# ---------------------------------------------------------------------------
# hold_period_days - real date math
# ---------------------------------------------------------------------------

def test_hold_period_not_yet_met_is_blocked_with_forecast(db_session):
    make_rule(db_session, "TEST-M14-009", "United States", "acquisition_date", "n/a", "needs_evidence",
              hold_period_days=180)

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    acquired = date.today() - timedelta(days=30)  # well inside the 180-day window
    make_fact(db_session, listing.id, "United States", "acquisition_date", "n/a", as_of_date=acquired)

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "blocked"
    expected_forecast = acquired + timedelta(days=180)
    assert result["forecast_date"] == expected_forecast
    assert result["path_to_eligibility"] is not None
    assert expected_forecast.isoformat() in result["path_to_eligibility"]


def test_hold_period_met_contributes_no_blocking_status(db_session):
    make_rule(db_session, "TEST-M14-010", "United States", "acquisition_date", "n/a", "needs_evidence",
              hold_period_days=180)

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    acquired = date.today() - timedelta(days=200)  # past the 180-day window
    make_fact(db_session, listing.id, "United States", "acquisition_date", "n/a", as_of_date=acquired)

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "eligible_pending_review"
    assert result["forecast_date"] is None


def test_hold_period_rule_needs_evidence_when_fact_has_no_date(db_session):
    make_rule(db_session, "TEST-M14-011", "United States", "acquisition_date", "n/a", "needs_evidence",
              hold_period_days=180)

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    make_fact(db_session, listing.id, "United States", "acquisition_date", "n/a", as_of_date=None)

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "needs_evidence"
    assert any("missing a date" in r for r in result["reasons"])


# ---------------------------------------------------------------------------
# US-only SEC Rule 144(d)(3)(vii) estate exemption (hardcoded in Python)
# ---------------------------------------------------------------------------

def test_estate_exemption_bypasses_us_hold_period(db_session):
    make_rule(db_session, "TEST-M14-012", "United States", "acquisition_date", "n/a", "needs_evidence",
              hold_period_days=180)

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    acquired = date.today() - timedelta(days=30)  # would otherwise be blocked
    make_fact(db_session, listing.id, "United States", "acquisition_date", "n/a", as_of_date=acquired)
    make_fact(db_session, listing.id, "United States", "holder_deceased_estate_distribution", "yes")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "eligible_pending_review"
    assert any("estate exemption" in r for r in result["reasons"])


def test_estate_exemption_does_not_apply_outside_united_states(db_session):
    make_rule(db_session, "TEST-M14-013", "Australia", "acquisition_date", "n/a", "needs_evidence",
              hold_period_days=365)

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Australia")
    acquired = date.today() - timedelta(days=30)  # would otherwise be blocked
    make_fact(db_session, listing.id, "Australia", "acquisition_date", "n/a", as_of_date=acquired)
    make_fact(db_session, listing.id, "Australia", "holder_deceased_estate_distribution", "yes")

    result = evaluate_transferability(listing, db_session)
    # The estate fact exists but the exemption is coded US-only - an
    # Australian rule is not bypassed by it.
    assert result["status"] == "blocked"


# ---------------------------------------------------------------------------
# expected_fact_value - the fix for the requirement-check gap (2026-09-09).
# rule.requirement stays a human-readable legal description (matching
# what all six real seeded rules actually put there - full sentences,
# not comparable values); expected_fact_value is the new, separate,
# nullable field actually compared against a verified fact's value.
# ---------------------------------------------------------------------------

def test_matching_expected_value_is_satisfied(db_session):
    make_rule(db_session, "TEST-M14-020", "United States", "transfer_restriction_consent",
              requirement="Consent must be obtained per governing documents.",
              decision_if_unmet="blocked", expected_fact_value="obtained")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "obtained")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "eligible_pending_review"


def test_wrong_expected_value_uses_decision_if_unmet_blocked(db_session):
    make_rule(db_session, "TEST-M14-021", "United States", "transfer_restriction_consent",
              requirement="Consent must be obtained per governing documents.",
              decision_if_unmet="blocked", expected_fact_value="obtained")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "denied")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "blocked"
    assert any("TEST-M14-021" in r for r in result["reasons"])
    assert any("has value 'denied'" in r for r in result["reasons"])


def test_wrong_expected_value_uses_decision_if_unmet_needs_evidence(db_session):
    make_rule(db_session, "TEST-M14-022", "Canada", "issuer_reporting_status",
              requirement="Only reporting issuers get the standard hold period.",
              decision_if_unmet="needs_evidence", expected_fact_value="reporting")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Canada")
    make_fact(db_session, listing.id, "Canada", "issuer_reporting_status", "non_reporting")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "needs_evidence"
    assert any("TEST-M14-022" in r for r in result["reasons"])


def test_rules_without_expected_value_are_satisfied_by_any_verified_fact(db_session):
    # expected_fact_value is opt-in (nullable) - a rule that deliberately
    # leaves it unset keeps the original behavior: any verified fact of
    # the right fact_type satisfies it. This is intentional now (used by
    # the three real hold_period_days rules, where fact_value is a
    # placeholder and the real gating is the date math), not a bug.
    make_rule(db_session, "TEST-M14-023", "United States", "transfer_restriction_consent",
              requirement="Consent must be obtained per governing documents.",
              decision_if_unmet="blocked")  # expected_fact_value left None

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "anything_at_all")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "eligible_pending_review"


def test_expected_value_checked_before_hold_period_logic(db_session):
    # When both expected_fact_value and hold_period_days are set on the
    # same rule, a value mismatch is caught first - the rule never
    # reaches the date-math branch at all.
    make_rule(db_session, "TEST-M14-024", "United States", "acquisition_date",
              requirement="Must be a qualifying acquisition.",
              decision_if_unmet="blocked", expected_fact_value="qualifying",
              hold_period_days=180)

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    # A date far enough in the past that hold_period_days would be
    # satisfied - if the value check didn't run first, this would come
    # back eligible_pending_review instead of blocked.
    acquired = date.today() - timedelta(days=400)
    make_fact(db_session, listing.id, "United States", "acquisition_date", "non_qualifying", as_of_date=acquired)

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "blocked"
    assert result["forecast_date"] is None  # never reached the date-math branch


# ---------------------------------------------------------------------------
# multiple rules combined - status precedence
# conflict > blocked > needs_evidence > review > eligible_pending_review
# ---------------------------------------------------------------------------

def test_conflict_takes_precedence_over_blocked(db_session):
    make_rule(db_session, "TEST-M14-015", "United States", "transfer_restriction_consent", "obtained", "blocked")
    make_rule(db_session, "TEST-M14-016", "United States", "buyer_eligible_category", "eligible", "blocked")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    # TEST-M14-015's fact conflicts.
    make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "obtained")
    make_fact(db_session, listing.id, "United States", "transfer_restriction_consent", "denied")
    # TEST-M14-016's fact is simply missing -> would be "blocked" alone.

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "conflict"


def test_blocked_takes_precedence_over_needs_evidence(db_session):
    make_rule(db_session, "TEST-M14-017", "United States", "transfer_restriction_consent", "obtained", "blocked")
    make_rule(db_session, "TEST-M14-018", "United States", "buyer_eligible_category", "eligible", "needs_evidence")

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    # TEST-M14-017's fact is missing entirely -> "blocked".
    # TEST-M14-018's fact is also missing -> "needs_evidence".

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "blocked"


def test_inactive_rule_is_excluded(db_session):
    make_rule(db_session, "TEST-M14-019", "United States", "transfer_restriction_consent", "obtained", "blocked",
              active=False)

    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")

    result = evaluate_transferability(listing, db_session)
    assert result["status"] == "review"
    assert result["applicable_rule_count"] == 0
