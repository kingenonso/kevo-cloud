"""
Tests for the narrowed M16B (2026-09-11/12): the Aggregate Demand/Supply
Indicator. Written against the REAL ~/KEVO implementation.

Design: build_liquidity_aggregation(company, asset_type, db) returns pure
quantity arithmetic comparing aggregate active buyer demand to aggregate
active listed supply for one company+asset_type - no specific buyer or
seller ever identified, no allocation ever decided, nothing persisted.
Reuses the Demand Heatmap's own MIN_DISTINCT_BUYERS anonymization threshold,
applied symmetrically to both buyers and sellers.
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

from models import Base, User as UserModel, Listing as ListingModel, BuyerInterest
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
    buyer = UserModel(name="Buyer " + str(n), email="buyer" + str(n) + "@example.com", role="buyer")
    db_session.add(buyer)
    db_session.commit()
    return buyer


def make_seller(db_session, n):
    seller = UserModel(name="Seller " + str(n), email="seller" + str(n) + "@example.com", role="seller")
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
    return listing


def make_balanced_group(db_session, company="Test Co", asset_type="Private Shares",
                         n_buyers=5, n_sellers=5, per_buyer_qty=100, per_seller_qty=100):
    for i in range(n_buyers):
        buyer = make_buyer(db_session, "demand_" + str(i))
        make_interest(db_session, buyer, company=company, asset_type=asset_type, desired_quantity=per_buyer_qty)
    for i in range(n_sellers):
        seller = make_seller(db_session, "supply_" + str(i))
        make_listing(db_session, seller, company=company, asset_type=asset_type, quantity=per_seller_qty)


def test_insufficient_data_when_no_data_at_all(client, db_session):
    response = client.get("/liquidity-aggregation", params={"company": "Nobody Co", "asset_type": "Private Shares"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_data"
    assert "message" in body


def test_insufficient_data_when_sellers_below_threshold(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer)
    seller = make_seller(db_session, 1)
    make_listing(db_session, seller, quantity=1000)

    response = client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})
    body = response.json()
    assert body["status"] == "insufficient_data"


def test_insufficient_data_when_buyers_below_threshold(client, db_session):
    buyer = make_buyer(db_session, 1)
    make_interest(db_session, buyer, desired_quantity=1)
    for i in range(MIN_DISTINCT_BUYERS):
        seller = make_seller(db_session, i)
        make_listing(db_session, seller)

    response = client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})
    body = response.json()
    assert body["status"] == "insufficient_data"


def test_ok_with_supply_may_cover_demand(client, db_session):
    make_balanced_group(db_session, per_buyer_qty=100, per_seller_qty=100)
    response = client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})
    body = response.json()
    assert body["status"] == "ok"
    assert body["active_buyer_count"] == 5
    assert body["active_seller_count"] == 5
    assert body["total_desired_quantity"] == 500
    assert body["total_available_quantity"] == 500
    assert body["aggregate_status"] == "supply_may_cover_demand"
    assert "quantity comparison only" in body["reason"]


def test_ok_with_insufficient_supply(client, db_session):
    make_balanced_group(db_session, per_buyer_qty=1000, per_seller_qty=10)
    response = client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})
    body = response.json()
    assert body["status"] == "ok"
    assert body["aggregate_status"] == "insufficient_supply"
    assert body["total_desired_quantity"] == 5000
    assert body["total_available_quantity"] == 50


def test_non_transferable_listings_excluded_from_supply(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer, desired_quantity=1)
    for i in range(MIN_DISTINCT_BUYERS):
        seller = make_seller(db_session, i)
        make_listing(db_session, seller, quantity=1000, is_transferable=False)

    response = client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})
    body = response.json()
    assert body["status"] == "insufficient_data"


def test_inactive_buyer_interests_excluded_from_demand(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer, desired_quantity=1000, status="withdrawn")
    for i in range(MIN_DISTINCT_BUYERS):
        seller = make_seller(db_session, i)
        make_listing(db_session, seller)

    response = client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})
    body = response.json()
    assert body["status"] == "insufficient_data"


def test_multiple_interests_from_same_buyer_counted_once(client, db_session):
    for i in range(MIN_DISTINCT_BUYERS):
        buyer = make_buyer(db_session, i)
        make_interest(db_session, buyer, desired_quantity=10)
        make_interest(db_session, buyer, desired_quantity=20)
    for i in range(MIN_DISTINCT_BUYERS):
        seller = make_seller(db_session, i)
        make_listing(db_session, seller, quantity=1000)

    response = client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})
    body = response.json()
    assert body["status"] == "ok"
    assert body["active_buyer_count"] == MIN_DISTINCT_BUYERS
    assert body["total_desired_quantity"] == MIN_DISTINCT_BUYERS * 30


def test_different_company_asset_type_isolated(client, db_session):
    make_balanced_group(db_session, company="Company A", asset_type="Private Shares")
    response = client.get("/liquidity-aggregation", params={"company": "Company B", "asset_type": "Private Shares"})
    body = response.json()
    assert body["status"] == "insufficient_data"


def test_endpoint_does_not_persist_anything(client, db_session):
    make_balanced_group(db_session)
    buyer_interest_count_before = db_session.query(BuyerInterest).count()
    listing_count_before = db_session.query(ListingModel).count()

    client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})
    client.get("/liquidity-aggregation", params={"company": "Test Co", "asset_type": "Private Shares"})

    assert db_session.query(BuyerInterest).count() == buyer_interest_count_before
    assert db_session.query(ListingModel).count() == listing_count_before
