"""
Tests for M33 (first slice) - the Issuer Liquidity Portal: the first real
company/issuer login-capable account type, admin-provisioned, plus a
read-only dashboard scoped to that issuer's own company (matched by the
free-text company name already used on Listing/OwnershipRecord/
TenderOfferProgram/BuyerInterest - no normalized Company table exists in
this schema).
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from datetime import date, datetime, timedelta

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
    RofrRequest,
    TransferabilityRule,
    TenderOfferProgram,
    BuyerInterest,
    ComplianceDecisionLedger,
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
    return TestClient(app)


def make_user(db, suffix, account_type="participant", role="buyer", kyc_status="verified", issuer_company_name=None):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m33-{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("password123"),
        issuer_company_name=issuer_company_name,
        terms_accepted=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user):
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_create_issuer_account(client, db_session):
    admin = make_user(db_session, "admin1", account_type="admin")

    resp = client.post(
        "/admin/issuer-accounts",
        json={
            "name": "Acme Issuer Contact",
            "email": "contact@acme-issuer.example.com",
            "password": "issuerpass123",
            "company_name": "Acme Private Co",
            "jurisdiction": "Delaware",
        },
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()["issuer"]
    assert body["company_name"] == "Acme Private Co"
    assert body["account_type"] == "issuer"


def test_non_admin_cannot_create_issuer_account(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")

    resp = client.post(
        "/admin/issuer-accounts",
        json={
            "name": "Fake Issuer",
            "email": "fake@example.com",
            "password": "pw",
            "company_name": "Whatever Inc",
        },
        headers=auth_headers(seller),
    )

    assert resp.status_code == 403


def test_non_issuer_cannot_reach_dashboard(client, db_session):
    seller = make_user(db_session, "seller2", role="seller")

    resp = client.get("/issuer/dashboard", headers=auth_headers(seller))

    assert resp.status_code == 403


def test_issuer_profile_endpoint(client, db_session):
    issuer = make_user(
        db_session, "issuer-profile", account_type="issuer",
        issuer_company_name="Acme Private Co",
    )

    resp = client.get("/issuer/me", headers=auth_headers(issuer))

    assert resp.status_code == 200
    body = resp.json()
    assert body["company_name"] == "Acme Private Co"
    assert body["account_type"] == "issuer"


def test_dashboard_scopes_strictly_to_the_issuers_own_company(client, db_session):
    issuer = make_user(
        db_session, "issuer-dash", account_type="issuer",
        issuer_company_name="Acme Private Co",
    )
    seller = make_user(db_session, "seller-dash", role="seller")
    other_seller = make_user(db_session, "other-seller-dash", role="seller")
    buyer = make_user(db_session, "buyer-dash", role="buyer")

    # A matching rule for Acme's listing (jurisdiction + asset_type must
    # match exactly, per find_applicable_transferability_rules).
    rule = TransferabilityRule(
        jurisdiction="Delaware",
        asset_type="Private Shares",
        fact_type="eligibility_verified",
        rule_code="M33-TEST-RULE",
        requirement="Buyer must be accredited",
        decision_if_unmet="review",
        active=True,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    acme_listing = ListingModel(
        seller_id=seller.id,
        company="Acme Private Co",
        asset_type="Private Shares",
        quantity=1000,
        asking_price=10.00,
        is_transferable=True,
        issuer_jurisdiction="Delaware",
    )
    other_listing = ListingModel(
        seller_id=other_seller.id,
        company="Other Private Co",
        asset_type="Private Shares",
        quantity=500,
        asking_price=5.00,
        is_transferable=True,
        issuer_jurisdiction="Delaware",
    )
    db_session.add_all([acme_listing, other_listing])
    db_session.commit()
    db_session.refresh(acme_listing)
    db_session.refresh(other_listing)

    acme_tx = Transaction(
        listing_id=acme_listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        quantity=100,
        agreed_price=10.00,
        status="settlement_pending",
    )
    other_tx = Transaction(
        listing_id=other_listing.id,
        buyer_id=buyer.id,
        seller_id=other_seller.id,
        quantity=50,
        agreed_price=5.00,
        status="settlement_pending",
    )
    db_session.add_all([acme_tx, other_tx])
    db_session.commit()
    db_session.refresh(acme_tx)
    db_session.refresh(other_tx)

    acme_rofr = RofrRequest(
        transaction_id=acme_tx.id,
        transferability_rule_id=rule.id,
        status="pending",
    )
    db_session.add(acme_rofr)

    acme_ownership = OwnershipRecord(
        seller_id=seller.id,
        listing_id=acme_listing.id,
        company="Acme Private Co",
        asset_type="Private Shares",
        quantity=900,
        verification_status="verified",
    )
    other_ownership = OwnershipRecord(
        seller_id=other_seller.id,
        company="Other Private Co",
        asset_type="Private Shares",
        quantity=500,
        verification_status="verified",
    )
    db_session.add_all([acme_ownership, other_ownership])

    acme_tender = TenderOfferProgram(
        company="Acme Private Co",
        jurisdiction="Delaware",
        price_per_share=12.00,
        opens_at=datetime.utcnow(),
        closes_at=datetime.utcnow() + timedelta(days=30),
        created_at=datetime.utcnow(),
    )
    db_session.add(acme_tender)

    acme_interest = BuyerInterest(
        buyer_id=buyer.id,
        company="Acme Private Co",
        asset_type="Private Shares",
        desired_quantity=200,
        maximum_price=11.00,
        status="active",
    )
    other_interest = BuyerInterest(
        buyer_id=buyer.id,
        company="Other Private Co",
        asset_type="Private Shares",
        desired_quantity=75,
        maximum_price=6.00,
        status="active",
    )
    db_session.add_all([acme_interest, other_interest])

    acme_decision = ComplianceDecisionLedger(
        transaction_id=acme_tx.id,
        buyer_id=buyer.id,
        listing_id=acme_listing.id,
        decision_status="eligible_pending_review",
        applicable_rule_codes="M33-TEST-RULE",
        triggered_by="transaction_creation",
        decided_at=datetime.utcnow(),
        previous_hash="0" * 64,
        entry_hash="1" * 64,
    )
    db_session.add(acme_decision)
    db_session.commit()

    resp = client.get("/issuer/dashboard", headers=auth_headers(issuer))

    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["company_name"] == "Acme Private Co"

    assert len(body["liquidity_seekers"]) == 1
    assert body["liquidity_seekers"][0]["listing_id"] == acme_listing.id

    assert len(body["pending_transfers"]) == 1
    assert body["pending_transfers"][0]["transaction_id"] == acme_tx.id

    assert len(body["rofr_requests"]) == 1
    assert body["rofr_requests"][0]["rofr_request_id"] == acme_rofr.id

    assert len(body["ownership_on_file"]) == 1
    assert body["ownership_on_file"][0]["quantity"] == 900

    assert len(body["tender_programs"]) == 1
    assert body["tender_programs"][0]["program_id"] == acme_tender.id

    assert body["shareholder_concentration"]["total_quantity_on_file"] == 900
    assert body["shareholder_concentration"]["distinct_holders"] == 1
    assert body["shareholder_concentration"]["top_holder_share_pct"] == 100.0

    assert len(body["transfer_restrictions"]) == 1
    assert body["transfer_restrictions"][0]["rule_code"] == "M33-TEST-RULE"

    # Aggregate only - no buyer_id anywhere in investor_demand.
    assert body["investor_demand"]["active_interest_count"] == 1
    assert body["investor_demand"]["total_desired_quantity"] == 200
    assert "buyer_id" not in str(body["investor_demand"])

    assert body["compliance_requests"]["eligible_pending_review"] == 1
    assert body["compliance_requests"]["blocked"] == 0

    assert body["cap_table_sync"]["connected"] is False
