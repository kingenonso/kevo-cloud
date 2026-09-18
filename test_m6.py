"""
Tests for the M6 transaction-oversell fix (2026-09-11) - fourth of six
M1-M12 findings from the re-verification audit. Written against the REAL
~/KEVO implementation.

Finding: POST /transactions only ever compared the new transaction's
quantity against the listing's static original quantity column, never
against quantity already committed by other transactions on that same
listing. A listing could be oversold.

Fix: sum quantity across existing transactions on the same listing with
status in ("accepted", "settlement_pending", "completed") - deliberately
excluding "interested" (mere inquiry, no agreement yet, per the M15
negotiation-status distinction), "rejected", and "cancelled" (dead ends) -
and reject the new transaction if quantity + that committed sum exceeds
the listing's quantity.
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
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


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


def make_transaction(db, listing, buyer, quantity, status):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=10.0, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def txn_payload(listing_id, buyer_id, quantity, agreed_price=10.0):
    return {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "quantity": quantity,
        "agreed_price": agreed_price,
    }


# --- Pre-existing validation still works (regression) ---

def test_create_transaction_succeeds_within_available_quantity(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller, quantity=1000)

    resp = client.post("/transactions", json=txn_payload(listing.id, buyer.id, 500), headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["transaction"]["status"] == "interested"


def test_create_transaction_fails_exceeding_listing_quantity_alone(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller, quantity=1000)

    resp = client.post("/transactions", json=txn_payload(listing.id, buyer.id, 1500), headers=auth_headers(buyer))
    assert resp.status_code == 400
    assert "quantity" in resp.json()["detail"].lower()


def test_create_transaction_404_listing_not_found(client, db_session):
    buyer = make_buyer(db_session)
    resp = client.post("/transactions", json=txn_payload(999999, buyer.id, 100), headers=auth_headers(buyer))
    assert resp.status_code == 404


def test_create_transaction_400_buyer_equals_seller(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller, quantity=1000)
    resp = client.post("/transactions", json=txn_payload(listing.id, seller.id, 100), headers=auth_headers(seller))
    assert resp.status_code == 400


def test_create_transaction_400_agreed_price_not_positive(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller, quantity=1000)
    resp = client.post("/transactions", json=txn_payload(listing.id, buyer.id, 100, agreed_price=0), headers=auth_headers(buyer))
    assert resp.status_code == 400


# --- The actual fix: committed quantity from other transactions now counts ---

def test_oversell_blocked_by_existing_accepted_transaction(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 800, "accepted")

    # 800 already accepted, only 200 left - this asks for 500, should fail
    resp = client.post("/transactions", json=txn_payload(listing.id, buyer2.id, 500), headers=auth_headers(buyer2))
    assert resp.status_code == 400
    assert "quantity" in resp.json()["detail"].lower()


def test_oversell_blocked_by_existing_settlement_pending_transaction(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 800, "settlement_pending")

    resp = client.post("/transactions", json=txn_payload(listing.id, buyer2.id, 500), headers=auth_headers(buyer2))
    assert resp.status_code == 400


def test_oversell_blocked_by_existing_completed_transaction(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 800, "completed")

    resp = client.post("/transactions", json=txn_payload(listing.id, buyer2.id, 500), headers=auth_headers(buyer2))
    assert resp.status_code == 400


def test_interested_transactions_do_not_count_against_quantity(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 900, "interested")

    # Another buyer expressing interest in 900 more should NOT be blocked -
    # nothing has actually been agreed yet
    resp = client.post("/transactions", json=txn_payload(listing.id, buyer2.id, 900), headers=auth_headers(buyer2))
    assert resp.status_code == 200


def test_rejected_transactions_do_not_count_against_quantity(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 900, "rejected")

    resp = client.post("/transactions", json=txn_payload(listing.id, buyer2.id, 900), headers=auth_headers(buyer2))
    assert resp.status_code == 200


def test_cancelled_transactions_do_not_count_against_quantity(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 900, "cancelled")

    resp = client.post("/transactions", json=txn_payload(listing.id, buyer2.id, 900), headers=auth_headers(buyer2))
    assert resp.status_code == 200


def test_multiple_committed_transactions_sum_correctly(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    buyer3 = make_buyer(db_session, "3")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 400, "accepted")
    make_transaction(db_session, listing, buyer2, 400, "settlement_pending")

    # 800 committed total, 200 left - this asks for 300, should fail
    resp = client.post("/transactions", json=txn_payload(listing.id, buyer3.id, 300), headers=auth_headers(buyer3))
    assert resp.status_code == 400


def test_transaction_exactly_filling_remaining_quantity_succeeds(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 800, "accepted")

    # exactly 200 left, asking for exactly 200 - should succeed (boundary)
    resp = client.post("/transactions", json=txn_payload(listing.id, buyer2.id, 200), headers=auth_headers(buyer2))
    assert resp.status_code == 200


def test_transaction_exceeding_remaining_by_one_unit_fails(client, db_session):
    seller = make_seller(db_session)
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    listing = make_listing(db_session, seller, quantity=1000)
    make_transaction(db_session, listing, buyer1, 800, "accepted")

    # only 200 left, asking for 201 - should fail (boundary)
    resp = client.post("/transactions", json=txn_payload(listing.id, buyer2.id, 201), headers=auth_headers(buyer2))
    assert resp.status_code == 400
