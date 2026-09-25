"""
Tests for M27's second remaining piece (2026-09-25): compliance rule-
change impact alerts.

Written against the REAL ~/KEVO implementation.

Builds on the already-shipped Hash-Chained Compliance Decision Ledger
(M27 first slice, 2026-09-19) and the already-existing
PUT /compliance-rules/{rule_id} endpoint (2026-09-21, added specifically
to unlock this feature). When an admin edits a rule, KEVO finds every
still-open transaction whose most recent Ledger entry cited that exact
rule, re-runs the real assess_compliance() verdict against the rule's
new wording, and creates one alert only where the outcome actually
changed. Purely informational - never blocks or changes the transaction.
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
    ComplianceRule, ComplianceDecisionLedger, ComplianceRuleChangeAlert,
)
from app import app, get_db, hash_password, create_access_token

TEST_SOURCE = "TEST FIXTURE - not real regulatory content, rule-change-alert test only"


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


def make_user(db, suffix="1", role="buyer", account_type="participant",
              kyc_status="not_started", jurisdiction=None):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m27rulealert{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        jurisdiction=jurisdiction,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, asset_type="common_stock", issuer_jurisdiction="United States",
                  is_transferable=True, quantity=1000):
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type=asset_type,
        quantity=quantity, asking_price=50.0, is_transferable=is_transferable,
        issuer_jurisdiction=issuer_jurisdiction,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_rule(db, rule_code, active=True, buyer_jurisdiction="United States",
              issuer_jurisdiction="United States", asset_type="common_stock"):
    rule = ComplianceRule(
        buyer_jurisdiction=buyer_jurisdiction,
        issuer_jurisdiction=issuer_jurisdiction,
        asset_type=asset_type,
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


def make_eligible_buyer(db, suffix):
    return make_user(db, suffix, role="buyer", kyc_status="verified", jurisdiction="United States")


def create_transaction_via_api(client, buyer, listing, quantity=100, agreed_price=10000.0):
    resp = client.post("/transactions", headers=auth_headers(buyer), json={
        "listing_id": listing.id, "buyer_id": buyer.id,
        "quantity": quantity, "agreed_price": agreed_price,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["transaction"]


# --- Trigger: deactivating a rule changes the verdict -> alert created ---

def test_deactivating_rule_creates_alert_when_verdict_changes(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_eligible_buyer(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    rule = make_rule(db_session, "TEST-M27-DEACTIVATE-001")

    txn = create_transaction_via_api(client, buyer, listing)

    ledger_entry = db_session.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == txn["id"]
    ).first()
    assert ledger_entry.decision_status == "needs_evidence"

    resp = client.put(f"/compliance-rules/{rule.id}", headers=auth_headers(admin), json={
        "active": False,
    })
    assert resp.status_code == 200, resp.text

    alerts = db_session.query(ComplianceRuleChangeAlert).filter(
        ComplianceRuleChangeAlert.transaction_id == txn["id"]
    ).all()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.compliance_rule_id == rule.id
    assert alert.buyer_id == buyer.id
    assert alert.listing_id == listing.id
    assert alert.previous_decision_status == "needs_evidence"
    assert alert.new_decision_status == "review"
    assert alert.is_read is False


def test_no_alert_when_verdict_unchanged(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_eligible_buyer(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    rule = make_rule(db_session, "TEST-M27-NOCHANGE-001")

    txn = create_transaction_via_api(client, buyer, listing)

    resp = client.put(f"/compliance-rules/{rule.id}", headers=auth_headers(admin), json={
        "description": "Updated wording, same substance.",
    })
    assert resp.status_code == 200, resp.text

    alerts = db_session.query(ComplianceRuleChangeAlert).filter(
        ComplianceRuleChangeAlert.transaction_id == txn["id"]
    ).all()
    assert len(alerts) == 0


def test_no_alert_for_terminal_transaction(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_eligible_buyer(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    rule = make_rule(db_session, "TEST-M27-TERMINAL-001")

    txn = create_transaction_via_api(client, buyer, listing)

    resp = client.patch(f"/transactions/{txn['id']}/status", headers=auth_headers(seller), params={
        "status": "rejected",
    })
    assert resp.status_code == 200, resp.text

    resp = client.put(f"/compliance-rules/{rule.id}", headers=auth_headers(admin), json={
        "active": False,
    })
    assert resp.status_code == 200, resp.text

    alerts = db_session.query(ComplianceRuleChangeAlert).filter(
        ComplianceRuleChangeAlert.transaction_id == txn["id"]
    ).all()
    assert len(alerts) == 0


# --- GET /rule-change-alerts ---

def test_list_buyer_sees_only_own_admin_sees_all(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer1 = make_eligible_buyer(db_session, "2")
    buyer2 = make_eligible_buyer(db_session, "3")
    admin = make_user(db_session, "4", account_type="admin")
    listing1 = make_listing(db_session, seller)
    listing2 = make_listing(db_session, seller)
    rule = make_rule(db_session, "TEST-M27-LIST-001")

    create_transaction_via_api(client, buyer1, listing1)
    create_transaction_via_api(client, buyer2, listing2)

    resp = client.put(f"/compliance-rules/{rule.id}", headers=auth_headers(admin), json={"active": False})
    assert resp.status_code == 200, resp.text

    resp = client.get("/rule-change-alerts", headers=auth_headers(buyer1))
    assert resp.status_code == 200
    buyer1_alerts = resp.json()["alerts"]
    assert len(buyer1_alerts) == 1
    assert buyer1_alerts[0]["buyer_id"] == buyer1.id

    resp = client.get("/rule-change-alerts", headers=auth_headers(admin))
    assert resp.status_code == 200
    admin_alerts = resp.json()["alerts"]
    assert len(admin_alerts) == 2


def test_list_unauthenticated_401(client, db_session):
    resp = client.get("/rule-change-alerts")
    assert resp.status_code == 401


# --- GET /rule-change-alerts/{alert_id} ---

def test_get_single_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.get("/rule-change-alerts/999999", headers=auth_headers(admin))
    assert resp.status_code == 404


def test_get_single_non_owner_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_eligible_buyer(db_session, "2")
    stranger = make_user(db_session, "3", role="buyer")
    admin = make_user(db_session, "4", account_type="admin")
    listing = make_listing(db_session, seller)
    rule = make_rule(db_session, "TEST-M27-GETSINGLE-001")

    txn = create_transaction_via_api(client, buyer, listing)
    client.put(f"/compliance-rules/{rule.id}", headers=auth_headers(admin), json={"active": False})

    alert = db_session.query(ComplianceRuleChangeAlert).filter(
        ComplianceRuleChangeAlert.transaction_id == txn["id"]
    ).first()

    resp = client.get(f"/rule-change-alerts/{alert.id}", headers=auth_headers(stranger))
    assert resp.status_code == 403

    resp = client.get(f"/rule-change-alerts/{alert.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200

    resp = client.get(f"/rule-change-alerts/{alert.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


# --- PUT /rule-change-alerts/{alert_id}/mark-read ---

def test_mark_read_owner_only(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_eligible_buyer(db_session, "2")
    stranger = make_user(db_session, "3", role="buyer")
    admin = make_user(db_session, "4", account_type="admin")
    listing = make_listing(db_session, seller)
    rule = make_rule(db_session, "TEST-M27-MARKREAD-001")

    txn = create_transaction_via_api(client, buyer, listing)
    client.put(f"/compliance-rules/{rule.id}", headers=auth_headers(admin), json={"active": False})

    alert = db_session.query(ComplianceRuleChangeAlert).filter(
        ComplianceRuleChangeAlert.transaction_id == txn["id"]
    ).first()

    resp = client.put(f"/rule-change-alerts/{alert.id}/mark-read", headers=auth_headers(stranger))
    assert resp.status_code == 403

    resp = client.put(f"/rule-change-alerts/{alert.id}/mark-read", headers=auth_headers(admin))
    assert resp.status_code == 403

    resp = client.put(f"/rule-change-alerts/{alert.id}/mark-read", headers=auth_headers(buyer))
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_read"] is True
    assert body["read_at"] is not None


def test_mark_read_404(client, db_session):
    buyer = make_eligible_buyer(db_session, "1")
    resp = client.put("/rule-change-alerts/999999/mark-read", headers=auth_headers(buyer))
    assert resp.status_code == 404


def test_no_duplicate_alert_on_second_unrelated_edit(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_eligible_buyer(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    rule = make_rule(db_session, "TEST-M27-NODUPE-001")

    txn = create_transaction_via_api(client, buyer, listing)

    resp = client.put(f"/compliance-rules/{rule.id}", headers=auth_headers(admin), json={"active": False})
    assert resp.status_code == 200, resp.text

    alerts = db_session.query(ComplianceRuleChangeAlert).filter(
        ComplianceRuleChangeAlert.transaction_id == txn["id"]
    ).all()
    assert len(alerts) == 1, f"expected 1 alert after first real change, got {len(alerts)}"
    assert alerts[0].previous_decision_status == "needs_evidence"
    assert alerts[0].new_decision_status == "review"

    resp = client.put(f"/compliance-rules/{rule.id}", headers=auth_headers(admin), json={
        "description": "Second edit, still inactive, verdict already reflects this.",
    })
    assert resp.status_code == 200, resp.text

    alerts_after = db_session.query(ComplianceRuleChangeAlert).filter(
        ComplianceRuleChangeAlert.transaction_id == txn["id"]
    ).all()
    assert len(alerts_after) == 1, f"expected still exactly 1 alert, got {len(alerts_after)} (this is the exact bug the live check caught - comparing against a stale Ledger snapshot instead of the most recent alert)"
