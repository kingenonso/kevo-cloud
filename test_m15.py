"""
Tests for M15 (Liquidity Path Engine) - written against the REAL ~/KEVO
implementation (2026-09-09), after fixing three confirmed bugs found by
direct code + live-database audit this session:

  1. BUYER_ELIGIBILITY_COMPLIANCE was a hardcoded stub - it never queried
     for a candidate buyer or called the real M13 assess_compliance()
     engine, even when a transaction (and therefore a real buyer) already
     existed for the listing. Confirmed both in code (no db.query call in
     that block) and in the live database (all 3 real rows showed the
     identical static "no candidate buyer" text, including for the one
     listing that already had a completed transaction).
  2. BUYER_MATCHING counted BuyerInterest rows regardless of status - a
     withdrawn or already-fulfilled interest would incorrectly count as
     proof of a matching buyer. Same bug class as one already fixed in
     M16's heatmap/curve.
  3. NEGOTIATION_PRICE_AGREEMENT treated the mere existence of any
     Transaction row as proof negotiation was complete, without checking
     .status. Since agreed_price is a caller-supplied value present from
     the moment a transaction is created (even at the "interested" stage,
     confirmed via the invariant comment at app.py:831-837 and the real
     status lifecycle at app.py:1180-1220), this meant negotiation could
     read "complete" before anything was agreed, or even for a
     transaction whose latest status was "rejected".

Runs against an isolated in-memory SQLite database, same pattern as
test_m13.py / test_m14.py / test_m16.py - does not touch the real
Postgres config. A separate real-database proof (flush + rollback, no
commit) is run afterward outside pytest to confirm the fix against the
real schema without leaving residue.
"""

import os

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import itertools
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base,
    User as UserModel,
    Listing as ListingModel,
    Transaction,
    OwnershipRecord,
    ComplianceRule,
    BuyerInterest,
    LiquidityPathStep,
)
from app import app, get_db, build_liquidity_path, create_access_token

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


def make_seller(db):
    n = next(_email_counter)
    user = UserModel(name=f"Seller{n}", email=f"seller{n}@example.com", role="seller")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_buyer(db, kyc_status=None, jurisdiction=None):
    n = next(_email_counter)
    user = UserModel(
        name=f"Buyer{n}", email=f"buyer{n}@example.com", role="buyer",
        kyc_status=kyc_status, jurisdiction=jurisdiction,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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


def make_transaction(db, listing_id, buyer_id, seller_id, status="interested",
                      agreed_price=80.0, quantity=100):
    txn = Transaction(
        listing_id=listing_id, buyer_id=buyer_id, seller_id=seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


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


def make_compliance_rule(db, rule_code, fact_type, requirement, decision_if_unmet,
                          buyer_jurisdiction=None, issuer_jurisdiction=None, asset_type=None,
                          investor_classification=None, active=True):
    rule = ComplianceRule(
        buyer_jurisdiction=buyer_jurisdiction, issuer_jurisdiction=issuer_jurisdiction,
        asset_type=asset_type, investor_classification=investor_classification,
        rule_code=rule_code, description="TEST FIXTURE", fact_type=fact_type,
        requirement=requirement, decision_if_unmet=decision_if_unmet,
        requires_human_review=True, active=active,
        source_reference="TEST FIXTURE - M15 test only",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def make_interest(db, buyer_id, company="Acme Inc", asset_type="Private Shares",
                   desired_quantity=100, maximum_price=100.0, status="active"):
    interest = BuyerInterest(
        buyer_id=buyer_id, company=company, asset_type=asset_type,
        desired_quantity=desired_quantity, maximum_price=maximum_price, status=status,
    )
    db.add(interest)
    db.commit()
    db.refresh(interest)
    return interest


def step_by_type(result, step_type):
    for s in result["steps"]:
        if s["step_type"] == step_type:
            return s
    return None


# ---------------------------------------------------------------------------
# baseline structure - unaffected by the fixes, confirms nothing regressed
# ---------------------------------------------------------------------------

def test_returns_nine_steps_in_sequence_order(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id)

    result = build_liquidity_path(listing, db_session)
    assert len(result["steps"]) == 9
    assert [s["sequence_position"] for s in result["steps"]] == list(range(1, 10))
    assert [s["step_type"] for s in result["steps"]] == [
        "OWNERSHIP_VERIFICATION", "TRANSFERABILITY_CLEARANCE", "DOCUMENTATION_COMPLETE",
        "ISSUER_APPROVAL_ROFR", "BUYER_ELIGIBILITY_COMPLIANCE", "BUYER_MATCHING",
        "NEGOTIATION_PRICE_AGREEMENT", "SETTLEMENT", "CASH_RELEASE",
    ]


def test_ownership_verification_known_incomplete_when_no_record(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id)

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "OWNERSHIP_VERIFICATION")
    assert step["complete"] is False
    assert step["determinability"] == "known_incomplete"


def test_ownership_verification_known_complete_when_verified(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id)
    make_ownership(db_session, listing.id, seller.id, verification_status="verified")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "OWNERSHIP_VERIFICATION")
    assert step["complete"] is True
    assert step["determinability"] == "known_complete"


def test_settlement_and_cash_release_always_cannot_determine(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id)

    result = build_liquidity_path(listing, db_session)
    assert step_by_type(result, "SETTLEMENT")["determinability"] == "cannot_determine"
    assert step_by_type(result, "CASH_RELEASE")["determinability"] == "cannot_determine"


# ---------------------------------------------------------------------------
# Fix 1: BUYER_ELIGIBILITY_COMPLIANCE actually calls M13's assess_compliance()
# ---------------------------------------------------------------------------

def test_buyer_eligibility_stub_when_no_transaction(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id)
    # No transaction created - preserves the original correct behavior for
    # the case where there's genuinely no candidate buyer yet.

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "BUYER_ELIGIBILITY_COMPLIANCE")
    assert step["complete"] is False
    assert step["determinability"] == "required_but_unverified"
    assert "No candidate buyer identified yet" in step["reasons"]


