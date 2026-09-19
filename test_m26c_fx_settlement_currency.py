"""
Tests for M26C's first slice (2026-09-19): Cross-Currency/FX Settlement
Handling, "sidestep" scope.

Dedicated research found the closest real precedent (EquityZen) avoids FX
risk entirely by settling every transaction in a single currency and
letting each non-USD party's own bank handle conversion, outside the
platform. This slice makes that already-implicit assumption explicit: a
new Transaction.settlement_currency column, fixed at "USD" for every
transaction regardless of listing/buyer/seller jurisdiction. No live FX
quoting, rate-locking, or conversion execution of any kind.
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
        email=f"m26cuser{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, quantity=1000, issuer_jurisdiction="South Africa"):
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=quantity, asking_price=50.0, is_transferable=True,
        issuer_jurisdiction=issuer_jurisdiction,
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


# --- POST /transactions ---

def test_create_transaction_always_sets_usd(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller, issuer_jurisdiction="Singapore")

    resp = client.post(
        "/transactions", headers=auth_headers(buyer),
        json={"listing_id": listing.id, "buyer_id": buyer.id, "quantity": 50, "agreed_price": 25.0},
    )
    assert resp.status_code == 200
    assert resp.json()["transaction"]["settlement_currency"] == "USD"


def test_create_transaction_usd_regardless_of_jurisdiction(client, db_session):
    # A non-USD jurisdiction (South Africa) still settles in USD - the whole
    # point of the sidestep design is that it's fixed, not derived.
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller, issuer_jurisdiction="South Africa")

    resp = client.post(
        "/transactions", headers=auth_headers(buyer),
        json={"listing_id": listing.id, "buyer_id": buyer.id, "quantity": 50, "agreed_price": 25.0},
    )
    assert resp.status_code == 200
    assert resp.json()["transaction"]["settlement_currency"] == "USD"


# --- DB-level default (no explicit value supplied) ---

def test_db_default_backfills_usd_without_explicit_value(db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    assert txn.settlement_currency == "USD"


# --- GET /transactions (list) ---

def test_list_includes_settlement_currency(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    make_transaction(db_session, listing, buyer)

    resp = client.get("/transactions", headers=auth_headers(seller))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["settlement_currency"] == "USD"


# --- GET /transactions/{id} ---

def test_get_by_id_includes_settlement_currency(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["transaction"]["settlement_currency"] == "USD"


# --- PATCH /transactions/{id}/status ---

def test_status_update_response_includes_settlement_currency_unchanged(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, status="interested")

    resp = client.patch(
        f"/transactions/{txn.id}/status", headers=auth_headers(seller),
        params={"status": "accepted"},
    )
    assert resp.status_code == 200
    body = resp.json()["transaction"]
    assert body["status"] == "accepted"
    assert body["settlement_currency"] == "USD"


# --- GET /deal-room/transaction/{id} ---

def test_deal_room_includes_settlement_currency(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/deal-room/transaction/{txn.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["transaction"]["settlement_currency"] == "USD"
