"""
Tests for GET /me/eligibility-check/{listing_id}, M31's Eligibility
Pre-Check piece, 2026-09-25 - a self-only wrapper around
assess_compliance() so a buyer can check whether they'd currently pass
compliance on a real listing before acting on it. Built directly on top
of the same-day fix to GET /compliance-rules/matches/{buyer_id}/{listing_id},
which previously let any authenticated user query any other buyer's
compliance verdict.
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
        email=f"precheck{suffix}-{id(object())}@example.com",
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


def test_returns_own_compliance_result(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller.id)

    resp = client.get(
        f"/me/eligibility-check/{listing.id}",
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["buyer_id"] == buyer.id
    assert body["listing_id"] == listing.id
    assert "status" in body
    assert "explanation" in body


def test_listing_not_found_404(client, db_session):
    buyer = make_user(db_session, "1", role="buyer")

    resp = client.get(
        "/me/eligibility-check/999999",
        headers=auth_headers(buyer),
    )
    assert resp.status_code == 404


def test_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    listing = make_listing(db_session, seller.id)

    resp = client.get(f"/me/eligibility-check/{listing.id}")
    assert resp.status_code == 401


def test_two_buyers_each_see_only_their_own_result(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer_a = make_user(db_session, "2", role="buyer")
    buyer_b = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller.id)

    resp_a = client.get(
        f"/me/eligibility-check/{listing.id}",
        headers=auth_headers(buyer_a),
    )
    resp_b = client.get(
        f"/me/eligibility-check/{listing.id}",
        headers=auth_headers(buyer_b),
    )
    assert resp_a.json()["buyer_id"] == buyer_a.id
    assert resp_b.json()["buyer_id"] == buyer_b.id
    assert resp_a.json()["buyer_id"] != resp_b.json()["buyer_id"]
