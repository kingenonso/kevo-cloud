import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app, get_db
from models import Base, User, Listing, OwnershipRecord, Transaction

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_seller(db):
    seller = User(name="Seller", email="batch1seller@test.com", role="seller")
    db.add(seller)
    db.commit()
    db.refresh(seller)
    return seller


def make_buyer(db):
    buyer = User(name="Buyer", email="batch1buyer@test.com", role="buyer")
    db.add(buyer)
    db.commit()
    db.refresh(buyer)
    return buyer


def make_listing(db, seller):
    listing = Listing(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares",
        quantity=1000, asking_price=50.0, is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_ownership(db, seller):
    ownership = OwnershipRecord(
        seller_id=seller.id, company="Acme Inc", asset_type="Private Shares", quantity=1000,
    )
    db.add(ownership)
    db.commit()
    db.refresh(ownership)
    return ownership


def make_transaction(db, listing, buyer):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=100, agreed_price=10.0, status="interested",
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def test_create_ownership_requires_auth(client, db_session):
    seller = make_seller(db_session)
    resp = client.post("/ownership", json={
        "seller_id": seller.id, "company": "Acme Inc", "asset_type": "Private Shares", "quantity": 1000,
    })
    assert resp.status_code == 401


def test_verify_ownership_requires_auth(client, db_session):
    seller = make_seller(db_session)
    ownership = make_ownership(db_session, seller)
    resp = client.put(
        f"/ownership/{ownership.id}/verify",
        params={"status": "verified", "verification_reference": "REF-X"},
    )
    assert resp.status_code == 401


def test_create_transaction_requires_auth(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    resp = client.post("/transactions", json={
        "listing_id": listing.id, "buyer_id": buyer.id, "quantity": 100, "agreed_price": 10.0,
    })
    assert resp.status_code == 401


def test_get_transactions_requires_auth(client, db_session):
    resp = client.get("/transactions")
    assert resp.status_code == 401


def test_get_transaction_by_id_requires_auth(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    resp = client.get(f"/transactions/{txn.id}")
    assert resp.status_code == 401


def test_update_transaction_status_requires_auth(client, db_session):
    seller = make_seller(db_session)
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)
    resp = client.patch(f"/transactions/{txn.id}/status", params={"status": "accepted"})
    assert resp.status_code == 401
