"""
Tests for the Batch B accountability extension (2026-09-24) on top of
Seller Financing: when a buyer stops paying, the seller (or admin) can
mark the agreement "defaulted". KEVO never decides default on its own via
an invented threshold -- the seller/admin decides, matching what their
own note actually says. The real consequence lands on the buyer's own
KEVO account (blocked from creating new buyer interests or transactions)
rather than a report compiled for other companies to use -- deliberately
avoiding FCRA "consumer reporting agency" exposure while still giving the
seller real teeth. Only an admin can lift the block, mirroring every
other "only an admin can attest this is resolved" gate in the app.
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
    SellerFinancingAgreement, SellerFinancingPayment,
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
        email=f"sfduser{suffix}-{id(object())}@example.com",
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


def make_transaction(db, listing, buyer, quantity=100, status="accepted", agreed_price=10.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_agreement(client, seller, txn, **overrides):
    payload = {
        "transaction_id": txn.id, "principal_amount": 1200.0, "annual_interest_rate_pct": 0,
        "term_months": 12, "payment_frequency": "monthly", "first_payment_due_date": "2026-10-01",
    }
    payload.update(overrides)
    resp = client.post("/seller-financing-agreements", headers=auth_headers(seller), json=payload)
    assert resp.status_code == 200
    return resp.json()


# --- PUT .../default ---

def test_seller_can_mark_defaulted(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn)

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/default",
        headers=auth_headers(seller), params={"reason": "Missed 3 consecutive payments"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "defaulted"
    assert body["default_reason"] == "Missed 3 consecutive payments"
    assert body["defaulted_at"] is not None


def test_admin_can_mark_defaulted(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn)

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/default",
        headers=auth_headers(admin), params={"reason": "Confirmed nonpayment"}
    )
    assert resp.status_code == 200


def test_buyer_cannot_mark_defaulted_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn)

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/default",
        headers=auth_headers(buyer), params={"reason": "trying to self-report"}
    )
    assert resp.status_code == 403


def test_cannot_default_an_already_completed_agreement(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn, term_months=1, principal_amount=100.0)
    payments = client.get(f"/seller-financing-agreements/{agreement['id']}/payments", headers=auth_headers(seller)).json()
    client.put(f"/seller-financing-agreements/{agreement['id']}/payments/{payments[0]['id']}/confirm", headers=auth_headers(seller))

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/default",
        headers=auth_headers(seller), params={"reason": "too late, already paid off"}
    )
    assert resp.status_code == 400


def test_default_unauthenticated_401(client, db_session):
    resp = client.put("/seller-financing-agreements/1/default", params={"reason": "x"})
    assert resp.status_code == 401


# --- The actual accountability mechanism ---

def test_defaulted_buyer_cannot_create_new_buyer_interest(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn)
    client.put(f"/seller-financing-agreements/{agreement['id']}/default", headers=auth_headers(seller), params={"reason": "nonpayment"})

    resp = client.post(
        "/buyer-interests", headers=auth_headers(buyer),
        json={"buyer_id": buyer.id, "company": "Other Co", "asset_type": "Private Shares", "desired_quantity": 10, "maximum_price": 20.0}
    )
    assert resp.status_code == 403
    assert "restricted" in resp.json()["detail"].lower()


def test_defaulted_buyer_cannot_be_party_to_new_transaction(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn)
    client.put(f"/seller-financing-agreements/{agreement['id']}/default", headers=auth_headers(seller), params={"reason": "nonpayment"})

    other_listing = make_listing(db_session, seller)
    resp = client.post(
        "/transactions", headers=auth_headers(seller),
        json={"listing_id": other_listing.id, "buyer_id": buyer.id, "quantity": 10, "agreed_price": 100.0}
    )
    assert resp.status_code == 403
    assert "restricted" in resp.json()["detail"].lower()


def test_non_defaulted_buyer_unaffected(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    resp = client.post(
        "/buyer-interests", headers=auth_headers(buyer),
        json={"buyer_id": buyer.id, "company": "Other Co", "asset_type": "Private Shares", "desired_quantity": 10, "maximum_price": 20.0}
    )
    assert resp.status_code == 200


# --- PUT .../resolve-default ---

def test_admin_can_resolve_default_and_unblock_buyer(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn)
    client.put(f"/seller-financing-agreements/{agreement['id']}/default", headers=auth_headers(seller), params={"reason": "nonpayment"})

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/resolve-default",
        headers=auth_headers(admin), params={"resolution_notes": "Buyer caught up on all payments off-platform"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolution_notes"] == "Buyer caught up on all payments off-platform"
    assert body["resolved_at"] is not None

    unblocked_attempt = client.post(
        "/buyer-interests", headers=auth_headers(buyer),
        json={"buyer_id": buyer.id, "company": "Other Co", "asset_type": "Private Shares", "desired_quantity": 10, "maximum_price": 20.0}
    )
    assert unblocked_attempt.status_code == 200


def test_seller_cannot_resolve_default_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn)
    client.put(f"/seller-financing-agreements/{agreement['id']}/default", headers=auth_headers(seller), params={"reason": "nonpayment"})

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/resolve-default",
        headers=auth_headers(seller), params={"resolution_notes": "trying to self-resolve"}
    )
    assert resp.status_code == 403


def test_cannot_resolve_a_non_defaulted_agreement(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="accepted")
    agreement = make_agreement(client, seller, txn)

    resp = client.put(
        f"/seller-financing-agreements/{agreement['id']}/resolve-default",
        headers=auth_headers(admin), params={"resolution_notes": "nothing to resolve"}
    )
    assert resp.status_code == 400


def test_resolve_default_unauthenticated_401(client, db_session):
    resp = client.put("/seller-financing-agreements/1/resolve-default", params={"resolution_notes": "x"})
    assert resp.status_code == 401
