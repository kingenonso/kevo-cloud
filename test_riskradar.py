"""
Tests for the M17 third slice (2026-09-11): the Transaction Risk Radar.
Written against the REAL ~/KEVO implementation.

Design: build_risk_radar(transaction, db) returns four real, binary risk
flags - each either fires on a real condition in the data or it doesn't.
No invented severity weighting, no invented percentage thresholds.
Nothing is persisted - GET /risk-radar/transaction/{transaction_id}
recomputes live on every call, same pattern as build_deal_health() and
assess_compliance().
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    TransferabilityAssessment, TransferabilityFact, TransferabilityRule,
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
    auth_user = UserModel(
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


def make_deal(db_session, seller_affiliate_status=None, transaction_status="interested"):
    seller = UserModel(
        name="Seller", email="seller_" + str(transaction_status) + "_" + str(seller_affiliate_status) + "@example.com",
        role="seller", kyc_status="not_started", seller_affiliate_status=seller_affiliate_status
    )
    buyer = UserModel(
        name="Buyer", email="buyer_" + str(transaction_status) + "_" + str(seller_affiliate_status) + "@example.com",
        role="buyer", kyc_status="not_started"
    )
    db_session.add(seller)
    db_session.add(buyer)
    db_session.commit()

    listing = ListingModel(
        seller_id=seller.id, company="Test Co", asset_type="Private Shares",
        quantity=1000, asking_price=10000, is_transferable=True
    )
    db_session.add(listing)
    db_session.commit()

    transaction = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id,
        quantity=100, agreed_price=1000, status=transaction_status
    )
    db_session.add(transaction)
    db_session.commit()

    return transaction, listing, buyer, seller


def test_404_for_unknown_transaction(client):
    response = client.get("/risk-radar/transaction/999999")
    assert response.status_code == 404


def test_response_shape_has_expected_top_level_keys(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == transaction.id
    assert body["listing_id"] == listing.id
    assert "summary" in body
    assert "flags" in body


def test_returns_four_flags(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag_types = [f["flag_type"] for f in body["flags"]]
    assert sorted(flag_types) == sorted([
        "seller_affiliate_status", "transferability_conflict",
        "competing_active_transactions", "transferability_forecast_timing"
    ])


def test_affiliate_status_clear_when_non_affiliate(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, seller_affiliate_status="non_affiliate")
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "seller_affiliate_status")
    assert flag["status"] == "clear"


def test_affiliate_status_flagged_when_not_recorded(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, seller_affiliate_status=None)
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "seller_affiliate_status")
    assert flag["status"] == "flagged"
    assert "not been recorded" in flag["reason"]


def test_affiliate_status_flagged_when_actually_affiliated(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, seller_affiliate_status="director")
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "seller_affiliate_status")
    assert flag["status"] == "flagged"
    assert "director" in flag["reason"]


def test_transferability_conflict_clear_when_no_assessments(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_conflict")
    assert flag["status"] == "clear"


def test_transferability_conflict_clear_when_only_non_conflict_assessments(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    a = TransferabilityAssessment(listing_id=listing.id, status="eligible", explanation="all clear")
    db_session.add(a)
    db_session.commit()

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_conflict")
    assert flag["status"] == "clear"


def test_transferability_conflict_flagged_when_real_conflict_exists(client, db_session):
    # 2026-09-11 M14 fix: this flag now calls evaluate_transferability() live
    # instead of reading stored TransferabilityAssessment rows.
    transaction, listing, buyer, seller = make_deal(db_session)
    listing.issuer_jurisdiction = "Testland"
    db_session.add(listing)
    db_session.commit()

    rule = TransferabilityRule(
        jurisdiction="Testland", asset_type="Private Shares",
        fact_type="acquisition_date_source", rule_code="TEST-CONFLICT-1",
        requirement="acquisition_date_source must be verified",
        decision_if_unmet="review", requires_human_review=True, active=True
    )
    db_session.add(rule)
    db_session.commit()

    fact_a = TransferabilityFact(
        listing_id=listing.id, jurisdiction="Testland",
        fact_type="acquisition_date_source", fact_value="2020-01-01",
        verification_status="verified"
    )
    fact_b = TransferabilityFact(
        listing_id=listing.id, jurisdiction="Testland",
        fact_type="acquisition_date_source", fact_value="2021-06-15",
        verification_status="verified"
    )
    db_session.add(fact_a)
    db_session.add(fact_b)
    db_session.commit()

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_conflict")
    assert flag["status"] == "flagged"
    assert "acquisition_date_source" in flag["reason"]


def test_competing_transactions_clear_when_alone_on_listing(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "competing_active_transactions")
    assert flag["status"] == "clear"


def test_competing_transactions_flagged_when_another_active_transaction_exists(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, transaction_status="interested")
    other_buyer = UserModel(name="Other Buyer", email="other_buyer@example.com", role="buyer")
    db_session.add(other_buyer)
    db_session.commit()

    other_transaction = Transaction(
        listing_id=listing.id, buyer_id=other_buyer.id, seller_id=seller.id,
        quantity=50, agreed_price=500, status="accepted"
    )
    db_session.add(other_transaction)
    db_session.commit()

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "competing_active_transactions")
    assert flag["status"] == "flagged"
    assert "1 other active transaction" in flag["reason"]


def test_competing_transactions_ignores_terminal_status_transactions(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, transaction_status="interested")
    other_buyer = UserModel(name="Other Buyer", email="other_buyer2@example.com", role="buyer")
    db_session.add(other_buyer)
    db_session.commit()

    other_transaction = Transaction(
        listing_id=listing.id, buyer_id=other_buyer.id, seller_id=seller.id,
        quantity=50, agreed_price=500, status="rejected"
    )
    db_session.add(other_transaction)
    db_session.commit()

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "competing_active_transactions")
    assert flag["status"] == "clear"


def test_competing_transactions_does_not_count_itself(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, transaction_status="accepted")
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "competing_active_transactions")
    assert flag["status"] == "clear"


def test_forecast_timing_clear_when_no_assessments(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_forecast_timing")
    assert flag["status"] == "clear"


def test_forecast_timing_clear_when_blocked_assessment_has_no_forecast_date(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    a = TransferabilityAssessment(
        listing_id=listing.id, status="blocked", explanation="holding period not met"
    )
    db_session.add(a)
    db_session.commit()

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_forecast_timing")
    assert flag["status"] == "clear"


def test_forecast_timing_flagged_when_blocked_assessment_has_real_forecast_date(client, db_session):
    # 2026-09-11 M14 fix: this flag now calls evaluate_transferability() live
    # instead of reading stored TransferabilityAssessment rows.
    transaction, listing, buyer, seller = make_deal(db_session)
    listing.issuer_jurisdiction = "Testland"
    db_session.add(listing)
    db_session.commit()

    rule = TransferabilityRule(
        jurisdiction="Testland", asset_type="Private Shares",
        fact_type="acquisition_date", rule_code="TEST-HOLD-1",
        requirement="6 month holding period", decision_if_unmet="blocked",
        requires_human_review=True, active=True, hold_period_days=180
    )
    db_session.add(rule)
    db_session.commit()

    acquisition_date = date.today() - timedelta(days=30)
    fact = TransferabilityFact(
        listing_id=listing.id, jurisdiction="Testland",
        fact_type="acquisition_date", fact_value=acquisition_date.isoformat(),
        as_of_date=acquisition_date, verification_status="verified"
    )
    db_session.add(fact)
    db_session.commit()

    expected_forecast_date = acquisition_date + timedelta(days=180)

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_forecast_timing")
    assert flag["status"] == "flagged"
    assert expected_forecast_date.isoformat() in flag["reason"]


def test_summary_counts_flagged_flags_correctly(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, seller_affiliate_status=None)
    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    assert body["summary"] == "1 of 4 risk flag(s) triggered for this transaction"


def test_endpoint_does_not_persist_anything(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)

    transaction_count_before = db_session.query(Transaction).count()
    assessment_count_before = db_session.query(TransferabilityAssessment).count()

    client.get("/risk-radar/transaction/" + str(transaction.id))
    client.get("/risk-radar/transaction/" + str(transaction.id))

    assert db_session.query(Transaction).count() == transaction_count_before
    assert db_session.query(TransferabilityAssessment).count() == assessment_count_before
