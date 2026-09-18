"""
Tests for the M7 missing transaction-retrieval endpoints (2026-09-11) -
fifth of six M1-M12 findings from the re-verification audit. Written
against the REAL ~/KEVO implementation.

Finding: no GET /transactions or GET /transactions/{id} existed anywhere
in the real app, confirmed by grep before building anything.

Fix: added both, mirroring existing conventions exactly - GET /transactions
returns a bare list like GET /listings; GET /transactions/{id} returns the
same {"transaction": {...}} wrapper shape already used by POST /transactions
and PATCH /transactions/{id}/status (including not calling float() on
agreed_price, matching those two).
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

from models import Base, User as UserModel, Listing as ListingModel, Transaction
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
        name="Auth User",
        email=f"authuser{id(object())}@example.com",
        role="seller",
        account_type="admin",
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def make_seller(db, suffix="1"):
    seller = UserModel(name="Seller", email=f"seller{suffix}@example.com", role="seller")
    db.add(seller)
    db.commit()
    db.refresh(seller)
    return seller


def make_buyer(db, suffix="1"):
    buyer = UserModel(name="Buyer", email=f"buyer{suffix}@example.com", role="buyer")
    db.add(buyer)
    db.commit()
    db.refresh(buyer)
    return buyer


def make_listing(db, seller, quantity=1000):
    listing = ListingModel(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=quantity, asking_price=50.0, is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_transaction(db, listing, buyer, quantity, status="interested", agreed_price=10.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


# --- GET /transactions (list) ---

def test_get_transactions_returns_empty_list_when_none_exist(client, db_session):
    resp = client.get("/transactions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_transactions_returns_all_transactions(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    txn1 = make_transaction(db_session, listing, buyer, 100, status="interested")
    txn2 = make_transaction(db_session, listing, buyer, 200, status="accepted")

    resp = client.get("/transactions")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    ids = {t["id"] for t in body}
    assert ids == {txn1.id, txn2.id}


def test_get_transactions_returns_correct_fields(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, 150, status="accepted", agreed_price=25.0)

    resp = client.get("/transactions")
    body = resp.json()[0]
    assert body["id"] == txn.id
    assert body["listing_id"] == listing.id
    assert body["buyer_id"] == buyer.id
    assert body["seller_id"] == seller.id
    assert body["quantity"] == 150
    assert float(body["agreed_price"]) == 25.0
    assert body["status"] == "accepted"


def test_get_transactions_spans_multiple_listings(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing1 = make_listing(db_session, seller)
    listing2 = make_listing(db_session, seller)
    make_transaction(db_session, listing1, buyer, 100)
    make_transaction(db_session, listing2, buyer, 200)

    resp = client.get("/transactions")
    assert len(resp.json()) == 2


# --- GET /transactions/{id} (single) ---

def test_get_transaction_by_id_returns_correct_transaction(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, 300, status="settlement_pending", agreed_price=40.0)

    resp = client.get(f"/transactions/{txn.id}")
    assert resp.status_code == 200
    body = resp.json()["transaction"]
    assert body["id"] == txn.id
    assert body["listing_id"] == listing.id
    assert body["buyer_id"] == buyer.id
    assert body["seller_id"] == seller.id
    assert body["quantity"] == 300
    assert float(body["agreed_price"]) == 40.0
    assert body["status"] == "settlement_pending"


def test_get_transaction_by_id_404_for_unknown_id(client, db_session):
    resp = client.get("/transactions/999999")
    assert resp.status_code == 404


def test_get_transaction_by_id_reflects_status_after_patch(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, 100, status="interested")

    patch_resp = client.patch(f"/transactions/{txn.id}/status", params={"status": "accepted"})
    assert patch_resp.status_code == 200

    resp = client.get(f"/transactions/{txn.id}")
    assert resp.json()["transaction"]["status"] == "accepted"
