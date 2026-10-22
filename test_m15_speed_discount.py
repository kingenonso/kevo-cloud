"""
Tests for M15's Discount-for-Speed (POST/GET/withdraw
/speed-discount-offers, GET /time-to-sale-stats), 2026-10-22.

Two pieces under test, both read-only/data-capture:
  - SpeedDiscountOffer: a seller-stated willingness to accept a lower
    price for a faster sale. Pure data capture - nothing matches, ranks,
    or auto-applies it to any transaction's agreed_price.
  - GET /time-to-sale-stats: a platform-wide aggregate derived from real
    completed transactions (Transaction.created_at and
    SettlementRecord.funds_released_at), gated by a minimum sample size.

Written against the real ~/KEVO implementation, same fixture pattern as
test_liquidity_commitments.py / test_m26e_escrow_integration.py.
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base,
    User as UserModel,
    Listing as ListingModel,
    Transaction,
    SettlementRecord,
    SpeedDiscountOffer,
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


def make_user(db, suffix="1", role="seller", account_type="participant", kyc_status="verified"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"speeddiscount{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, company="Acme Inc", asset_type="Private Shares",
                  quantity=1000, asking_price=50.0):
    listing = ListingModel(
        seller_id=seller.id, company=company, asset_type=asset_type,
        quantity=quantity, asking_price=asking_price, is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_offer(db, listing, seller, max_discount_percent=5.0, floor_price=None,
               speed_window_days=14, status="active"):
    offer = SpeedDiscountOffer(
        listing_id=listing.id, seller_id=seller.id,
        max_discount_percent=max_discount_percent, floor_price=floor_price,
        speed_window_days=speed_window_days, status=status,
        created_at=datetime.utcnow(),
    )
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def make_completed_transaction(db, listing, buyer, created_at, funds_released_at,
                                agreed_price=45.0, quantity=100):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status="completed",
        created_at=created_at,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    record = SettlementRecord(
        transaction_id=txn.id, status="released",
        funds_received=True, shares_confirmed_transferable=True,
        funds_released=True, funds_released_at=funds_released_at,
    )
    db.add(record)
    db.commit()
    return txn, record


# --- POST /speed-discount-offers ---

def test_seller_can_create_offer_with_discount_percent(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller)

    response = client.post(
        "/speed-discount-offers",
        json={
            "listing_id": listing.id, "seller_id": seller.id,
            "max_discount_percent": 5.0, "speed_window_days": 14,
        },
        headers=auth_headers(seller),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["max_discount_percent"] == 5.0
    assert body["floor_price"] is None
    assert body["speed_window_days"] == 14
    assert body["status"] == "active"
    assert "disclaimer" in body


def test_seller_can_create_offer_with_floor_price(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller, asking_price=50.0)

    response = client.post(
        "/speed-discount-offers",
        json={
            "listing_id": listing.id, "seller_id": seller.id,
            "floor_price": 45.0, "speed_window_days": 30,
        },
        headers=auth_headers(seller),
    )

    assert response.status_code == 200
    assert response.json()["floor_price"] == 45.0


def test_create_offer_requires_at_least_one_of_discount_or_floor(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller)

    response = client.post(
        "/speed-discount-offers",
        json={"listing_id": listing.id, "seller_id": seller.id, "speed_window_days": 14},
        headers=auth_headers(seller),
    )

    assert response.status_code == 400
    assert "max_discount_percent or floor_price" in response.json()["detail"]


def test_create_offer_rejects_floor_price_above_asking_price(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller, asking_price=50.0)

    response = client.post(
        "/speed-discount-offers",
        json={
            "listing_id": listing.id, "seller_id": seller.id,
            "floor_price": 60.0, "speed_window_days": 14,
        },
        headers=auth_headers(seller),
    )

    assert response.status_code == 400
    assert "asking_price" in response.json()["detail"]


def test_cannot_create_offer_for_someone_elses_listing(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    other_seller = make_user(db_session, "2", role="seller")
    listing = make_listing(db_session, seller)

    response = client.post(
        "/speed-discount-offers",
        json={
            "listing_id": listing.id, "seller_id": other_seller.id,
            "max_discount_percent": 5.0, "speed_window_days": 14,
        },
        headers=auth_headers(other_seller),
    )

    assert response.status_code == 403
    assert "own listing" in response.json()["detail"]


def test_cannot_impersonate_another_seller_in_payload(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    attacker = make_user(db_session, "2", role="seller")
    listing = make_listing(db_session, seller)

    response = client.post(
        "/speed-discount-offers",
        json={
            "listing_id": listing.id, "seller_id": seller.id,
            "max_discount_percent": 5.0, "speed_window_days": 14,
        },
        headers=auth_headers(attacker),
    )

    assert response.status_code == 403
    assert "for yourself" in response.json()["detail"]


def test_create_offer_404_for_missing_listing(client, db_session):
    seller = make_user(db_session, "1", role="seller")

    response = client.post(
        "/speed-discount-offers",
        json={
            "listing_id": 999999, "seller_id": seller.id,
            "max_discount_percent": 5.0, "speed_window_days": 14,
        },
        headers=auth_headers(seller),
    )

    assert response.status_code == 404


# --- GET /speed-discount-offers ---

def test_anyone_can_view_active_offers_on_a_listing(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    make_offer(db_session, listing, seller)
    make_offer(db_session, listing, seller, status="withdrawn")

    response = client.get(
        f"/speed-discount-offers?listing_id={listing.id}",
        headers=auth_headers(buyer),
    )

    assert response.status_code == 200
    offers = response.json()
    assert len(offers) == 1
    assert offers[0]["status"] == "active"


def test_seller_sees_own_offers_across_statuses_without_listing_filter(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller)
    make_offer(db_session, listing, seller, status="active")
    make_offer(db_session, listing, seller, status="withdrawn")

    response = client.get("/speed-discount-offers", headers=auth_headers(seller))

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_single_offer_by_id(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller)
    offer = make_offer(db_session, listing, seller)

    response = client.get(f"/speed-discount-offers/{offer.id}", headers=auth_headers(seller))

    assert response.status_code == 200
    assert response.json()["id"] == offer.id


def test_get_offer_404_when_missing(client, db_session):
    seller = make_user(db_session, "1", role="seller")

    response = client.get("/speed-discount-offers/999999", headers=auth_headers(seller))

    assert response.status_code == 404


# --- PUT /speed-discount-offers/{id}/withdraw ---

def test_seller_can_withdraw_own_offer(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller)
    offer = make_offer(db_session, listing, seller)

    response = client.put(
        f"/speed-discount-offers/{offer.id}/withdraw", headers=auth_headers(seller)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "withdrawn"


def test_cannot_withdraw_someone_elses_offer(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    other = make_user(db_session, "2", role="seller")
    listing = make_listing(db_session, seller)
    offer = make_offer(db_session, listing, seller)

    response = client.put(
        f"/speed-discount-offers/{offer.id}/withdraw", headers=auth_headers(other)
    )

    assert response.status_code == 403


# --- GET /time-to-sale-stats ---

def test_time_to_sale_insufficient_data_below_threshold(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    now = datetime.utcnow()
    for _ in range(3):
        make_completed_transaction(db_session, listing, buyer, now - timedelta(days=10), now)

    response = client.get(
        "/time-to-sale-stats?company=Acme Inc&asset_type=Private Shares",
        headers=auth_headers(buyer),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_data"


def test_time_to_sale_computes_average_and_median_once_threshold_met(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    now = datetime.utcnow()
    # 5 completed transactions, each taking exactly 10 days.
    for _ in range(5):
        make_completed_transaction(db_session, listing, buyer, now - timedelta(days=10), now)

    response = client.get(
        "/time-to-sale-stats?company=Acme Inc&asset_type=Private Shares",
        headers=auth_headers(buyer),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["sample_size"] == 5
    assert body["average_days_to_sale"] == pytest.approx(10.0, abs=0.1)
    assert body["median_days_to_sale"] == pytest.approx(10.0, abs=0.1)


def test_time_to_sale_excludes_transactions_with_unknown_created_at(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    now = datetime.utcnow()
    for _ in range(5):
        make_completed_transaction(db_session, listing, buyer, now - timedelta(days=10), now)

    # Historical-style row with no honest creation time - must be excluded,
    # not backfilled with a fabricated timestamp.
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=50, agreed_price=40.0, status="completed", created_at=None,
    )
    db_session.add(txn)
    db_session.commit()
    db_session.refresh(txn)
    record = SettlementRecord(
        transaction_id=txn.id, status="released", funds_received=True,
        shares_confirmed_transferable=True, funds_released=True,
        funds_released_at=now,
    )
    db_session.add(record)
    db_session.commit()

    response = client.get(
        "/time-to-sale-stats?company=Acme Inc&asset_type=Private Shares",
        headers=auth_headers(buyer),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["sample_size"] == 5


def test_time_to_sale_excludes_incomplete_transactions(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)

    now = datetime.utcnow()
    for _ in range(5):
        make_completed_transaction(db_session, listing, buyer, now - timedelta(days=10), now)

    # Not yet completed - must not count toward the stat.
    pending_txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=10, agreed_price=40.0, status="accepted",
        created_at=now - timedelta(days=2),
    )
    db_session.add(pending_txn)
    db_session.commit()

    response = client.get(
        "/time-to-sale-stats?company=Acme Inc&asset_type=Private Shares",
        headers=auth_headers(buyer),
    )

    assert response.json()["sample_size"] == 5


def test_time_to_sale_scoped_by_company_and_asset_type(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing_a = make_listing(db_session, seller, company="Acme Inc", asset_type="Private Shares")
    listing_b = make_listing(db_session, seller, company="Other Co", asset_type="Private Shares")

    now = datetime.utcnow()
    for _ in range(5):
        make_completed_transaction(db_session, listing_a, buyer, now - timedelta(days=10), now)
    for _ in range(5):
        make_completed_transaction(db_session, listing_b, buyer, now - timedelta(days=3), now)

    response = client.get(
        "/time-to-sale-stats?company=Acme Inc&asset_type=Private Shares",
        headers=auth_headers(buyer),
    )

    body = response.json()
    assert body["sample_size"] == 5
    assert body["average_days_to_sale"] == pytest.approx(10.0, abs=0.1)
