"""
Tests for M25's first slice (2026-09-18): Right of First Refusal (ROFR) --
consent request + response log.

POST /rofr-requests lets the transaction's seller (or an admin) submit a
ROFR consent request, grounded in a real TransferabilityRule that actually
applies to the transaction's listing (same jurisdiction + asset_type, via
find_applicable_transferability_rules). PUT .../respond lets only an admin
record the real-world outcome (approved / waived / exercised). GET
/rofr-requests lists the caller's own requests (admin sees all). GET
/rofr-requests/{id} is scoped to the transaction's buyer, seller, or admin.

Still deliberately avoids any auto-triggered countdown or automatic
escalation when a deadline passes -- see
claude/kevo-m25-rofr-patent-claim-analysis.md for why. As of 2026-09-25,
response_due_date is computed from TransferabilityRule.rofr_response_window_days
when that rule has a real, sourced window on file; it stays null otherwise --
no jurisdiction-wide deadline is ever invented (confirmed by research: ROFR
response periods are always a company's own contractual term, never statutory).
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
    TransferabilityRule, RofrRequest,
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


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_user(db, suffix="1", role="buyer", account_type="participant", kyc_status="not_started"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m25user{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, quantity=1000, issuer_jurisdiction="ZA", asset_type="Private Shares"):
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type=asset_type,
        quantity=quantity, asking_price=50.0, is_transferable=True,
        issuer_jurisdiction=issuer_jurisdiction,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_transaction(db, listing, buyer, quantity=100, status="interested", agreed_price=10.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_transferability_rule(db, jurisdiction="ZA", asset_type="Private Shares",
                               rule_code=None, active=True, fact_type="rofr_consent",
                               requirement="Company must consent under ROFR before transfer",
                               decision_if_unmet="block"):
    rule = TransferabilityRule(
        jurisdiction=jurisdiction, asset_type=asset_type, fact_type=fact_type,
        rule_code=rule_code or f"TEST-ROFR-{id(object())}",
        requirement=requirement, decision_if_unmet=decision_if_unmet,
        requires_human_review=True, active=active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


# --- POST /rofr-requests ---

def test_seller_can_submit_rofr_request(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)

    resp = client.post("/rofr-requests", headers=auth_headers(seller), json={
        "transaction_id": txn.id,
        "transferability_rule_id": rule.id,
        "source_reference": "ZA Companies Act s8 consent letter",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["transaction_id"] == txn.id
    assert body["transferability_rule_id"] == rule.id


def test_admin_can_submit_rofr_request(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)

    resp = client.post("/rofr-requests", headers=auth_headers(admin), json={
        "transaction_id": txn.id,
        "transferability_rule_id": rule.id,
    })
    assert resp.status_code == 200


def test_non_seller_non_admin_cannot_submit_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)

    resp = client.post("/rofr-requests", headers=auth_headers(stranger), json={
        "transaction_id": txn.id,
        "transferability_rule_id": rule.id,
    })
    assert resp.status_code == 403


def test_buyer_cannot_submit_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)

    resp = client.post("/rofr-requests", headers=auth_headers(buyer), json={
        "transaction_id": txn.id,
        "transferability_rule_id": rule.id,
    })
    assert resp.status_code == 403


def test_submit_unauthenticated_401(client, db_session):
    resp = client.post("/rofr-requests", json={
        "transaction_id": 1,
        "transferability_rule_id": 1,
    })
    assert resp.status_code == 401


def test_submit_unknown_transaction_404(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    rule = make_transferability_rule(db_session)
    resp = client.post("/rofr-requests", headers=auth_headers(seller), json={
        "transaction_id": 999999,
        "transferability_rule_id": rule.id,
    })
    assert resp.status_code == 404


def test_submit_unknown_rule_404(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post("/rofr-requests", headers=auth_headers(seller), json={
        "transaction_id": txn.id,
        "transferability_rule_id": 999999,
    })
    assert resp.status_code == 404


def test_submit_rule_not_applicable_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller, issuer_jurisdiction="ZA")
    txn = make_transaction(db_session, listing, buyer)
    wrong_rule = make_transferability_rule(db_session, jurisdiction="US")

    resp = client.post("/rofr-requests", headers=auth_headers(seller), json={
        "transaction_id": txn.id,
        "transferability_rule_id": wrong_rule.id,
    })
    assert resp.status_code == 400


# --- PUT /rofr-requests/{id}/respond ---

def test_admin_can_respond_approved(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()
    db_session.refresh(rofr)

    resp = client.put(
        f"/rofr-requests/{rofr.id}/respond",
        headers=auth_headers(admin),
        params={"status": "approved", "response_notes": "Board consented in writing"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["response_notes"] == "Board consented in writing"
    assert body["responded_at"] is not None


@pytest.mark.parametrize("status", ["approved", "waived", "exercised"])
def test_admin_can_respond_each_valid_status(client, db_session, status):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()
    db_session.refresh(rofr)

    resp = client.put(f"/rofr-requests/{rofr.id}/respond", headers=auth_headers(admin), params={"status": status})
    assert resp.status_code == 200
    assert resp.json()["status"] == status


def test_non_admin_cannot_respond_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()
    db_session.refresh(rofr)

    resp = client.put(f"/rofr-requests/{rofr.id}/respond", headers=auth_headers(seller), params={"status": "approved"})
    assert resp.status_code == 403


def test_respond_invalid_status_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()
    db_session.refresh(rofr)

    resp = client.put(f"/rofr-requests/{rofr.id}/respond", headers=auth_headers(admin), params={"status": "denied"})
    assert resp.status_code == 400


def test_respond_unknown_request_404(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.put("/rofr-requests/999999/respond", headers=auth_headers(admin), params={"status": "approved"})
    assert resp.status_code == 404


def test_respond_unauthenticated_401(client, db_session):
    resp = client.put("/rofr-requests/1/respond", params={"status": "approved"})
    assert resp.status_code == 401


# --- GET /rofr-requests (list) ---

def test_list_scoped_to_own_transactions(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()

    resp_seller = client.get("/rofr-requests", headers=auth_headers(seller))
    assert resp_seller.status_code == 200
    assert len(resp_seller.json()) == 1

    resp_buyer = client.get("/rofr-requests", headers=auth_headers(buyer))
    assert resp_buyer.status_code == 200
    assert len(resp_buyer.json()) == 1

    resp_stranger = client.get("/rofr-requests", headers=auth_headers(stranger))
    assert resp_stranger.status_code == 200
    assert len(resp_stranger.json()) == 0


def test_admin_sees_all_in_list(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()

    resp = client.get("/rofr-requests", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_unauthenticated_401(client, db_session):
    resp = client.get("/rofr-requests")
    assert resp.status_code == 401


# --- GET /rofr-requests/{id} ---

def test_get_by_id_party_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()
    db_session.refresh(rofr)

    for user in (seller, buyer):
        resp = client.get(f"/rofr-requests/{rofr.id}", headers=auth_headers(user))
        assert resp.status_code == 200


def test_get_by_id_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()
    db_session.refresh(rofr)

    resp = client.get(f"/rofr-requests/{rofr.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_get_by_id_non_party_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rofr = RofrRequest(transaction_id=txn.id, transferability_rule_id=rule.id, status="pending")
    db_session.add(rofr)
    db_session.commit()
    db_session.refresh(rofr)

    resp = client.get(f"/rofr-requests/{rofr.id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_get_by_id_unknown_404(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    resp = client.get("/rofr-requests/999999", headers=auth_headers(seller))
    assert resp.status_code == 404


def test_get_by_id_unauthenticated_401(client, db_session):
    resp = client.get("/rofr-requests/1")
    assert resp.status_code == 401


# --- response_due_date (added 2026-09-25) ---

def test_response_due_date_computed_when_rule_has_window(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)
    rule.rofr_response_window_days = 30
    db_session.commit()

    resp = client.post("/rofr-requests", headers=auth_headers(seller), json={
        "transaction_id": txn.id,
        "transferability_rule_id": rule.id,
        "source_reference": "Shareholders agreement clause 7.2, 30-day response window",
    })
    assert resp.status_code == 200
    body = resp.json()
    expected_due = (date.today() + timedelta(days=30)).isoformat()
    assert body["response_due_date"] == expected_due


def test_response_due_date_null_when_rule_has_no_window(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    rule = make_transferability_rule(db_session)

    resp = client.post("/rofr-requests", headers=auth_headers(seller), json={
        "transaction_id": txn.id,
        "transferability_rule_id": rule.id,
        "source_reference": "No sourced response window for this rule yet",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_due_date"] is None
