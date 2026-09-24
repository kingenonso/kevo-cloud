"""
Tests for the Transaction Cost Calculator (Batch B, group 3 item 9),
2026-09-24 - a pure arithmetic estimator: headline valuation minus every
user-entered friction cost equals estimated net proceeds. Deliberately
carries no hardcoded KEVO platform fee - see the endpoint's own docstring
in app.py for why. Written against the REAL ~/KEVO implementation.
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
    return TestClient(app)


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_user(db, suffix="1", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"costcalc{suffix}-{id(object())}@example.com",
        role="buyer",
        account_type=account_type,
        hashed_password=hash_password("originalpass123"),
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


def make_transaction(db, listing, buyer, quantity=100, status="completed", agreed_price=25000.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def test_estimate_with_real_transaction_auto_derives_valuation(client, db_session):
    seller = make_user(db_session, "seller1")
    buyer = make_user(db_session, "buyer1")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, quantity=100, agreed_price=25000.0)

    resp = client.post(
        "/transaction-cost-estimate",
        json={"transaction_id": txn.id},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["headline_valuation"] == 100 * 25000.0
    assert data["total_friction"] == 0
    assert data["net_proceeds"] == data["headline_valuation"]
    assert data["currency"] == "USD"


def test_estimate_with_real_transaction_and_explicit_valuation_override(client, db_session):
    seller = make_user(db_session, "seller2")
    buyer = make_user(db_session, "buyer2")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, quantity=100, agreed_price=25000.0)

    resp = client.post(
        "/transaction-cost-estimate",
        json={"transaction_id": txn.id, "headline_valuation": 5000000},
        headers=auth_headers(seller),
    )
    assert resp.status_code == 200
    assert resp.json()["headline_valuation"] == 5000000


def test_fee_breakdown_arithmetic_is_correct(client, db_session):
    seller = make_user(db_session, "seller3")
    buyer = make_user(db_session, "buyer3")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer, quantity=10, agreed_price=1000.0)

    resp = client.post(
        "/transaction-cost-estimate",
        json={
            "transaction_id": txn.id,
            "legal_fee": 100,
            "platform_fee": 50,
            "settlement_fee": 25,
            "custody_fee": 10,
            "fx_fee": 5,
            "transfer_fee": 2,
            "taxes_other": 200,
        },
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["headline_valuation"] == 10000.0
    assert data["total_friction"] == 392
    assert data["net_proceeds"] == 10000.0 - 392


def test_non_party_non_admin_gets_403(client, db_session):
    seller = make_user(db_session, "seller4")
    buyer = make_user(db_session, "buyer4")
    stranger = make_user(db_session, "stranger4")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(
        "/transaction-cost-estimate",
        json={"transaction_id": txn.id},
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 403


def test_admin_can_estimate_any_transaction(client, db_session):
    seller = make_user(db_session, "seller5")
    buyer = make_user(db_session, "buyer5")
    admin = make_user(db_session, "admin5", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.post(
        "/transaction-cost-estimate",
        json={"transaction_id": txn.id},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200


def test_transaction_not_found_404(client, db_session):
    user = make_user(db_session, "user6")
    resp = client.post(
        "/transaction-cost-estimate",
        json={"transaction_id": 999999},
        headers=auth_headers(user),
    )
    assert resp.status_code == 404


def test_adhoc_estimate_without_transaction_id(client, db_session):
    user = make_user(db_session, "user7")
    resp = client.post(
        "/transaction-cost-estimate",
        json={"headline_valuation": 100000, "legal_fee": 2000, "taxes_other": 15000},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["transaction_id"] is None
    assert data["headline_valuation"] == 100000
    assert data["total_friction"] == 17000
    assert data["net_proceeds"] == 83000
    assert data["currency"] == "USD"


def test_missing_transaction_id_and_headline_valuation_returns_400(client, db_session):
    user = make_user(db_session, "user8")
    resp = client.post(
        "/transaction-cost-estimate",
        json={"legal_fee": 500},
        headers=auth_headers(user),
    )
    assert resp.status_code == 400


def test_negative_fee_rejected(client, db_session):
    user = make_user(db_session, "user9")
    resp = client.post(
        "/transaction-cost-estimate",
        json={"headline_valuation": 1000, "legal_fee": -50},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_negative_headline_valuation_rejected(client, db_session):
    user = make_user(db_session, "user10")
    resp = client.post(
        "/transaction-cost-estimate",
        json={"headline_valuation": -1000},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422


def test_currency_reflects_transaction_settlement_currency(client, db_session):
    seller = make_user(db_session, "seller11")
    buyer = make_user(db_session, "buyer11")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    assert txn.settlement_currency == "USD"

    resp = client.post(
        "/transaction-cost-estimate",
        json={"transaction_id": txn.id},
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    assert resp.json()["currency"] == "USD"


def test_requires_authentication(client, db_session):
    resp = client.post("/transaction-cost-estimate", json={"headline_valuation": 1000})
    assert resp.status_code in (401, 403)
