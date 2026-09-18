"""
Tests for the M17 first slice (2026-09-11): a transaction-scoped Liquidity
Roadmap. Written against the REAL ~/KEVO implementation.

Design: build_liquidity_path(listing, db, transaction_id=None) gained one
optional parameter. When omitted, behavior is byte-for-byte identical to
before (the listing's latest transaction is used) - GET /liquidity-path/listing/{id}
(M15) is unaffected. When given, the function uses that exact transaction
instead - the new GET /liquidity-path/transaction/{id} endpoint. This matters
for real data: listing 2 in the real database already has 3 transactions,
so "latest transaction" and "this specific transaction" are not always the
same thing.
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
    OwnershipRecord, LiquidityPathStep,
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


def make_buyer(db, suffix="1", kyc_status="not_started", jurisdiction=None):
    buyer = UserModel(
        name="Buyer", email=f"buyer{suffix}@example.com", role="buyer",
        kyc_status=kyc_status, jurisdiction=jurisdiction,
    )
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


def make_transaction(db, listing, buyer, quantity=100, status="interested", agreed_price=10.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def step_by_type(result, step_type):
    return next(s for s in result["steps"] if s["step_type"] == step_type)


# --- Regression: M15's own endpoint is completely unaffected ---

def test_listing_endpoint_still_returns_nine_steps(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)

    resp = client.get(f"/liquidity-path/listing/{listing.id}")
    assert resp.status_code == 200
    assert len(resp.json()["steps"]) == 9


def test_listing_endpoint_still_persists_transaction_id_as_none(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    make_transaction(db_session, listing, buyer, status="accepted")

    resp = client.get(f"/liquidity-path/listing/{listing.id}")
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    rows = db_session.query(LiquidityPathStep).filter(LiquidityPathStep.run_id == run_id).all()
    assert len(rows) == 9
    assert all(r.transaction_id is None for r in rows)


def test_listing_endpoint_still_uses_latest_transaction_with_multiple_on_file(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller)
    make_transaction(db_session, listing, buyer1, status="rejected")
    newest = make_transaction(db_session, listing, buyer2, status="accepted")

    resp = client.get(f"/liquidity-path/listing/{listing.id}")
    negotiation = step_by_type(resp.json(), "NEGOTIATION_PRICE_AGREEMENT")
    # The listing endpoint should reflect the NEWEST transaction (accepted -> complete)
    assert negotiation["complete"] is True
    assert str(newest.id) in negotiation["reasons"]


# --- New: GET /liquidity-path/transaction/{id} ---

def test_transaction_endpoint_404_for_unknown_transaction(client, db_session):
    resp = client.get("/liquidity-path/transaction/999999")
    assert resp.status_code == 404


def test_transaction_endpoint_returns_nine_steps(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/liquidity-path/transaction/{txn.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["steps"]) == 9
    assert body["transaction_id"] == txn.id
    assert body["listing_id"] == listing.id


def test_transaction_endpoint_persists_real_transaction_id_on_rows(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/liquidity-path/transaction/{txn.id}")
    run_id = resp.json()["run_id"]

    rows = db_session.query(LiquidityPathStep).filter(LiquidityPathStep.run_id == run_id).all()
    assert len(rows) == 9
    assert all(r.transaction_id == txn.id for r in rows)


# --- The core fix: an older transaction on a multi-transaction listing gets ITS OWN data ---

def test_transaction_endpoint_uses_the_specific_requested_transaction_not_the_latest(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller)

    older_rejected = make_transaction(db_session, listing, buyer1, status="rejected")
    newer_accepted = make_transaction(db_session, listing, buyer2, status="accepted")

    # Asking for the OLDER (rejected) transaction's passport must reflect
    # ITS status, not the newer accepted one's.
    resp_older = client.get(f"/liquidity-path/transaction/{older_rejected.id}")
    negotiation_older = step_by_type(resp_older.json(), "NEGOTIATION_PRICE_AGREEMENT")
    assert negotiation_older["complete"] is False
    assert str(older_rejected.id) in negotiation_older["reasons"]

    # Asking for the NEWER (accepted) transaction's passport must reflect ITS status.
    resp_newer = client.get(f"/liquidity-path/transaction/{newer_accepted.id}")
    negotiation_newer = step_by_type(resp_newer.json(), "NEGOTIATION_PRICE_AGREEMENT")
    assert negotiation_newer["complete"] is True
    assert str(newer_accepted.id) in negotiation_newer["reasons"]


def test_transaction_endpoint_buyer_eligibility_uses_the_specific_requested_transactions_buyer(client, db_session):
    seller = make_seller(db_session)
    # buyer1: fails compliance (kyc not verified). buyer2: kyc verified, no rules seeded -> "review"/cannot_determine, not blocked
    buyer1 = make_buyer(db_session, "1", kyc_status="not_started", jurisdiction="Canada")
    buyer2 = make_buyer(db_session, "2", kyc_status="verified", jurisdiction="New Zealand")
    listing = make_listing(db_session, seller)
    listing.issuer_jurisdiction = "Canada"
    db_session.commit()

    txn1 = make_transaction(db_session, listing, buyer1)
    listing.issuer_jurisdiction = "New Zealand"
    db_session.commit()
    txn2 = make_transaction(db_session, listing, buyer2)

    resp1 = client.get(f"/liquidity-path/transaction/{txn1.id}")
    eligibility1 = step_by_type(resp1.json(), "BUYER_ELIGIBILITY_COMPLIANCE")
    assert str(buyer1.id) in eligibility1["reasons"]

    resp2 = client.get(f"/liquidity-path/transaction/{txn2.id}")
    eligibility2 = step_by_type(resp2.json(), "BUYER_ELIGIBILITY_COMPLIANCE")
    assert str(buyer2.id) in eligibility2["reasons"]
    # Confirms each call evaluated its OWN transaction's buyer, not always the latest one
    assert eligibility1["reasons"] != eligibility2["reasons"]
