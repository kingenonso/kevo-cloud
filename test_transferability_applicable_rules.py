"""
Tests for the new applicable-rules endpoint (2026-09-20): GET
/transferability/listing/{listing_id}/applicable-rules. Added while
building the ROFR frontend - a seller submitting a ROFR request needs to
pick a real transferability_rule_id, but no endpoint previously exposed
rule IDs for a listing (only a count, via GET /transferability/listing/{id},
or rule codes with no ID, via GET /transferability/matrix). This is a thin,
additive, read-only wrapper over the existing
find_applicable_transferability_rules() function. Written against the REAL
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

from models import Base, User as UserModel, Listing as ListingModel, TransferabilityRule
from app import app, get_db, hash_password, create_access_token

TEST_SOURCE = "TEST FIXTURE - not real regulatory content"


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


def make_user(db, suffix="1"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"applicablerules{suffix}-{id(object())}@example.com",
        role="seller",
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller, issuer_jurisdiction="United States", asset_type="Private Shares"):
    listing = ListingModel(
        seller_id=seller.id,
        company="Acme Inc",
        asset_type=asset_type,
        quantity=1000,
        asking_price=80.0,
        issuer_jurisdiction=issuer_jurisdiction,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_rule(db, rule_code, jurisdiction, asset_type="Private Shares"):
    rule = TransferabilityRule(
        jurisdiction=jurisdiction,
        asset_type=asset_type,
        fact_type="TEST_FACT",
        rule_code=rule_code,
        requirement="Test requirement",
        decision_if_unmet="needs_evidence",
        requires_human_review=True,
        active=True,
        source_reference=TEST_SOURCE,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def test_requires_auth(client, db_session):
    seller = make_user(db_session, "1")
    listing = make_listing(db_session, seller)

    resp = client.get(f"/transferability/listing/{listing.id}/applicable-rules")
    assert resp.status_code == 401


def test_returns_applicable_rules_for_matching_listing(client, db_session):
    seller = make_user(db_session, "2")
    listing = make_listing(db_session, seller, issuer_jurisdiction="South Africa")
    rule = make_rule(db_session, "TEST-ZA-ROFR", "South Africa")

    resp = client.get(f"/transferability/listing/{listing.id}/applicable-rules", headers=auth_headers(seller))
    assert resp.status_code == 200
    body = resp.json()
    assert body["listing_id"] == listing.id
    assert len(body["applicable_rules"]) == 1
    assert body["applicable_rules"][0]["id"] == rule.id
    assert body["applicable_rules"][0]["rule_code"] == "TEST-ZA-ROFR"


def test_returns_empty_for_non_matching_listing(client, db_session):
    seller = make_user(db_session, "3")
    listing = make_listing(db_session, seller, issuer_jurisdiction="Nigeria")
    make_rule(db_session, "TEST-ZA-ROFR", "South Africa")

    resp = client.get(f"/transferability/listing/{listing.id}/applicable-rules", headers=auth_headers(seller))
    assert resp.status_code == 200
    assert resp.json()["applicable_rules"] == []


def test_404_for_missing_listing(client, db_session):
    seller = make_user(db_session, "4")

    resp = client.get("/transferability/listing/999999/applicable-rules", headers=auth_headers(seller))
    assert resp.status_code == 404
