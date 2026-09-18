"""
Tests for the M9 missing buyer-interest-retrieval endpoints (2026-09-11) -
sixth and final of six M1-M12 findings from the re-verification audit.
Written against the REAL ~/KEVO implementation.

Finding: no GET /buyer-interests or GET /buyer-interests/{id} existed
anywhere in the real app, confirmed by grep before building anything.

Fix: added both, mirroring create_buyer_interest's own response shape
exactly - GET /buyer-interests returns a bare list like GET /listings;
GET /buyer-interests/{id} returns the same {"buyer_interest": {...}}
wrapper POST /buyer-interests already uses, including calling float()
on maximum_price (matching that endpoint's own existing convention).
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

from models import Base, User as UserModel, BuyerInterest
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
    auth_user = UserModel(
        name="Auth User",
        email=f"authuser{id(object())}@example.com",
        role="seller",
        account_type="admin",
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def make_buyer(db, suffix="1"):
    buyer = UserModel(name="Buyer", email=f"buyer{suffix}@example.com", role="buyer")
    db.add(buyer)
    db.commit()
    db.refresh(buyer)
    return buyer


def make_interest(db, buyer, company="Acme Inc", asset_type="Private Shares",
                   desired_quantity=100, maximum_price=20.0, status="active"):
    interest = BuyerInterest(
        buyer_id=buyer.id, company=company, asset_type=asset_type,
        desired_quantity=desired_quantity, maximum_price=maximum_price, status=status,
    )
    db.add(interest)
    db.commit()
    db.refresh(interest)
    return interest


# --- GET /buyer-interests (list) ---

def test_get_buyer_interests_returns_empty_list_when_none_exist(client, db_session):
    resp = client.get("/buyer-interests")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_buyer_interests_returns_all_interests(client, db_session):
    buyer = make_buyer(db_session)
    i1 = make_interest(db_session, buyer, company="Acme Inc")
    i2 = make_interest(db_session, buyer, company="Beta Corp")

    resp = client.get("/buyer-interests")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    ids = {i["id"] for i in body}
    assert ids == {i1.id, i2.id}


def test_get_buyer_interests_returns_correct_fields(client, db_session):
    buyer = make_buyer(db_session)
    interest = make_interest(
        db_session, buyer, company="Acme Inc", asset_type="Private Shares",
        desired_quantity=250, maximum_price=35.5, status="active",
    )

    resp = client.get("/buyer-interests")
    body = resp.json()[0]
    assert body["id"] == interest.id
    assert body["buyer_id"] == buyer.id
    assert body["company"] == "Acme Inc"
    assert body["asset_type"] == "Private Shares"
    assert body["desired_quantity"] == 250
    assert body["maximum_price"] == 35.5
    assert body["status"] == "active"


def test_get_buyer_interests_spans_multiple_buyers(client, db_session):
    buyer1 = make_buyer(db_session, "1")
    buyer2 = make_buyer(db_session, "2")
    make_interest(db_session, buyer1)
    make_interest(db_session, buyer2)

    resp = client.get("/buyer-interests")
    assert len(resp.json()) == 2


# --- GET /buyer-interests/{id} (single) ---

def test_get_buyer_interest_by_id_returns_correct_interest(client, db_session):
    buyer = make_buyer(db_session)
    interest = make_interest(
        db_session, buyer, company="Gamma Ltd", desired_quantity=400,
        maximum_price=12.25, status="withdrawn",
    )

    resp = client.get(f"/buyer-interests/{interest.id}")
    assert resp.status_code == 200
    body = resp.json()["buyer_interest"]
    assert body["id"] == interest.id
    assert body["buyer_id"] == buyer.id
    assert body["company"] == "Gamma Ltd"
    assert body["desired_quantity"] == 400
    assert body["maximum_price"] == 12.25
    assert body["status"] == "withdrawn"


def test_get_buyer_interest_by_id_404_for_unknown_id(client, db_session):
    resp = client.get("/buyer-interests/999999")
    assert resp.status_code == 404


def test_get_buyer_interest_by_id_does_not_collide_with_matches_route(client, db_session):
    buyer = make_buyer(db_session)
    interest = make_interest(db_session, buyer)

    # /buyer-interests/{id} and /buyer-interests/{id}/matches must both resolve correctly
    resp_single = client.get(f"/buyer-interests/{interest.id}")
    assert resp_single.status_code == 200
    assert resp_single.json()["buyer_interest"]["id"] == interest.id

    resp_matches = client.get(f"/buyer-interests/{interest.id}/matches")
    assert resp_matches.status_code == 200
