"""
Tests for the buyer-interest withdraw endpoint (2026-09-20): POST
/buyer-interests/{id}/withdraw. Added while completing the frontend so the
Browse page can offer a "withdraw interest" action. The status field already
existed (BuyerInterest.status defaults to "active" and is filtered on
elsewhere, e.g. the M16 demand heatmap/curve and M16b liquidity aggregation),
but there was previously no endpoint to change it. Written against the REAL
~/KEVO implementation.
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
    return TestClient(app)


def auth_headers(user):
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def make_buyer(db, suffix="1"):
    user = UserModel(
        name=f"Buyer {suffix}",
        email=f"withdraw{suffix}-{id(object())}@example.com",
        role="buyer",
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_interest(db, buyer):
    interest = BuyerInterest(
        buyer_id=buyer.id,
        company="Withdraw Test Co",
        asset_type="common_stock",
        desired_quantity=10,
        maximum_price=1000,
    )
    db.add(interest)
    db.commit()
    db.refresh(interest)
    return interest


def test_withdraw_requires_auth(client, db_session):
    buyer = make_buyer(db_session, "1")
    interest = make_interest(db_session, buyer)

    resp = client.post(f"/buyer-interests/{interest.id}/withdraw")
    assert resp.status_code == 401


def test_withdraw_updates_status(client, db_session):
    buyer = make_buyer(db_session, "2")
    interest = make_interest(db_session, buyer)

    resp = client.post(f"/buyer-interests/{interest.id}/withdraw", headers=auth_headers(buyer))
    assert resp.status_code == 200
    assert resp.json()["buyer_interest"]["status"] == "withdrawn"

    check = client.get(f"/buyer-interests/{interest.id}", headers=auth_headers(buyer))
    assert check.json()["buyer_interest"]["status"] == "withdrawn"


def test_withdraw_rejects_non_owner(client, db_session):
    owner = make_buyer(db_session, "3")
    other = make_buyer(db_session, "4")
    interest = make_interest(db_session, owner)

    resp = client.post(f"/buyer-interests/{interest.id}/withdraw", headers=auth_headers(other))
    assert resp.status_code == 403

    check = client.get(f"/buyer-interests/{interest.id}", headers=auth_headers(owner))
    assert check.json()["buyer_interest"]["status"] == "active"


def test_withdraw_returns_404_for_missing_interest(client, db_session):
    buyer = make_buyer(db_session, "5")

    resp = client.post("/buyer-interests/999999/withdraw", headers=auth_headers(buyer))
    assert resp.status_code == 404
