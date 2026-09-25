"""
Tests for M25's third and final sub-piece (2026-09-25): Structured
Secondary Auctions.

Written against the REAL ~/KEVO implementation.

A sealed-bid mechanism for a listing. Buyers submit their own freely-
chosen price and quantity - KEVO never computes, suggests, or ranks a
price. Each buyer can see only their own bid, never another buyer's
terms (sealed). The listing's seller privately reviews every bid and
manually accepts exactly one, which becomes a normal Transaction at
"accepted" status. No automated matching, ranking, or clearing-price
computation - the seller's own manual accept decision is what keeps
this a negotiation process rather than an automated exchange.

Endpoints:
  POST /listings/{listing_id}/auction-bids
  GET  /listings/{listing_id}/auction-bids
  PUT  /auction-bids/{bid_id}/accept
  PUT  /auction-bids/{bid_id}/reject
  PUT  /auction-bids/{bid_id}/withdraw
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
    SecondaryAuctionBid,
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
        email=f"m25auction{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
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


# --- POST /listings/{listing_id}/auction-bids ---

def test_create_404_for_unknown_listing(client, db_session):
    buyer = make_user(db_session, "1", role="buyer")
    resp = client.post("/listings/999999/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    assert resp.status_code == 404


def test_create_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller)
    resp = client.post(f"/listings/{listing.id}/auction-bids", json={
        "quantity": 100, "bid_price": 55.0,
    })
    assert resp.status_code == 401


def test_create_seller_cannot_bid_on_own_listing_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller)
    resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(seller), json={
        "quantity": 100, "bid_price": 55.0,
    })
    assert resp.status_code == 403


def test_create_buyer_bid_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0, "note": "Willing to close fast",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["listing_id"] == listing.id
    assert body["bidder_id"] == buyer.id
    assert body["status"] == "submitted"
    assert float(body["bid_price"]) == 55.0
    assert body["resulting_transaction_id"] is None


def test_create_non_positive_quantity_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 0, "bid_price": 55.0,
    })
    assert resp.status_code == 400


def test_create_non_positive_price_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 0,
    })
    assert resp.status_code == 400


# --- GET /listings/{listing_id}/auction-bids ---

def test_list_404_for_unknown_listing(client, db_session):
    buyer = make_user(db_session, "1", role="buyer")
    resp = client.get("/listings/999999/auction-bids", headers=auth_headers(buyer))
    assert resp.status_code == 404


def test_list_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller)
    resp = client.get(f"/listings/{listing.id}/auction-bids")
    assert resp.status_code == 401


def test_list_seller_sees_all_bids(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer1 = make_user(db_session, "2", role="buyer")
    buyer2 = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)

    client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer1), json={
        "quantity": 100, "bid_price": 55.0,
    })
    client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer2), json={
        "quantity": 50, "bid_price": 60.0,
    })

    resp = client.get(f"/listings/{listing.id}/auction-bids", headers=auth_headers(seller))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_buyer_sees_only_own_bid(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer1 = make_user(db_session, "2", role="buyer")
    buyer2 = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)

    client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer1), json={
        "quantity": 100, "bid_price": 55.0,
    })
    client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer2), json={
        "quantity": 50, "bid_price": 60.0,
    })

    resp = client.get(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer1))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["bidder_id"] == buyer1.id


def test_list_admin_sees_all_bids(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer1 = make_user(db_session, "2", role="buyer")
    buyer2 = make_user(db_session, "3", role="buyer")
    admin = make_user(db_session, "4", account_type="admin")
    listing = make_listing(db_session, seller)

    client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer1), json={
        "quantity": 100, "bid_price": 55.0,
    })
    client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer2), json={
        "quantity": 50, "bid_price": 60.0,
    })

    resp = client.get(f"/listings/{listing.id}/auction-bids", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# --- PUT /auction-bids/{bid_id}/accept ---

def test_accept_404_for_unknown_bid(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    resp = client.put("/auction-bids/999999/accept", headers=auth_headers(seller))
    assert resp.status_code == 404


def test_accept_non_seller_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]

    resp = client.put(f"/auction-bids/{bid_id}/accept", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_accept_creates_real_transaction(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]

    resp = client.put(f"/auction-bids/{bid_id}/accept", headers=auth_headers(seller))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["decided_by_user_id"] == seller.id
    assert body["decided_at"] is not None
    txn_id = body["resulting_transaction_id"]
    assert txn_id is not None

    txn = db_session.query(Transaction).filter(Transaction.id == txn_id).first()
    assert txn is not None
    assert txn.listing_id == listing.id
    assert txn.buyer_id == buyer.id
    assert txn.seller_id == seller.id
    assert txn.quantity == 100
    assert float(txn.agreed_price) == 55.0
    assert txn.status == "accepted"


def test_accept_already_decided_bid_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]
    client.put(f"/auction-bids/{bid_id}/accept", headers=auth_headers(seller))

    resp = client.put(f"/auction-bids/{bid_id}/accept", headers=auth_headers(seller))
    assert resp.status_code == 400


def test_accept_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]

    resp = client.put(f"/auction-bids/{bid_id}/accept", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["decided_by_user_id"] == admin.id


# --- PUT /auction-bids/{bid_id}/reject ---

def test_reject_non_seller_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]

    resp = client.put(f"/auction-bids/{bid_id}/reject", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_reject_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]

    resp = client.put(f"/auction-bids/{bid_id}/reject", headers=auth_headers(seller))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["decided_by_user_id"] == seller.id
    assert body["resulting_transaction_id"] is None


def test_reject_already_decided_bid_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]
    client.put(f"/auction-bids/{bid_id}/reject", headers=auth_headers(seller))

    resp = client.put(f"/auction-bids/{bid_id}/reject", headers=auth_headers(seller))
    assert resp.status_code == 400


# --- PUT /auction-bids/{bid_id}/withdraw ---

def test_withdraw_non_bidder_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]

    resp = client.put(f"/auction-bids/{bid_id}/withdraw", headers=auth_headers(seller))
    assert resp.status_code == 403


def test_withdraw_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]

    resp = client.put(f"/auction-bids/{bid_id}/withdraw", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["status"] == "withdrawn"


def test_withdraw_already_decided_bid_400(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    create_resp = client.post(f"/listings/{listing.id}/auction-bids", headers=auth_headers(buyer), json={
        "quantity": 100, "bid_price": 55.0,
    })
    bid_id = create_resp.json()["id"]
    client.put(f"/auction-bids/{bid_id}/withdraw", headers=auth_headers(buyer))

    resp = client.put(f"/auction-bids/{bid_id}/withdraw", headers=auth_headers(buyer))
    assert resp.status_code == 400
