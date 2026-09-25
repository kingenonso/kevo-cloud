"""
Tests for the 2026-09-25 authorization fix on
GET /compliance-rules/matches/{buyer_id}/{listing_id} - this endpoint
previously took buyer_id straight from the URL with no check that it
matched the caller, so any authenticated user could pull any other
buyer's real compliance verdict (including the reasons) against any
listing. Fixed with the same owner-or-admin pattern used everywhere
else in KEVO (see test_investor_eligibility_verify.py). Found while
scoping M31's Eligibility Pre-Check, which builds on this endpoint.
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


def make_user(db, suffix="1", role="buyer", account_type="participant"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"compmatch{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller_id, company="Test Co"):
    listing = ListingModel(
        seller_id=seller_id, company=company, asset_type="Private Shares",
        quantity=100, asking_price=10000,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def test_buyer_can_view_own_matches(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller.id)

    resp = client.get(
        f"/compliance-rules/matches/{buyer.id}/{listing.id}",
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    assert resp.json()["buyer_id"] == buyer.id


def test_admin_can_view_any_buyers_matches(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller.id)

    resp = client.get(
        f"/compliance-rules/matches/{buyer.id}/{listing.id}",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["buyer_id"] == buyer.id


def test_stranger_cannot_view_other_buyers_matches_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller.id)

    resp = client.get(
        f"/compliance-rules/matches/{buyer.id}/{listing.id}",
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 403
