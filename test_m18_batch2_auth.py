import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app, get_db
from models import Base, User, Listing, BuyerInterest

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
    seller = User(name="Seller", email="batch2seller@test.com", role="seller")
    db.add(seller)
    db.commit()
    db.refresh(seller)
    return seller


def make_buyer(db):
    buyer = User(name="Buyer", email="batch2buyer@test.com", role="buyer")
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


def make_interest(db, buyer):
    interest = BuyerInterest(
        buyer_id=buyer.id, company="Acme Inc", asset_type="Private Shares",
        desired_quantity=100, maximum_price=50.0, status="active",
    )
    db.add(interest)
    db.commit()
    db.refresh(interest)
    return interest


def test_create_listing_requires_auth(client, db_session):
    seller = make_seller(db_session)
    resp = client.post("/listings", json={
        "seller_id": seller.id, "company": "Acme Inc", "asset_type": "Private Shares",
        "quantity": 1000, "asking_price": 50.0,
    })
    assert resp.status_code == 401


def test_get_listings_requires_auth(client, db_session):
    resp = client.get("/listings")
    assert resp.status_code == 401


def test_update_listing_requires_auth(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)
    resp = client.put(f"/listings/{listing.id}", json={
        "seller_id": seller.id, "company": "New Co", "asset_type": "Private Shares",
        "quantity": 500, "asking_price": 50.0,
    })
    assert resp.status_code == 401


def test_delete_listing_requires_auth(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller)
    resp = client.delete(f"/listings/{listing.id}")
    assert resp.status_code == 401


def test_create_buyer_interest_requires_auth(client, db_session):
    buyer = make_buyer(db_session)
    resp = client.post("/buyer-interests", json={
        "buyer_id": buyer.id, "company": "Acme Inc", "asset_type": "Private Shares",
        "desired_quantity": 100, "maximum_price": 50.0,
    })
    assert resp.status_code == 401


def test_get_buyer_interests_requires_auth(client, db_session):
    resp = client.get("/buyer-interests")
    assert resp.status_code == 401


def test_get_buyer_interest_by_id_requires_auth(client, db_session):
    buyer = make_buyer(db_session)
    interest = make_interest(db_session, buyer)
    resp = client.get(f"/buyer-interests/{interest.id}")
    assert resp.status_code == 401


def test_buyer_interest_matches_requires_auth(client, db_session):
    buyer = make_buyer(db_session)
    interest = make_interest(db_session, buyer)
    resp = client.get(f"/buyer-interests/{interest.id}/matches")
    assert resp.status_code == 401
