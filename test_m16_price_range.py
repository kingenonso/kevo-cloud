"""
Tests for M16's general indicative price-range engine (admin-approved,
built 2026-10-22 per kevo-batch-b-full-gap-closure-plan.md Group
4): GET /price-range.

Design: build_price_range(company, asset_type, db) reports the real,
observed range of completed-transaction prices, current seller asking
prices, and current buyer maximum stated prices - never an interpolated
or predictive single-point estimate. Each of the three is independently
gated by MIN_DISTINCT_BUYERS (reused from the Demand Heatmap); completed
transactions additionally require at least 2 distinct buyer/seller pairs
to avoid the exact degenerate-duplicate-data problem the 2026-09-12
data-sufficiency audit found for real. Written against the real ~/KEVO
implementation, same fixture pattern as test_m16b.py.
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

from models import Base, User as UserModel, Listing as ListingModel, BuyerInterest, Transaction
from app import app, get_db, MIN_DISTINCT_BUYERS


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


def make_buyer(db_session, n):
    buyer = UserModel(name="Buyer " + str(n), email="pbuyer" + str(n) + "@example.com", role="buyer")
    db_session.add(buyer)
    db_session.commit()
    return buyer


def make_seller(db_session, n):
    seller = UserModel(name="Seller " + str(n), email="pseller" + str(n) + "@example.com", role="seller")
    db_session.add(seller)
    db_session.commit()
    return seller


def make_interest(db_session, buyer, company="Test Co", asset_type="Private Shares",
                   desired_quantity=100, maximum_price=10, status="active"):
    interest = BuyerInterest(
        buyer_id=buyer.id, company=company, asset_type=asset_type,
        desired_quantity=desired_quantity, maximum_price=maximum_price, status=status
    )
    db_session.add(interest)
    db_session.commit()
    return interest


def make_listing(db_session, seller, company="Test Co", asset_type="Private Shares",
                  quantity=100, asking_price=10, is_transferable=True):
    listing = ListingModel(
        seller_id=seller.id, company=company, asset_type=asset_type,
        quantity=quantity, asking_price=asking_price, is_transferable=is_transferable
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)
    return listing


def make_completed_transaction(db_session, listing, buyer, seller, agreed_price=10):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=seller.id,
        quantity=10, agreed_price=agreed_price, status="completed",
    )
    db_session.add(txn)
    db_session.commit()
    return txn


# --- Insufficient data across the board ---

def test_insufficient_data_when_nothing_exists(client, db_session):
    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "insufficient_data"


def test_price_range_is_unauthenticated(client, db_session):
    """Matches the other 3 anonymized aggregate endpoints - no login required."""
    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})
    assert resp.status_code == 200


# --- Completed-transaction range ---

def _add_qualifying_demand(db_session, company="Test Co", asset_type="Private Shares"):
    """Adds just enough active buyer interest to make current_demand_range
    populate on its own, so a test can isolate a different sub-range's
    gating without tripping the blanket insufficient_data short-circuit."""
    for i in range(100, 100 + MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer, company=company, asset_type=asset_type, maximum_price=10 + i)


def test_observed_price_range_requires_min_distinct_buyers_sample_size(client, db_session):
    seller = make_seller(db_session, 1)
    listing = make_listing(db_session, seller)
    for i in range(MIN_DISTINCT_BUYERS - 1):
        buyer = make_buyer(db_session, i)
        make_completed_transaction(db_session, listing, buyer, seller, agreed_price=10 + i)
    _add_qualifying_demand(db_session)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["status"] == "ok"
    assert body["observed_price_range"] is None


def test_observed_price_range_rejects_degenerate_single_pair_duplicate(client, db_session):
    """
    The exact real-world problem the 2026-09-12 data-sufficiency audit
    found: enough rows to clear a raw count threshold, but all from the
    same buyer/seller pair duplicated - not independent data points.
    """
    seller = make_seller(db_session, 1)
    buyer = make_buyer(db_session, 1)
    listing = make_listing(db_session, seller)
    for _ in range(MIN_DISTINCT_BUYERS + 2):
        make_completed_transaction(db_session, listing, buyer, seller, agreed_price=25000)
    _add_qualifying_demand(db_session)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["status"] == "ok"
    assert body["observed_price_range"] is None


def test_observed_price_range_appears_with_enough_independent_transactions(client, db_session):
    seller1 = make_seller(db_session, 1)
    seller2 = make_seller(db_session, 2)
    listing1 = make_listing(db_session, seller1)
    listing2 = make_listing(db_session, seller2)
    prices = []
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        seller = seller1 if i % 2 == 0 else seller2
        listing = listing1 if i % 2 == 0 else listing2
        price = 10 + i
        prices.append(price)
        make_completed_transaction(db_session, listing, buyer, seller, agreed_price=price)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["status"] == "ok"
    assert body["observed_price_range"]["low"] == min(prices)
    assert body["observed_price_range"]["high"] == max(prices)
    assert body["observed_price_range"]["sample_size"] == MIN_DISTINCT_BUYERS


def test_observed_price_range_only_counts_completed_transactions(client, db_session):
    seller1 = make_seller(db_session, 1)
    seller2 = make_seller(db_session, 2)
    listing1 = make_listing(db_session, seller1)
    listing2 = make_listing(db_session, seller2)
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        seller = seller1 if i % 2 == 0 else seller2
        listing = listing1 if i % 2 == 0 else listing2
        make_completed_transaction(db_session, listing, buyer, seller, agreed_price=10 + i)

    pending_buyer = make_buyer(db_session, "pending")
    pending_txn = Transaction(
        listing_id=listing1.id, buyer_id=pending_buyer.id, seller_id=seller1.id,
        quantity=5, agreed_price=999, status="accepted",
    )
    db_session.add(pending_txn)
    db_session.commit()

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    assert 999 not in [resp.json()["observed_price_range"]["low"], resp.json()["observed_price_range"]["high"]]


# --- Current ask range ---

def test_current_ask_range_requires_min_distinct_sellers(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS - 1):
        seller = make_seller(db_session, i)
        make_listing(db_session, seller, asking_price=10 + i)
    _add_qualifying_demand(db_session)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["status"] == "ok"
    assert body["current_ask_range"] is None


def test_current_ask_range_appears_with_enough_sellers(client, db_session):
    asks = []
    for i in range(MIN_DISTINCT_BUYERS):
        seller = make_seller(db_session, i)
        ask = 10 + i
        asks.append(ask)
        make_listing(db_session, seller, asking_price=ask)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["current_ask_range"]["low"] == min(asks)
    assert body["current_ask_range"]["high"] == max(asks)
    assert body["current_ask_range"]["distinct_seller_count"] == MIN_DISTINCT_BUYERS


def test_current_ask_range_ignores_non_transferable_listings(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS):
        seller = make_seller(db_session, i)
        make_listing(db_session, seller, asking_price=10 + i, is_transferable=False)
    _add_qualifying_demand(db_session)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["status"] == "ok"
    assert body["current_ask_range"] is None


# --- Current demand range ---

def _add_qualifying_asks(db_session, company="Test Co", asset_type="Private Shares"):
    """Adds just enough active, transferable listings to make
    current_ask_range populate on its own, so a test can isolate a
    different sub-range's gating."""
    for i in range(200, 200 + MIN_DISTINCT_BUYERS):
        seller = make_seller(db_session, i)
        make_listing(db_session, seller, company=company, asset_type=asset_type, asking_price=10 + i)


