"""
Tests for the M17 second slice (2026-09-11): the Deal Health Score.
Written against the REAL ~/KEVO implementation.

Design: build_deal_health(transaction, db) computes a breakdown-only
readout across six real, already-built sources (assess_compliance(),
User.kyc_status, OwnershipRecord.verification_status, Transaction.status,
TransferabilityAssessment.status, Evidence.verification_status). No
invented weighting, no composite number. Any dimension without real data
on file reads "cannot_determine" with a real reason rather than a guess.
Nothing is persisted - GET /deal-health/transaction/{transaction_id}
recomputes live on every call, same as assess_compliance() and
evaluate_transferability() already do.
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
    Base, User as UserModel, Listing as ListingModel, Transaction,
    OwnershipRecord, TransferabilityAssessment, TransferabilityRule, Evidence,
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


def make_deal(db_session, buyer_kyc="not_started", listing_transferable=True,
              transaction_status="interested"):
    seller = UserModel(name="Seller", email="seller_" + transaction_status + "_" + buyer_kyc + "@example.com",
                        role="seller", kyc_status="not_started")
    buyer = UserModel(name="Buyer", email="buyer_" + transaction_status + "_" + buyer_kyc + "@example.com",
                       role="buyer", kyc_status=buyer_kyc)
    db_session.add(seller)
    db_session.add(buyer)
    db_session.commit()

    listing = ListingModel(
        seller_id=seller.id, company="Test Co", asset_type="Private Shares",
        quantity=1000, asking_price=10000, is_transferable=listing_transferable
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
    response = client.get("/deal-health/transaction/999999")
    assert response.status_code == 404


def test_response_shape_has_expected_top_level_keys(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    assert response.status_code == 200
    body = response.json()
    assert body["transaction_id"] == transaction.id
    assert body["listing_id"] == listing.id
    assert "summary" in body
    assert "main_risk" in body
    assert "dimensions" in body


def test_returns_six_dimensions(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    dimension_names = [d["dimension"] for d in body["dimensions"]]
    assert sorted(dimension_names) == sorted([
        "compliance", "buyer_readiness", "ownership",
        "settlement_readiness", "regulatory_uncertainty", "documentation"
    ])


def test_compliance_blocked_when_buyer_kyc_not_verified(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, buyer_kyc="not_started")
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    compliance = next(d for d in body["dimensions"] if d["dimension"] == "compliance")
    assert compliance["status"] == "blocked"
    assert compliance["determinable"] is True
    assert "KYC" in compliance["reason"]


def test_compliance_not_blocked_when_kyc_verified_and_listing_transferable(client, db_session):
    transaction, listing, buyer, seller = make_deal(
        db_session, buyer_kyc="verified", listing_transferable=True
    )
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    compliance = next(d for d in body["dimensions"] if d["dimension"] == "compliance")
    assert compliance["status"] != "blocked"


def test_buyer_readiness_reflects_real_kyc_status(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, buyer_kyc="verified")
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    buyer_readiness = next(d for d in body["dimensions"] if d["dimension"] == "buyer_readiness")
    assert buyer_readiness["status"] == "verified"


def test_ownership_cannot_determine_when_no_ownership_record_for_listing(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    ownership = next(d for d in body["dimensions"] if d["dimension"] == "ownership")
    assert ownership["determinable"] is False
    assert ownership["status"] == "cannot_determine"


def test_ownership_pending_when_unverified_ownership_record_exists(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    record = OwnershipRecord(
        seller_id=seller.id, listing_id=listing.id, company="Test Co",
        asset_type="Private Shares", quantity=1000, verification_status="pending"
    )
    db_session.add(record)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    ownership = next(d for d in body["dimensions"] if d["dimension"] == "ownership")
    assert ownership["determinable"] is True
    assert ownership["status"] == "pending"


def test_ownership_verified_when_all_ownership_records_verified(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    record = OwnershipRecord(
        seller_id=seller.id, listing_id=listing.id, company="Test Co",
        asset_type="Private Shares", quantity=1000, verification_status="verified"
    )
    db_session.add(record)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    ownership = next(d for d in body["dimensions"] if d["dimension"] == "ownership")
    assert ownership["status"] == "verified"


def test_settlement_readiness_completed_maps_to_ready(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, transaction_status="completed")
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    settlement = next(d for d in body["dimensions"] if d["dimension"] == "settlement_readiness")
    assert settlement["status"] == "ready"


def test_settlement_readiness_rejected_maps_to_not_ready(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, transaction_status="rejected")
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    settlement = next(d for d in body["dimensions"] if d["dimension"] == "settlement_readiness")
    assert settlement["status"] == "not_ready"


def test_settlement_readiness_interested_maps_to_not_yet_committed(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, transaction_status="interested")
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    settlement = next(d for d in body["dimensions"] if d["dimension"] == "settlement_readiness")
    assert settlement["status"] == "not_yet_committed"


def test_regulatory_uncertainty_cannot_determine_when_no_assessment_on_file(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    reg = next(d for d in body["dimensions"] if d["dimension"] == "regulatory_uncertainty")
    assert reg["determinable"] is False
    assert reg["status"] == "cannot_determine"


def test_regulatory_uncertainty_reflects_live_transferability_status(client, db_session):
    # 2026-09-11 M14 fix: regulatory_uncertainty now calls evaluate_transferability()
    # live instead of reading stored TransferabilityAssessment rows - that table was
    # only ever populated by a write-on-GET bug in /transferability/listing/{id},
    # since there is no real way to create/update facts or evidence through the API.
    transaction, listing, buyer, seller = make_deal(db_session)
    listing.issuer_jurisdiction = "Testland"
    db_session.add(listing)
    db_session.commit()

    rule = TransferabilityRule(
        jurisdiction="Testland", asset_type="Private Shares",
        fact_type="some_required_fact", rule_code="TEST-RULE-REG-1",
        requirement="some required fact must be verified",
        decision_if_unmet="blocked", requires_human_review=True, active=True
    )
    db_session.add(rule)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    reg = next(d for d in body["dimensions"] if d["dimension"] == "regulatory_uncertainty")
    assert reg["determinable"] is True
    assert reg["status"] == "blocked"
    assert "some_required_fact" in reg["reason"]


def test_documentation_cannot_determine_when_no_evidence_on_file(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    docs = next(d for d in body["dimensions"] if d["dimension"] == "documentation")
    assert docs["determinable"] is False
    assert docs["status"] == "cannot_determine"


def test_documentation_verified_when_all_evidence_verified(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    evidence = Evidence(
        transaction_id=transaction.id, evidence_type="proof_of_ownership",
        description="signed cert", verification_status="verified"
    )
    db_session.add(evidence)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    docs = next(d for d in body["dimensions"] if d["dimension"] == "documentation")
    assert docs["status"] == "verified"


def test_documentation_pending_when_unverified_evidence_exists(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    evidence = Evidence(
        transaction_id=transaction.id, evidence_type="proof_of_ownership",
        description="signed cert", verification_status="pending"
    )
    db_session.add(evidence)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    docs = next(d for d in body["dimensions"] if d["dimension"] == "documentation")
    assert docs["status"] == "pending"


def test_main_risk_names_worst_determinable_dimension(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session, buyer_kyc="not_started")
    record = OwnershipRecord(
        seller_id=seller.id, listing_id=listing.id, company="Test Co",
        asset_type="Private Shares", quantity=1000, verification_status="pending"
    )
    db_session.add(record)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    assert body["main_risk"] is not None
    assert body["main_risk"]["dimension"] == "compliance"
    assert body["main_risk"]["status"] == "blocked"


def test_main_risk_is_none_when_every_determinable_dimension_is_healthy(client, db_session):
    transaction, listing, buyer, seller = make_deal(
        db_session, buyer_kyc="verified", listing_transferable=True,
        transaction_status="completed"
    )
    record = OwnershipRecord(
        seller_id=seller.id, listing_id=listing.id, company="Test Co",
        asset_type="Private Shares", quantity=1000, verification_status="verified"
    )
    db_session.add(record)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    dimension_statuses = {d["dimension"]: d["status"] for d in body["dimensions"]}
    if dimension_statuses["compliance"] == "eligible_pending_review":
        assert body["main_risk"] is None
    else:
        assert dimension_statuses["compliance"] in ("review", "needs_evidence")


def test_summary_reports_cannot_determine_count_correctly(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    determinable = [d for d in body["dimensions"] if d["determinable"]]
    cannot_determine = [d for d in body["dimensions"] if not d["determinable"]]
    assert len(determinable) == 3
    assert len(cannot_determine) == 3
    assert "3 dimension(s) cannot currently be determined" in body["summary"]


def test_endpoint_does_not_persist_anything(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)

    ownership_before = db_session.query(OwnershipRecord).count()
    transferability_before = db_session.query(TransferabilityAssessment).count()
    evidence_before = db_session.query(Evidence).count()

    client.get("/deal-health/transaction/" + str(transaction.id))
    client.get("/deal-health/transaction/" + str(transaction.id))

    assert db_session.query(OwnershipRecord).count() == ownership_before
    assert db_session.query(TransferabilityAssessment).count() == transferability_before
    assert db_session.query(Evidence).count() == evidence_before