def test_buyer_eligibility_evaluates_real_compliance_for_eligible_buyer(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session, kyc_status="verified", jurisdiction="United States")
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="interested")
    make_ownership(db_session, listing.id, seller.id, verification_status="verified")
    make_compliance_rule(db_session, "TEST-M15-001", fact_type="ownership_verified",
                          requirement="verified", decision_if_unmet="blocked")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "BUYER_ELIGIBILITY_COMPLIANCE")
    assert step["complete"] is True
    assert step["determinability"] == "known_complete"
    assert "eligible_pending_review" in step["reasons"]
    assert step["evidence_reference_type"] == "Transaction"


def test_buyer_eligibility_does_not_falsely_complete_for_noncompliant_buyer(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session, kyc_status="pending", jurisdiction="United States")
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="interested")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "BUYER_ELIGIBILITY_COMPLIANCE")
    assert step["complete"] is False
    assert step["determinability"] == "known_incomplete"
    assert "blocked" in step["reasons"]


def test_buyer_eligibility_cannot_determine_when_no_rules_seeded(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session, kyc_status="verified", jurisdiction="United States")
    listing = make_listing(db_session, seller.id, issuer_jurisdiction="United States")
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="interested")
    # No ComplianceRule rows at all.

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "BUYER_ELIGIBILITY_COMPLIANCE")
    assert step["complete"] is False
    assert step["determinability"] == "cannot_determine"
    assert "review" in step["reasons"]


# ---------------------------------------------------------------------------
# Fix 2: BUYER_MATCHING only counts active BuyerInterest rows
# ---------------------------------------------------------------------------

def test_buyer_matching_ignores_withdrawn_interest(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, asking_price=80.0, quantity=1000)
    make_interest(db_session, buyer.id, maximum_price=100.0, desired_quantity=500, status="withdrawn")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "BUYER_MATCHING")
    assert step["complete"] is False
    assert step["determinability"] == "known_incomplete"
    assert "0 buyer interest" in step["reasons"]


def test_buyer_matching_counts_active_interest(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id, asking_price=80.0, quantity=1000)
    make_interest(db_session, buyer.id, maximum_price=100.0, desired_quantity=500, status="active")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "BUYER_MATCHING")
    assert step["complete"] is True
    assert step["determinability"] == "known_complete"
    assert "1 buyer interest" in step["reasons"]


# ---------------------------------------------------------------------------
# Fix 3: NEGOTIATION_PRICE_AGREEMENT checks real transaction status
# ---------------------------------------------------------------------------

def test_negotiation_not_complete_when_no_transaction(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id)

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "NEGOTIATION_PRICE_AGREEMENT")
    assert step["complete"] is False
    assert step["determinability"] == "known_incomplete"
    assert "No transaction record exists" in step["reasons"]


def test_negotiation_not_complete_when_status_interested(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="interested")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "NEGOTIATION_PRICE_AGREEMENT")
    assert step["complete"] is False
    assert step["determinability"] == "known_incomplete"
    assert "current status is 'interested'" in step["reasons"]


def test_negotiation_not_complete_when_status_rejected(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="rejected")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "NEGOTIATION_PRICE_AGREEMENT")
    assert step["complete"] is False
    assert step["determinability"] == "known_incomplete"
    assert "current status is 'rejected'" in step["reasons"]


def test_negotiation_not_complete_when_status_cancelled(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="cancelled")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "NEGOTIATION_PRICE_AGREEMENT")
    assert step["complete"] is False
    assert "current status is 'cancelled'" in step["reasons"]


def test_negotiation_complete_when_status_accepted(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="accepted")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "NEGOTIATION_PRICE_AGREEMENT")
    assert step["complete"] is True
    assert step["determinability"] == "known_complete"
    assert "has status 'accepted'" in step["reasons"]


def test_negotiation_complete_when_status_settlement_pending(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="settlement_pending")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "NEGOTIATION_PRICE_AGREEMENT")
    assert step["complete"] is True


def test_negotiation_complete_when_status_completed(db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller.id)
    make_transaction(db_session, listing.id, buyer.id, seller.id, status="completed")

    result = build_liquidity_path(listing, db_session)
    step = step_by_type(result, "NEGOTIATION_PRICE_AGREEMENT")
    assert step["complete"] is True


# ---------------------------------------------------------------------------
# HTTP endpoint - confirms persistence still works after the fixes
# ---------------------------------------------------------------------------

def test_get_liquidity_path_endpoint_persists_and_returns_steps(db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller.id)
    client = TestClient(app)
    token = create_access_token(seller.id)

    response = client.get(f"/liquidity-path/listing/{listing.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["steps"]) == 9

    persisted = db_session.query(LiquidityPathStep).filter(
        LiquidityPathStep.run_id == body["run_id"]
    ).all()
    assert len(persisted) == 9
