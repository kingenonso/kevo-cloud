"""
Tests for M31's first slice (2026-09-21): Smart Deal Alerts.

Reuses find_matches()'s exact same non-discretionary matching criteria
(company, asset_type, price, quantity) to automatically notify a buyer
when a brand-new listing matches one of their standing, active
BuyerInterest rows - so they do not have to keep re-checking manually.
Flat and chronological by design, never ranked or scored, matching
M11's own corrected no-scoring posture for the same Rule 3b-16
non-discretionary reasons.

Covers: alert creation on POST /listings (including all the ways a
listing can fail to match, and inactive interests being excluded),
and the three new endpoints - GET /deal-alerts, GET /deal-alerts/{id},
PUT /deal-alerts/{id}/mark-read - with the same owner-or-admin (read)
and owner-only (mark-read) authorization matrix used elsewhere.
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
    Base, User as UserModel, Listing as ListingModel, BuyerInterest,
    DealAlert,
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
        email=f"m31user{suffix}-{id(object())}@example.com",
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


def make_interest(db, buyer, company="Acme Inc", asset_type="Private Shares",
                   desired_quantity=50, maximum_price=100.0, status="active"):
    interest = BuyerInterest(
        buyer_id=buyer.id, company=company, asset_type=asset_type,
        desired_quantity=desired_quantity, maximum_price=maximum_price,
        status=status,
    )
    db.add(interest)
    db.commit()
    db.refresh(interest)
    return interest


def make_deal_alert(db, interest, listing, buyer, is_read=False):
    from datetime import datetime
    alert = DealAlert(
        buyer_interest_id=interest.id, listing_id=listing.id,
        buyer_id=buyer.id, is_read=is_read, created_at=datetime.utcnow(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


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


# --- Alert creation on POST /listings ---

def test_creating_matching_listing_creates_alert_for_active_interest(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    interest = make_interest(db_session, buyer)

    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200

    alerts = db_session.query(DealAlert).all()
    assert len(alerts) == 1
    assert alerts[0].buyer_interest_id == interest.id
    assert alerts[0].buyer_id == buyer.id
    assert alerts[0].is_read is False


def test_creating_listing_does_not_alert_on_company_mismatch(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    make_interest(db_session, buyer, company="Other Co")

    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200
    assert db_session.query(DealAlert).count() == 0


def test_creating_listing_does_not_alert_on_asset_type_mismatch(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    make_interest(db_session, buyer, asset_type="Common Stock")

    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200
    assert db_session.query(DealAlert).count() == 0


def test_creating_listing_does_not_alert_when_price_exceeds_buyer_max(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    make_interest(db_session, buyer, maximum_price=10.0)

    resp = client.post("/listings", json=listing_payload(seller.id, asking_price=50.0), headers=auth_headers(seller))
    assert resp.status_code == 200
    assert db_session.query(DealAlert).count() == 0


def test_creating_listing_does_not_alert_when_quantity_below_desired(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    make_interest(db_session, buyer, desired_quantity=5000)

    resp = client.post("/listings", json=listing_payload(seller.id, quantity=1000), headers=auth_headers(seller))
    assert resp.status_code == 200
    assert db_session.query(DealAlert).count() == 0


def test_creating_listing_does_not_alert_for_inactive_interest(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    make_interest(db_session, buyer, status="withdrawn")

    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200
    assert db_session.query(DealAlert).count() == 0


def test_creating_listing_alerts_every_matching_buyer_flat_no_ranking(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer1 = make_user(db_session, "buyer1", role="buyer")
    buyer2 = make_user(db_session, "buyer2", role="buyer")
    interest1 = make_interest(db_session, buyer1)
    interest2 = make_interest(db_session, buyer2)

    resp = client.post("/listings", json=listing_payload(seller.id), headers=auth_headers(seller))
    assert resp.status_code == 200

    alerts = db_session.query(DealAlert).all()
    assert len(alerts) == 2
    buyer_ids = {a.buyer_id for a in alerts}
    assert buyer_ids == {buyer1.id, buyer2.id}
    for a in alerts:
        assert not hasattr(a, "score")
        assert not hasattr(a, "rank")


# --- GET /deal-alerts (list) ---

def test_list_deal_alerts_returns_only_own_for_buyer(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer1 = make_user(db_session, "buyer1", role="buyer")
    buyer2 = make_user(db_session, "buyer2", role="buyer")
    listing = make_listing(db_session, seller)
    interest1 = make_interest(db_session, buyer1)
    interest2 = make_interest(db_session, buyer2)
    make_deal_alert(db_session, interest1, listing, buyer1)
    make_deal_alert(db_session, interest2, listing, buyer2)

    resp = client.get("/deal-alerts", headers=auth_headers(buyer1))
    assert resp.status_code == 200
    alerts = resp.json()["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["buyer_id"] == buyer1.id


def test_list_deal_alerts_admin_sees_all(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer1 = make_user(db_session, "buyer1", role="buyer")
    buyer2 = make_user(db_session, "buyer2", role="buyer")
    admin = make_user(db_session, "admin1", role="admin", account_type="admin")
    listing = make_listing(db_session, seller)
    interest1 = make_interest(db_session, buyer1)
    interest2 = make_interest(db_session, buyer2)
    make_deal_alert(db_session, interest1, listing, buyer1)
    make_deal_alert(db_session, interest2, listing, buyer2)

    resp = client.get("/deal-alerts", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()["alerts"]) == 2


def test_list_deal_alerts_empty_for_buyer_with_no_alerts(client, db_session):
    buyer = make_user(db_session, "buyer1", role="buyer")
    resp = client.get("/deal-alerts", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["alerts"] == []


# --- GET /deal-alerts/{id} ---

def test_get_deal_alert_owner_can_view(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    listing = make_listing(db_session, seller)
    interest = make_interest(db_session, buyer)
    alert = make_deal_alert(db_session, interest, listing, buyer)

    resp = client.get(f"/deal-alerts/{alert.id}", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["id"] == alert.id


def test_get_deal_alert_admin_can_view(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    admin = make_user(db_session, "admin1", role="admin", account_type="admin")
    listing = make_listing(db_session, seller)
    interest = make_interest(db_session, buyer)
    alert = make_deal_alert(db_session, interest, listing, buyer)

    resp = client.get(f"/deal-alerts/{alert.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_get_deal_alert_other_buyer_forbidden(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    other = make_user(db_session, "buyer2", role="buyer")
    listing = make_listing(db_session, seller)
    interest = make_interest(db_session, buyer)
    alert = make_deal_alert(db_session, interest, listing, buyer)

    resp = client.get(f"/deal-alerts/{alert.id}", headers=auth_headers(other))
    assert resp.status_code == 403


def test_get_deal_alert_not_found(client, db_session):
    buyer = make_user(db_session, "buyer1", role="buyer")
    resp = client.get("/deal-alerts/999999", headers=auth_headers(buyer))
    assert resp.status_code == 404


# --- PUT /deal-alerts/{id}/mark-read ---

def test_mark_read_owner_succeeds(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    listing = make_listing(db_session, seller)
    interest = make_interest(db_session, buyer)
    alert = make_deal_alert(db_session, interest, listing, buyer)

    resp = client.put(f"/deal-alerts/{alert.id}/mark-read", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True
    assert resp.json()["read_at"] is not None

    db_session.refresh(alert)
    assert alert.is_read is True
    assert alert.read_at is not None


def test_mark_read_other_buyer_forbidden(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    other = make_user(db_session, "buyer2", role="buyer")
    listing = make_listing(db_session, seller)
    interest = make_interest(db_session, buyer)
    alert = make_deal_alert(db_session, interest, listing, buyer)

    resp = client.put(f"/deal-alerts/{alert.id}/mark-read", headers=auth_headers(other))
    assert resp.status_code == 403
    db_session.refresh(alert)
    assert alert.is_read is False


def test_mark_read_admin_cannot_override_owner_only(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")
    buyer = make_user(db_session, "buyer1", role="buyer")
    admin = make_user(db_session, "admin1", role="admin", account_type="admin")
    listing = make_listing(db_session, seller)
    interest = make_interest(db_session, buyer)
    alert = make_deal_alert(db_session, interest, listing, buyer)

    resp = client.put(f"/deal-alerts/{alert.id}/mark-read", headers=auth_headers(admin))
    assert resp.status_code == 403


def test_mark_read_not_found(client, db_session):
    buyer = make_user(db_session, "buyer1", role="buyer")
    resp = client.put("/deal-alerts/999999/mark-read", headers=auth_headers(buyer))
    assert resp.status_code == 404
