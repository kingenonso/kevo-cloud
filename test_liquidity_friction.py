"""
Tests for the Liquidity Friction Indicator (first slice) - written against
the REAL ~/KEVO implementation (2026-09-19).

Packages M14's evaluate_transferability() and M15's build_liquidity_path()
into an explained illiquidity-friction readout for a listing. Nothing new
is computed or persisted here - this wraps two already-tested, already-real
engines. These tests focus on the new packaging logic itself: the
determinability breakdown, the main_constraint priority ordering (blocked
transferability > unresolved ROFR > other transferability issues > earliest
unresolved liquidity-path step), and that nothing is persisted.

Runs against an isolated in-memory SQLite database, same pattern as
test_m14.py / test_m15.py / test_m17.py - does not touch the real Postgres
config.
"""

import os

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import itertools
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base,
    User as UserModel,
    Listing as ListingModel,
    OwnershipRecord,
    TransferabilityRule,
    TransferabilityFact,
    LiquidityPathStep,
)
from app import app, get_db, hash_password, create_access_token

_email_counter = itertools.count(1)


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
        name="Auth Test User",
        email="__test_auth_user__@kevo.local",
        role="buyer",
        account_type="admin",
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def make_seller(db):
    n = next(_email_counter)
    user = UserModel(name=f"Seller{n}", email=f"seller{n}@example.com", role="seller")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_stranger_client(db):
    n = next(_email_counter)
    user = UserModel(
        name=f"Stranger{n}", email=f"stranger{n}@example.com", role="buyer",
        account_type="user", hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def make_listing(db, seller_id, issuer_jurisdiction="United States", asset_type="Private Shares",
                  is_transferable=True, company="Acme Inc", quantity=1000, asking_price=80.0):
    listing = ListingModel(
        seller_id=seller_id, company=company, asset_type=asset_type, quantity=quantity,
        asking_price=asking_price, is_transferable=is_transferable,
        issuer_jurisdiction=issuer_jurisdiction,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_ownership(db, listing_id, seller_id, company="Acme Inc", asset_type="Private Shares",
                    quantity=1000, verification_status="verified"):
    rec = OwnershipRecord(
        seller_id=seller_id, listing_id=listing_id, company=company, asset_type=asset_type,
        quantity=quantity, verification_status=verification_status,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def make_rule(db, jurisdiction, asset_type, fact_type, rule_code, decision_if_unmet,
              expected_fact_value=None, hold_period_days=None, active=True):
    rule = TransferabilityRule(
        jurisdiction=jurisdiction, asset_type=asset_type, fact_type=fact_type,
        rule_code=rule_code, requirement="TEST FIXTURE", decision_if_unmet=decision_if_unmet,
        requires_human_review=True, active=active,
        expected_fact_value=expected_fact_value, hold_period_days=hold_period_days,
        source_reference="TEST FIXTURE - liquidity friction test only",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def make_fact(db, listing_id, jurisdiction, fact_type, fact_value, as_of_date=None,
              verification_status="verified"):
    fact = TransferabilityFact(
        listing_id=listing_id, jurisdiction=jurisdiction, fact_type=fact_type,
        fact_value=fact_value, as_of_date=as_of_date, verification_status=verification_status,
    )
    db.add(fact)
    db.commit()
    db.refresh(fact)
    return fact


def step_by_type(result, step_type):
    for s in result["steps"]:
        if s["step_type"] == step_type:
            return s
    return None


def test_404_for_unknown_listing(client, db_session):
    resp = client.get("/liquidity-friction/listing/999999")
    assert resp.status_code == 404


def test_response_shape_has_expected_keys(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    assert resp.status_code == 200
    body = resp.json()
    for key in ["listing_id", "summary", "steps_breakdown", "main_constraint",
                "main_constraint_reason", "transferability", "rofr", "steps", "disclaimer"]:
        assert key in body


def test_disclaimer_says_not_a_price(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    disclaimer = resp.json()["disclaimer"].lower()
    assert "not a price" in disclaimer
    assert "valuation" in disclaimer


def test_any_authenticated_user_can_access_not_just_seller(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland")
    stranger_client = make_stranger_client(db_session)
    resp = stranger_client.get(f"/liquidity-friction/listing/{listing.id}")
    assert resp.status_code == 200


def test_steps_breakdown_sums_to_nine_and_matches_steps_list(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    assert len(body["steps"]) == 9
    breakdown = body["steps_breakdown"]
    assert sum(breakdown.values()) == 9
    real_counts = {"known_complete": 0, "known_incomplete": 0, "required_but_unverified": 0, "cannot_determine": 0}
    for s in body["steps"]:
        real_counts[s["determinability"]] += 1
    assert breakdown == real_counts


def test_nothing_is_persisted(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland")
    before = db_session.query(LiquidityPathStep).count()
    client.get(f"/liquidity-friction/listing/{listing.id}")
    client.get(f"/liquidity-friction/listing/{listing.id}")
    after = db_session.query(LiquidityPathStep).count()
    assert before == 0
    assert after == 0


def test_main_constraint_legal_transferability_when_no_rules_seeded(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland - No Rules")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    assert body["main_constraint"] == "legal_transferability"
    assert body["transferability"]["status"] == "review"
    assert "No transferability rules found" in body["main_constraint_reason"]


def test_main_constraint_legal_transferability_when_needs_evidence(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Evidenceland", asset_type="Private Shares")
    make_rule(db_session, jurisdiction="Evidenceland", asset_type="Private Shares",
              fact_type="transfer_consent", rule_code="TEST-NEEDS-EVIDENCE",
              decision_if_unmet="needs_evidence")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    assert body["main_constraint"] == "legal_transferability"
    assert body["transferability"]["status"] == "needs_evidence"


def test_main_constraint_legal_transferability_when_blocked_by_holding_period(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Holdland", asset_type="Private Shares")
    make_rule(db_session, jurisdiction="Holdland", asset_type="Private Shares",
              fact_type="holding_start", rule_code="TEST-HOLD-PERIOD",
              decision_if_unmet="blocked", expected_fact_value="yes", hold_period_days=180)
    make_fact(db_session, listing.id, jurisdiction="Holdland", fact_type="holding_start",
              fact_value="yes", as_of_date=date.today() - timedelta(days=10),
              verification_status="verified")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    assert body["main_constraint"] == "legal_transferability"
    assert body["transferability"]["status"] == "blocked"
    assert body["transferability"]["forecast_date"] is not None
    assert body["transferability"]["path_to_eligibility"] is not None


def test_main_constraint_rofr_consent_when_rofr_rule_unresolved(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="South Africa", asset_type="Private Shares")
    make_rule(db_session, jurisdiction="South Africa", asset_type="Private Shares",
              fact_type="rofr_consent_status", rule_code="ZA-COMPANIES-S8-ROFR-CONSENT",
              decision_if_unmet="review")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    assert body["main_constraint"] == "rofr_consent"
    assert body["rofr"]["determinability"] == "required_but_unverified"
    assert body["rofr"]["complete"] is False


def test_rofr_known_complete_when_verified_fact_on_file(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="South Africa", asset_type="Private Shares")
    make_rule(db_session, jurisdiction="South Africa", asset_type="Private Shares",
              fact_type="rofr_consent_status", rule_code="ZA-COMPANIES-S8-ROFR-CONSENT",
              decision_if_unmet="review", expected_fact_value="waived")
    make_fact(db_session, listing.id, jurisdiction="South Africa", fact_type="rofr_consent_status",
              fact_value="waived", verification_status="verified")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    assert body["rofr"]["determinability"] == "known_complete"
    assert body["rofr"]["complete"] is True
    assert body["main_constraint"] != "rofr_consent"


def test_rofr_cannot_determine_when_no_rofr_rule_matches_jurisdiction(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    assert body["rofr"]["determinability"] == "cannot_determine"
    assert body["rofr"]["complete"] is False


def test_main_constraint_falls_through_to_earliest_unresolved_step_when_transferability_and_rofr_resolved(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Cleared Land", asset_type="Private Shares")
    make_rule(db_session, jurisdiction="Cleared Land", asset_type="Private Shares",
              fact_type="transfer_consent", rule_code="TEST-CLEARED",
              decision_if_unmet="review", expected_fact_value="yes")
    make_fact(db_session, listing.id, jurisdiction="Cleared Land", fact_type="transfer_consent",
              fact_value="yes", verification_status="verified")
    make_ownership(db_session, listing.id, seller.id, verification_status="verified")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    assert body["transferability"]["status"] == "eligible_pending_review"
    assert body["rofr"]["determinability"] == "cannot_determine"
    ownership_step = step_by_type(body, "OWNERSHIP_VERIFICATION")
    assert ownership_step["determinability"] == "known_complete"
    assert body["main_constraint"] == "DOCUMENTATION_COMPLETE"


def test_steps_include_all_nine_expected_step_types_in_order(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    expected = [
        "OWNERSHIP_VERIFICATION", "TRANSFERABILITY_CLEARANCE", "DOCUMENTATION_COMPLETE",
        "ISSUER_APPROVAL_ROFR", "BUYER_ELIGIBILITY_COMPLIANCE", "BUYER_MATCHING",
        "NEGOTIATION_PRICE_AGREEMENT", "SETTLEMENT", "CASH_RELEASE",
    ]
    assert [s["step_type"] for s in body["steps"]] == expected


def test_summary_string_reports_real_counts(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="Nowhereland")
    resp = client.get(f"/liquidity-friction/listing/{listing.id}")
    body = resp.json()
    breakdown = body["steps_breakdown"]
    assert str(breakdown["known_complete"]) in body["summary"]
    assert str(breakdown["required_but_unverified"]) in body["summary"]
    assert str(breakdown["known_incomplete"]) in body["summary"]
    assert str(breakdown["cannot_determine"]) in body["summary"]
