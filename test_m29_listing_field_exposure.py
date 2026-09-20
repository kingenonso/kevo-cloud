"""
Tests for a real gap found while building M29's listing-detail edit form
(2026-09-20): GET /listings and GET /listings/{id} never returned
issuer_jurisdiction, is_transferable, issuer_reporting_status, or
issuer_current_information_available, even though POST/PUT both save and
return them. An edit form built without these would have silently wiped
them on every save. Fixed by adding them to both GET endpoints (additive
only, no behavior change). Written against the REAL ~/KEVO implementation.
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

from models import Base, User as UserModel, Listing as ListingModel
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


def make_seller(db, suffix="1"):
    user = UserModel(
        name=f"Seller {suffix}",
        email=f"m29field{suffix}-{id(object())}@example.com",
        role="seller",
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, jurisdiction="US", transferable=True):
    listing = ListingModel(
        seller_id=seller.id,
        company="Field Exposure Test Co",
        asset_type="common_stock",
        quantity=100,
        asking_price=5000,
        issuer_jurisdiction=jurisdiction,
        is_transferable=transferable,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def test_get_listings_includes_issuer_fields(client, db_session):
    seller = make_seller(db_session, "1")
    make_listing(db_session, seller, jurisdiction="CA", transferable=True)

    resp = client.get("/listings", headers=auth_headers(seller))
    assert resp.status_code == 200
    listing = resp.json()[0]
    assert listing["issuer_jurisdiction"] == "CA"
    assert listing["is_transferable"] is True
    assert "issuer_reporting_status" in listing
    assert "issuer_current_information_available" in listing


def test_get_single_listing_includes_issuer_fields(client, db_session):
    seller = make_seller(db_session, "2")
    listing = make_listing(db_session, seller, jurisdiction="UK", transferable=False)

    resp = client.get(f"/listings/{listing.id}", headers=auth_headers(seller))
    assert resp.status_code == 200
    body = resp.json()["listing"]
    assert body["issuer_jurisdiction"] == "UK"
    assert body["is_transferable"] is False
    assert "issuer_reporting_status" in body
    assert "issuer_current_information_available" in body
