"""
Tests for M27's third and final piece (2026-09-25): the Deal Dependency
Graph.

Written against the REAL ~/KEVO implementation.

A read-time diff layer over M15's Liquidity Path Engine - no new table,
no new trigger points. GET /transactions/{id}/dependency-changes takes
the most recent existing LiquidityPathStep snapshot as "before", computes
and persists one fresh snapshot as "after" (same mechanism the existing
liquidity-path endpoint already uses), diffs step by step (matched by the
stable step_type), and for anything that changed, walks the real
blocking_step_id edges forward to report which downstream steps are
affected.
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
    Base, User as UserModel, Listing as ListingModel, Transaction,
    OwnershipRecord,
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
        email=f"m27depchanges{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
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


def make_transaction(db, listing, buyer, quantity=100, status="interested", agreed_price=10.0):
    txn = Transaction(
        listing_id=listing.id, buyer_id=buyer.id, seller_id=listing.seller_id,
        quantity=quantity, agreed_price=agreed_price, status=status,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def make_ownership(db, listing, seller, verification_status="pending"):
    record = OwnershipRecord(
        seller_id=seller.id, listing_id=listing.id, company="Acme Inc",
        asset_type="Private Shares", quantity=1000,
        verification_status=verification_status,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def test_404_for_unknown_transaction(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    resp = client.get("/transactions/999999/dependency-changes", headers=auth_headers(seller))
    assert resp.status_code == 404


def test_non_party_403(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    stranger = make_user(db_session, "3", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}/dependency-changes", headers=auth_headers(stranger))
    assert resp.status_code == 403


def test_unauthenticated_401(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}/dependency-changes")
    assert resp.status_code == 401


def test_first_call_establishes_baseline(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}/dependency-changes", headers=auth_headers(buyer))
    assert resp.status_code == 200
    body = resp.json()
    assert body["previous_run_id"] is None
    assert body["new_run_id"] is not None
    assert body["changed_steps"] == []
    assert "message" in body


def test_no_changes_between_two_identical_calls(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    first = client.get(f"/transactions/{txn.id}/dependency-changes", headers=auth_headers(buyer))
    assert first.status_code == 200

    second = client.get(f"/transactions/{txn.id}/dependency-changes", headers=auth_headers(buyer))
    assert second.status_code == 200
    body = second.json()
    assert body["previous_run_id"] == first.json()["new_run_id"]
    assert body["changed_steps"] == []


def test_ownership_verification_change_reports_all_downstream_steps(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    baseline = client.get(f"/transactions/{txn.id}/dependency-changes", headers=auth_headers(buyer))
    assert baseline.status_code == 200
    assert baseline.json()["changed_steps"] == []

    make_ownership(db_session, listing, seller, verification_status="verified")

    resp = client.get(f"/transactions/{txn.id}/dependency-changes", headers=auth_headers(buyer))
    assert resp.status_code == 200
    body = resp.json()
    assert body["previous_run_id"] == baseline.json()["new_run_id"]

    changed = {c["step_type"]: c for c in body["changed_steps"]}
    assert "OWNERSHIP_VERIFICATION" in changed
    ownership_change = changed["OWNERSHIP_VERIFICATION"]
    assert ownership_change["previous"]["complete"] is False
    assert ownership_change["current"]["complete"] is True

    downstream_types = {d["step_type"] for d in ownership_change["downstream_steps_affected"]}
    assert "TRANSFERABILITY_CLEARANCE" in downstream_types
    assert "DOCUMENTATION_COMPLETE" in downstream_types
    assert "CASH_RELEASE" in downstream_types
    assert len(downstream_types) == 8


def test_admin_succeeds(client, db_session):
    seller = make_user(db_session, "1", role="seller")
    buyer = make_user(db_session, "2", role="buyer")
    admin = make_user(db_session, "3", account_type="admin")
    listing = make_listing(db_session, seller)
    txn = make_transaction(db_session, listing, buyer)

    resp = client.get(f"/transactions/{txn.id}/dependency-changes", headers=auth_headers(admin))
    assert resp.status_code == 200
