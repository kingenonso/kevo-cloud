"""
Tests for M33B (first slice) - KEVO Liquidity-as-a-Service: admin-
provisioned third-party API clients, authenticated by API key (never a
KEVO user JWT), with read-only access to the advisory engines only
(transferability, compliance check, ROFR status) - the matching engine
is deliberately not exposed here, see ApiClient's docstring in models.py.
"""
import os
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base,
    User as UserModel,
    Listing as ListingModel,
    Transaction,
    TransferabilityRule,
    TransferabilityFact,
    RofrRequest,
    ApiClient,
    ApiKey,
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


def make_user(db, suffix, account_type="participant", role="buyer", kyc_status="verified"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m33b-{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("password123"),
        terms_accepted=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user):
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def make_listing(db, seller, company="Acme Co", asset_type="common_stock"):
    listing = ListingModel(
        seller_id=seller.id,
        company=company,
        asset_type=asset_type,
        quantity=1000,
        asking_price=10.0,
        is_transferable=True,
        issuer_jurisdiction="Delaware",
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def create_api_client_via_endpoint(client, admin, organization_name="Fund Partner LLC"):
    resp = client.post(
        "/admin/api-clients",
        json={
            "organization_name": organization_name,
            "contact_email": "contact@fundpartner.example.com",
            "description": "A test integration partner",
        },
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Admin provisioning ---------------------------------------------------

def test_admin_can_create_api_client(client, db_session):
    admin = make_user(db_session, "admin1", account_type="admin")

    body = create_api_client_via_endpoint(client, admin)

    assert body["api_client"]["organization_name"] == "Fund Partner LLC"
    assert body["api_client"]["active"] is True
    assert isinstance(body["api_key"], str) and len(body["api_key"]) > 20


def test_non_admin_cannot_create_api_client(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")

    resp = client.post(
        "/admin/api-clients",
        json={"organization_name": "Sneaky LLC", "contact_email": "a@b.com"},
        headers=auth_headers(seller),
    )

    assert resp.status_code == 403


def test_admin_can_list_api_clients(client, db_session):
    admin = make_user(db_session, "admin2", account_type="admin")
    create_api_client_via_endpoint(client, admin, "Fund A")
    create_api_client_via_endpoint(client, admin, "Fund B")

    resp = client.get("/admin/api-clients", headers=auth_headers(admin))

    assert resp.status_code == 200
    orgs = {c["organization_name"] for c in resp.json()}
    assert orgs == {"Fund A", "Fund B"}
    # the raw key is never returned on list - only a prefix
    for c in resp.json():
        assert len(c["keys"]) == 1
        assert "key_prefix" in c["keys"][0]
        assert "key_hash" not in c["keys"][0]


# --- API key authentication -----------------------------------------------

def test_api_endpoint_rejects_missing_key(client, db_session):
    seller = make_user(db_session, "seller2")
    listing = make_listing(db_session, seller)

    resp = client.get(f"/api/v1/transferability/listing/{listing.id}")

    assert resp.status_code == 401


def test_api_endpoint_rejects_invalid_key(client, db_session):
    seller = make_user(db_session, "seller3")
    listing = make_listing(db_session, seller)

    resp = client.get(
        f"/api/v1/transferability/listing/{listing.id}",
        headers={"X-API-Key": "not-a-real-key"},
    )

    assert resp.status_code == 401


def test_api_endpoint_works_with_valid_key(client, db_session):
    admin = make_user(db_session, "admin3", account_type="admin")
    seller = make_user(db_session, "seller4")
    listing = make_listing(db_session, seller)
    body = create_api_client_via_endpoint(client, admin)
    raw_key = body["api_key"]

    resp = client.get(
        f"/api/v1/transferability/listing/{listing.id}",
        headers={"X-API-Key": raw_key},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["listing_id"] == listing.id
    assert "status" in data


def test_revoked_client_key_rejected(client, db_session):
    admin = make_user(db_session, "admin4", account_type="admin")
    seller = make_user(db_session, "seller5")
    listing = make_listing(db_session, seller)
    body = create_api_client_via_endpoint(client, admin)
    raw_key = body["api_key"]
    client_id = body["api_client"]["id"]

    revoke_resp = client.put(f"/admin/api-clients/{client_id}/revoke", headers=auth_headers(admin))
    assert revoke_resp.status_code == 200

    resp = client.get(
        f"/api/v1/transferability/listing/{listing.id}",
        headers={"X-API-Key": raw_key},
    )

    assert resp.status_code == 401


def test_key_rotation_issues_new_key_without_revoking_client(client, db_session):
    admin = make_user(db_session, "admin5", account_type="admin")
    seller = make_user(db_session, "seller6")
    listing = make_listing(db_session, seller)
    body = create_api_client_via_endpoint(client, admin)
    old_key = body["api_key"]
    client_id = body["api_client"]["id"]

    rotate_resp = client.post(f"/admin/api-clients/{client_id}/keys", headers=auth_headers(admin))
    assert rotate_resp.status_code == 200
    new_key = rotate_resp.json()["api_key"]
    assert new_key != old_key

    # both keys still work - rotation is additive, not a revoke-and-replace
    old_resp = client.get(f"/api/v1/transferability/listing/{listing.id}", headers={"X-API-Key": old_key})
    new_resp = client.get(f"/api/v1/transferability/listing/{listing.id}", headers={"X-API-Key": new_key})
    assert old_resp.status_code == 200
    assert new_resp.status_code == 200


def test_cannot_rotate_key_for_revoked_client(client, db_session):
    admin = make_user(db_session, "admin6", account_type="admin")
    body = create_api_client_via_endpoint(client, admin)
    client_id = body["api_client"]["id"]
    client.put(f"/admin/api-clients/{client_id}/revoke", headers=auth_headers(admin))

    resp = client.post(f"/admin/api-clients/{client_id}/keys", headers=auth_headers(admin))

    assert resp.status_code == 400


# --- Engine coverage: transferability, compliance, ROFR -------------------

def test_api_transferability_check_reaches_real_engine(client, db_session):
    admin = make_user(db_session, "admin7", account_type="admin")
    seller = make_user(db_session, "seller7")
    listing = make_listing(db_session, seller, company="Blocked Co")
    rule = TransferabilityRule(
        rule_code="API-TEST-RULE",
        jurisdiction="Delaware",
        asset_type="common_stock",
        fact_type="identity_verified",
        requirement="identity_verified",
        decision_if_unmet="blocked",
        source_reference="test fixture",
    )
    db_session.add(rule)
    db_session.commit()
    key = create_api_client_via_endpoint(client, admin)["api_key"]

    resp = client.get(f"/api/v1/transferability/listing/{listing.id}", headers={"X-API-Key": key})

    assert resp.status_code == 200
    assert resp.json()["status"] == "blocked"


def test_api_transferability_404_for_missing_listing(client, db_session):
    admin = make_user(db_session, "admin8", account_type="admin")
    key = create_api_client_via_endpoint(client, admin)["api_key"]

    resp = client.get("/api/v1/transferability/listing/999999", headers={"X-API-Key": key})

    assert resp.status_code == 404


def test_api_compliance_check(client, db_session):
    admin = make_user(db_session, "admin9", account_type="admin")
    seller = make_user(db_session, "seller8")
    buyer = make_user(db_session, "buyer1", kyc_status="not_started")
    listing = make_listing(db_session, seller)
    key = create_api_client_via_endpoint(client, admin)["api_key"]

    resp = client.get(f"/api/v1/compliance-check/{buyer.id}/{listing.id}", headers={"X-API-Key": key})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["buyer_id"] == buyer.id
    assert data["listing_id"] == listing.id
    assert "status" in data


def test_api_compliance_check_404_for_missing_buyer(client, db_session):
    admin = make_user(db_session, "admin10", account_type="admin")
    seller = make_user(db_session, "seller9")
    listing = make_listing(db_session, seller)
    key = create_api_client_via_endpoint(client, admin)["api_key"]

    resp = client.get(f"/api/v1/compliance-check/999999/{listing.id}", headers={"X-API-Key": key})

    assert resp.status_code == 404


def test_api_rofr_status(client, db_session):
    admin = make_user(db_session, "admin11", account_type="admin")
    seller = make_user(db_session, "seller10")
    buyer = make_user(db_session, "buyer2")
    listing = make_listing(db_session, seller)
    rule = TransferabilityRule(
        rule_code="API-ROFR-RULE",
        jurisdiction="Delaware",
        asset_type="common_stock",
        fact_type="rofr_consent",
        requirement="rofr_consent",
        decision_if_unmet="needs_evidence",
        source_reference="test fixture",
    )
    db_session.add(rule)
    db_session.commit()
    transaction = Transaction(
        listing_id=listing.id,
        buyer_id=buyer.id,
        seller_id=seller.id,
        quantity=100,
        agreed_price=12.0,
        status="accepted",
    )
    db_session.add(transaction)
    db_session.commit()
    rofr = RofrRequest(
        transaction_id=transaction.id,
        transferability_rule_id=rule.id,
        status="pending",
    )
    db_session.add(rofr)
    db_session.commit()
    key = create_api_client_via_endpoint(client, admin)["api_key"]

    resp = client.get(f"/api/v1/rofr-status/transaction/{transaction.id}", headers={"X-API-Key": key})

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["transaction_id"] == transaction.id
    assert len(data["rofr_requests"]) == 1
    assert data["rofr_requests"][0]["status"] == "pending"


def test_api_rofr_status_404_for_missing_transaction(client, db_session):
    admin = make_user(db_session, "admin12", account_type="admin")
    key = create_api_client_via_endpoint(client, admin)["api_key"]

    resp = client.get("/api/v1/rofr-status/transaction/999999", headers={"X-API-Key": key})

    assert resp.status_code == 404


def test_matching_engine_not_exposed_under_api_v1(client, db_session):
    """
    The matching engine is deliberately NOT part of this slice (see
    ApiClient's docstring) - there should be no /api/v1/matches route at
    all, regardless of authentication.
    """
    admin = make_user(db_session, "admin13", account_type="admin")
    key = create_api_client_via_endpoint(client, admin)["api_key"]

    resp = client.get("/api/v1/matches", headers={"X-API-Key": key})

    assert resp.status_code == 404


def test_api_access_is_audit_logged(client, db_session):
    from models import AuditLogEntry

    admin = make_user(db_session, "admin14", account_type="admin")
    seller = make_user(db_session, "seller11")
    listing = make_listing(db_session, seller)
    key = create_api_client_via_endpoint(client, admin)["api_key"]

    client.get(f"/api/v1/transferability/listing/{listing.id}", headers={"X-API-Key": key})

    entries = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "api_client_transferability_check"
    ).all()
    assert len(entries) == 1
    assert entries[0].target_id == listing.id
    assert entries[0].actor_user_id is None
