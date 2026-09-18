"""
Tests for M19 Authorization (2026-09-18) - identity-to-resource-relationship
based authorization, replacing M1-M18's role-label checks. Written against
the REAL ~/KEVO implementation, per the architecture audit approved in
claude/kevo-m19-authorization-architecture-audit-and-design.md.

Core pattern under test: every gated endpoint now checks current_user.id
against the resource's actual owning/party id(s) - not the role recorded
on a user referenced in the request body. Marketplace capability
(buyer/seller) is derived from existing foreign keys, never stored as a
role list - so a single account can freely be both a seller (via
Listing.seller_id) and a buyer (via BuyerInterest.buyer_id /
Transaction.buyer_id) at the same time.
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
    Base,
    User as UserModel,
    Listing as ListingModel,
    OwnershipRecord,
    Transaction,
    BuyerInterest,
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


def make_user(db, suffix="1", role="buyer", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m19user{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, quantity=1000):
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=quantity, asking_price=50.0, is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_ownership(db, listing, seller, verification_status="pending"):
    record = OwnershipRecord(
        seller_id=seller.id, listing_id=listing.id, company="Acme Inc",
        asset_type="Private Shares", quantity=1000,
        verification_status=verification_status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def make_transaction(db, listing, buyer, quantity=100, status="interested"):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=10.0, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_interest(db, buyer, company="Acme Inc"):
    interest = BuyerInterest(
        buyer_id=buyer.id, company=company, asset_type="Private Shares",
        desired_quantity=100, maximum_price=20.0, status="active",
    )
    db.add(interest)
    db.commit()
    db.refresh(interest)
    return interest


def listing_payload(seller_id, **overrides):
    payload = {
        "seller_id": seller_id,
        "company": "Acme Inc",
        "asset_type": "Private Shares",
        "quantity": 1000,
        "asking_price": 50.0,
        "is_transferable": True,
    }
    payload.update(overrides)
    return payload


def ownership_payload(listing_id, seller_id):
    return {
        "listing_id": listing_id,
        "seller_id": seller_id,
        "company": "Acme Inc",
        "asset_type": "Private Shares",
        "quantity": 1000,
    }


def interest_payload(buyer_id, **overrides):
    payload = {
        "buyer_id": buyer_id,
        "company": "Acme Inc",
        "asset_type": "Private Shares",
        "desired_quantity": 100,
        "maximum_price": 20.0,
    }
    payload.update(overrides)
    return payload


def eligibility_payload(buyer_id, **overrides):
    payload = {
        "buyer_id": buyer_id,
        "investor_type": "individual",
        "classification": "accredited_investor",
    }
    payload.update(overrides)
    return payload


def compliance_rule_payload(**overrides):
    payload = {
        "rule_code": f"TEST-M19-{id(object())}",
        "description": "M19 authorization test rule.",
        "fact_type": "eligibility_verified",
        "requirement": "verified",
        "decision_if_unmet": "blocked",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Critical requirement: buyer and seller are not mutually exclusive - one
# authenticated account can create a Listing (as seller) and a
# BuyerInterest (as buyer) with no role switch of any kind.
# ---------------------------------------------------------------------------

def test_same_account_can_be_both_seller_and_buyer(client, db_session):
    user = make_user(db_session, "1")

    listing_resp = client.post(
        "/listings", json=listing_payload(user.id), headers=auth_headers(user)
    )
    assert listing_resp.status_code == 200

    interest_resp = client.post(
        "/buyer-interests",
        json=interest_payload(user.id, company="Beta Corp"),
        headers=auth_headers(user),
    )
    assert interest_resp.status_code == 200


# ---------------------------------------------------------------------------
# Listings - POST /listings, PUT /listings/{id}, DELETE /listings/{id}
# ---------------------------------------------------------------------------

def test_create_listing_owner_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200


def test_create_listing_non_owner_403(client, db_session):
    seller = make_user(db_session, "1")
    other = make_user(db_session, "2")
    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(other))
    assert resp.status_code == 403


def test_create_listing_cannot_impersonate_another_user_via_body(client, db_session):
    caller = make_user(db_session, "1")
    someone_else = make_user(db_session, "2")
    resp = client.post("/listings", json=listing_payload(someone_else.id), headers=auth_headers(caller))
    assert resp.status_code == 403


def test_create_listing_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1")
    resp = client.post("/listings", json=listing_payload(seller.id))
    assert resp.status_code == 401


def test_get_listings_broad_access_for_any_authenticated_user(client, db_session):
    seller = make_user(db_session, "1")
    other = make_user(db_session, "2")
    make_listing(db_session, seller)
    resp = client.get("/listings", headers=auth_headers(other))
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_listings_unauthenticated_401(client, db_session):
    resp = client.get("/listings")
    assert resp.status_code == 401


def test_update_listing_owner_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    listing = make_listing(db_session, seller)
    resp = client.put(
        f"/listings/{listing.id}",
        json=listing_payload(seller.id, asking_price=75.0),
        headers=auth_headers(seller),
    )
    assert resp.status_code == 200


def test_update_listing_non_owner_403(client, db_session):
    seller = make_user(db_session, "1")
    other = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    resp = client.put(
        f"/listings/{listing.id}",
        json=listing_payload(seller.id, asking_price=75.0),
        headers=auth_headers(other),
    )
    assert resp.status_code == 403


def test_update_listing_cannot_reassign_to_another_user(client, db_session):
    seller = make_user(db_session, "1")
    other = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    resp = client.put(
        f"/listings/{listing.id}",
        json=listing_payload(other.id),
        headers=auth_headers(seller),
    )
    assert resp.status_code == 403


def test_delete_listing_owner_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    listing = make_listing(db_session, seller)
    resp = client.delete(f"/listings/{listing.id}", headers=auth_headers(seller))
    assert resp.status_code == 200


def test_delete_listing_non_owner_403(client, db_session):
    seller = make_user(db_session, "1")
    other = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    resp = client.delete(f"/listings/{listing.id}", headers=auth_headers(other))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Ownership records - POST /ownership, PUT /ownership/{id}/verify
# ---------------------------------------------------------------------------

def test_create_ownership_owner_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    listing = make_listing(db_session, seller)
    resp = client.post(
        "/ownership", json=ownership_payload(listing.id, seller.id), headers=auth_headers(seller)
    )
    assert resp.status_code == 200


def test_create_ownership_non_owner_403(client, db_session):
    seller = make_user(db_session, "1")
    other = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    resp = client.post(
        "/ownership", json=ownership_payload(listing.id, seller.id), headers=auth_headers(other)
    )
    assert resp.status_code == 403


def test_verify_ownership_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    listing = make_listing(db_session, seller)
    ownership = make_ownership(db_session, listing, seller)
    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "verified", "verification_reference": "ref-123"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200


def test_verify_ownership_participant_403(client, db_session):
    seller = make_user(db_session, "1")
    listing = make_listing(db_session, seller)
    ownership = make_ownership(db_session, listing, seller)
    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "verified", "verification_reference": "ref-123"},
        headers=auth_headers(seller),
    )
    assert resp.status_code == 403


def test_verify_ownership_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1")
    listing = make_listing(db_session, seller)
    ownership = make_ownership(db_session, listing, seller)
    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "verified", "verification_reference": "ref-123"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Transactions - POST /transactions, GET /transactions[/id], PATCH .../status
# ---------------------------------------------------------------------------

def test_create_transaction_buyer_party_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    resp = client.post(
        "/transactions",
        json={"listing_id": listing.id, "buyer_id": buyer.id, "quantity": 100, "agreed_price": 10.0},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200


def test_create_transaction_seller_party_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    resp = client.post(
        "/transactions",
        json={"listing_id": listing.id, "buyer_id": buyer.id, "quantity": 100, "agreed_price": 10.0},
        headers=auth_headers(seller),
    )
    assert resp.status_code == 200


def test_create_transaction_non_party_403(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    resp = client.post(
        "/transactions",
        json={"listing_id": listing.id, "buyer_id": buyer.id, "quantity": 100, "agreed_price": 10.0},
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 403


def test_create_transaction_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    resp = client.post(
        "/transactions",
        json={"listing_id": listing.id, "buyer_id": buyer.id, "quantity": 100, "agreed_price": 10.0},
    )
    assert resp.status_code == 401


def test_get_transactions_scoped_to_own_party(client, db_session):
    seller = make_user(db_session, "1")
    buyer1 = make_user(db_session, "2")
    buyer2 = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    make_transaction(db_session, listing, buyer1)
    make_transaction(db_session, listing, buyer2)

    resp = client.get("/transactions", headers=auth_headers(buyer1))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["buyer_id"] == buyer1.id


def test_get_transactions_admin_sees_all(client, db_session):
    seller = make_user(db_session, "1")
    buyer1 = make_user(db_session, "2")
    buyer2 = make_user(db_session, "3")
    admin = make_user(db_session, "4", account_type="admin")
    listing = make_listing(db_session, seller)
    make_transaction(db_session, listing, buyer1)
    make_transaction(db_session, listing, buyer2)

    resp = client.get("/transactions", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_transactions_unauthenticated_401(client, db_session):
    resp = client.get("/transactions")
    assert resp.status_code == 401


def test_get_transaction_by_id_party_succeeds(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200


def test_get_transaction_by_id_non_party_403(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_update_transaction_status_buyer_can_cancel(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.patch(
        f"/transactions/{txn.id}/status", params={"status": "cancelled"}, headers=auth_headers(buyer)
    )
    assert resp.status_code == 200


def test_update_transaction_status_non_party_403(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    stranger = make_user(db_session, "3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.patch(
        f"/transactions/{txn.id}/status", params={"status": "cancelled"}, headers=auth_headers(stranger)
    )
    assert resp.status_code == 403


def test_update_transaction_status_seller_can_accept(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.patch(
        f"/transactions/{txn.id}/status", params={"status": "accepted"}, headers=auth_headers(seller)
    )
    assert resp.status_code == 200


def test_update_transaction_status_buyer_cannot_accept_403(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.patch(
        f"/transactions/{txn.id}/status", params={"status": "accepted"}, headers=auth_headers(buyer)
    )
    assert resp.status_code == 403


def test_update_transaction_status_admin_can_accept(client, db_session):
    seller = make_user(db_session, "1")
    buyer = make_user(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.patch(
        f"/transactions/{txn.id}/status", params={"status": "accepted"}, headers=auth_headers(admin)
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Buyer interests - POST/GET /buyer-interests[/id], GET .../matches
# ---------------------------------------------------------------------------

def test_create_buyer_interest_owner_succeeds(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post("/buyer-interests", json=interest_payload(buyer.id), headers=auth_headers(buyer))
    assert resp.status_code == 200


def test_create_buyer_interest_non_owner_403(client, db_session):
    buyer = make_user(db_session, "1")
    other = make_user(db_session, "2")
    resp = client.post("/buyer-interests", json=interest_payload(buyer.id), headers=auth_headers(other))
    assert resp.status_code == 403


def test_create_buyer_interest_unauthenticated_401(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post("/buyer-interests", json=interest_payload(buyer.id))
    assert resp.status_code == 401


def test_get_buyer_interests_scoped_to_own(client, db_session):
    buyer1 = make_user(db_session, "1")
    buyer2 = make_user(db_session, "2")
    make_interest(db_session, buyer1)
    make_interest(db_session, buyer2)

    resp = client.get("/buyer-interests", headers=auth_headers(buyer1))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["buyer_id"] == buyer1.id


def test_get_buyer_interests_admin_sees_all(client, db_session):
    buyer1 = make_user(db_session, "1")
    buyer2 = make_user(db_session, "2")
    admin = make_user(db_session, "3", account_type="admin")
    make_interest(db_session, buyer1)
    make_interest(db_session, buyer2)

    resp = client.get("/buyer-interests", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_buyer_interest_by_id_owner_succeeds(client, db_session):
    buyer = make_user(db_session, "1")
    interest = make_interest(db_session, buyer)
    resp = client.get(f"/buyer-interests/{interest.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200


def test_get_buyer_interest_by_id_non_owner_403(client, db_session):
    buyer = make_user(db_session, "1")
    other = make_user(db_session, "2")
    interest = make_interest(db_session, buyer)
    resp = client.get(f"/buyer-interests/{interest.id}", headers=auth_headers(other))
    assert resp.status_code == 403


def test_find_matches_owner_succeeds(client, db_session):
    buyer = make_user(db_session, "1")
    interest = make_interest(db_session, buyer)
    resp = client.get(f"/buyer-interests/{interest.id}/matches", headers=auth_headers(buyer))
    assert resp.status_code == 200


def test_find_matches_non_owner_403(client, db_session):
    buyer = make_user(db_session, "1")
    other = make_user(db_session, "2")
    interest = make_interest(db_session, buyer)
    resp = client.get(f"/buyer-interests/{interest.id}/matches", headers=auth_headers(other))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# KYC status - PUT /users/{id}/kyc-status
# (found during the M20 audit: this endpoint had zero authorization check
# at all - any authenticated user could mark any user's KYC verified,
# bypassing assess_compliance()'s first hard gate. Admin-gated the same
# way verify_ownership and create_compliance_rule were.)
# ---------------------------------------------------------------------------

def test_update_kyc_status_admin_succeeds(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    resp = client.put(
        f"/users/{buyer.id}/kyc-status", params={"status": "verified"}, headers=auth_headers(admin)
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["kyc_status"] == "verified"


def test_update_kyc_status_participant_403(client, db_session):
    buyer = make_user(db_session, "1")
    participant = make_user(db_session, "2")
    resp = client.put(
        f"/users/{buyer.id}/kyc-status", params={"status": "verified"}, headers=auth_headers(participant)
    )
    assert resp.status_code == 403


def test_update_kyc_status_cannot_self_verify(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.put(
        f"/users/{buyer.id}/kyc-status", params={"status": "verified"}, headers=auth_headers(buyer)
    )
    assert resp.status_code == 403


def test_update_kyc_status_unauthenticated_401(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.put(f"/users/{buyer.id}/kyc-status", params={"status": "verified"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Investor eligibility - POST /investor-eligibility
# ---------------------------------------------------------------------------

def test_create_investor_eligibility_self_pending_succeeds(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post(
        "/investor-eligibility", json=eligibility_payload(buyer.id, status="pending"), headers=auth_headers(buyer)
    )
    assert resp.status_code == 200


def test_create_investor_eligibility_self_cannot_submit_verified_403(client, db_session):
    buyer = make_user(db_session, "1")
    resp = client.post(
        "/investor-eligibility", json=eligibility_payload(buyer.id, status="verified"), headers=auth_headers(buyer)
    )
    assert resp.status_code == 403


def test_create_investor_eligibility_admin_can_submit_verified(client, db_session):
    buyer = make_user(db_session, "1")
    admin = make_user(db_session, "2", account_type="admin")
    resp = client.post(
        "/investor-eligibility", json=eligibility_payload(buyer.id, status="verified"), headers=auth_headers(admin)
    )
    assert resp.status_code == 200


def test_create_investor_eligibility_cannot_submit_for_another_user_403(client, db_session):
    buyer = make_user(db_session, "1")
    other = make_user(db_session, "2")
    resp = client.post(
        "/investor-eligibility", json=eligibility_payload(buyer.id, status="pending"), headers=auth_headers(other)
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Compliance rules - POST /compliance-rules
# ---------------------------------------------------------------------------

def test_create_compliance_rule_admin_succeeds(client, db_session):
    admin = make_user(db_session, "1", account_type="admin")
    resp = client.post("/compliance-rules", json=compliance_rule_payload(), headers=auth_headers(admin))
    assert resp.status_code == 200


def test_create_compliance_rule_participant_403(client, db_session):
    participant = make_user(db_session, "1")
    resp = client.post("/compliance-rules", json=compliance_rule_payload(), headers=auth_headers(participant))
    assert resp.status_code == 403


def test_create_compliance_rule_unauthenticated_401(client, db_session):
    resp = client.post("/compliance-rules", json=compliance_rule_payload())
    assert resp.status_code == 401