def test_current_demand_range_requires_min_distinct_buyers(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS - 1):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer, maximum_price=10 + i)
    _add_qualifying_asks(db_session)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["status"] == "ok"
    assert body["current_demand_range"] is None


def test_current_demand_range_appears_with_enough_buyers(client, db_session):
    max_prices = []
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        price = 10 + i
        max_prices.append(price)
        make_interest(db_session, buyer, maximum_price=price)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["current_demand_range"]["low"] == min(max_prices)
    assert body["current_demand_range"]["high"] == max(max_prices)
    assert body["current_demand_range"]["distinct_buyer_count"] == MIN_DISTINCT_BUYERS


def test_current_demand_range_ignores_withdrawn_interest(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer, maximum_price=10 + i, status="withdrawn")
    _add_qualifying_asks(db_session)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert body["status"] == "ok"
    assert body["current_demand_range"] is None


# --- Response shape / disclaimer ---

def test_response_includes_disclaimer_when_ok(client, db_session):
    max_prices = []
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer, maximum_price=10 + i)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    body = resp.json()
    assert "commitment" in body["disclaimer"] and "transact" in body["disclaimer"]
    assert "not investment advice" in body["disclaimer"]


def test_different_company_is_scoped_separately(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer, company="Other Co", maximum_price=10 + i)

    resp = client.get("/price-range", params={"company": "Test Co", "asset_type": "Private Shares"})

    assert resp.json()["status"] == "insufficient_data"
