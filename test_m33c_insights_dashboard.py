"""
Tests for M33C (first slice) - Private Market Data & Insights, a
reporting dashboard over data KEVO already produces and already exposes
publicly, unauthenticated, via /price-range, /demand-heatmap,
/demand-curve, and /liquidity-aggregation. This does not change those
endpoints - this adds a named, admin-provisioned subscriber account type
with a login, one composite dashboard endpoint, and a query log.
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

from models import Base, User as UserModel, BuyerInterest, Listing as ListingModel, AuditLogEntry
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


def make_user(db, suffix, account_type="participant", role="buyer", insights_subscriber_organization=None, insights_subscriber_type=None):
    user = UserModel(
        name=f"User {suffix}",
        email=f"m33c-{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status="verified",
        hashed_password=hash_password("password123"),
        insights_subscriber_organization=insights_subscriber_organization,
        insights_subscriber_type=insights_subscriber_type,
        terms_accepted=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_headers(user):
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_create_insights_subscriber_account(client, db_session):
    admin = make_user(db_session, "admin1", account_type="admin")

    resp = client.post(
        "/admin/insights-subscriber-accounts",
        json={
            "name": "VC Analyst",
            "email": "analyst@examplevc.com",
            "password": "subscriberpass123",
            "organization_name": "Example Ventures",
            "subscriber_type": "vc",
        },
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()["subscriber"]
    assert body["organization_name"] == "Example Ventures"
    assert body["subscriber_type"] == "vc"
    assert body["account_type"] == "insights_subscriber"


def test_non_admin_cannot_create_insights_subscriber_account(client, db_session):
    seller = make_user(db_session, "seller1", role="seller")

    resp = client.post(
        "/admin/insights-subscriber-accounts",
        json={
            "name": "Fake Subscriber",
            "email": "fake@example.com",
            "password": "pw",
            "organization_name": "Whatever LLC",
        },
        headers=auth_headers(seller),
    )

    assert resp.status_code == 403


def test_invalid_subscriber_type_rejected(client, db_session):
    admin = make_user(db_session, "admin2", account_type="admin")

    resp = client.post(
        "/admin/insights-subscriber-accounts",
        json={
            "name": "Bad Type",
            "email": "bad@example.com",
            "password": "pw12345",
            "organization_name": "Bad Co",
            "subscriber_type": "not_a_real_type",
        },
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400


def test_non_subscriber_cannot_reach_dashboard(client, db_session):
    seller = make_user(db_session, "seller2", role="seller")

    resp = client.get(
        "/insights/dashboard",
        params={"company": "Acme Co", "asset_type": "common_stock"},
        headers=auth_headers(seller),
    )

    assert resp.status_code == 403


def test_subscriber_profile_endpoint(client, db_session):
    subscriber = make_user(
        db_session, "sub1", account_type="insights_subscriber",
        insights_subscriber_organization="Example Ventures",
        insights_subscriber_type="vc",
    )

    resp = client.get("/insights/me", headers=auth_headers(subscriber))

    assert resp.status_code == 200
    body = resp.json()
    assert body["organization_name"] == "Example Ventures"
    assert body["subscriber_type"] == "vc"


def test_dashboard_composes_all_four_aggregate_endpoints(client, db_session):
    subscriber = make_user(
        db_session, "sub2", account_type="insights_subscriber",
        insights_subscriber_organization="Example Ventures",
        insights_subscriber_type="vc",
    )

    resp = client.get(
        "/insights/dashboard",
        params={"company": "Acme Co", "asset_type": "common_stock"},
        headers=auth_headers(subscriber),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["company"] == "Acme Co"
    assert body["asset_type"] == "common_stock"
    for key in ("price_range", "demand_heatmap", "demand_curve", "liquidity_aggregation"):
        assert key in body
        assert "status" in body[key]


def test_dashboard_honestly_reports_insufficient_data(client, db_session):
    """
    With no real buyer interests/listings on file for this company/asset
    type combination, every composed engine should honestly report
    insufficient_data rather than fabricating a result - same discipline
    as the underlying public endpoints.
    """
    subscriber = make_user(
        db_session, "sub3", account_type="insights_subscriber",
        insights_subscriber_organization="Example Ventures",
        insights_subscriber_type="vc",
    )

    resp = client.get(
        "/insights/dashboard",
        params={"company": "Nonexistent Co", "asset_type": "common_stock"},
        headers=auth_headers(subscriber),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["demand_heatmap"]["status"] in ("insufficient_data", "ok")
    assert body["liquidity_aggregation"]["status"] == "insufficient_data"


def test_dashboard_query_is_audit_logged(client, db_session):
    subscriber = make_user(
        db_session, "sub4", account_type="insights_subscriber",
        insights_subscriber_organization="Example Ventures",
        insights_subscriber_type="vc",
    )

    client.get(
        "/insights/dashboard",
        params={"company": "Acme Co", "asset_type": "common_stock"},
        headers=auth_headers(subscriber),
    )

    entries = db_session.query(AuditLogEntry).filter(
        AuditLogEntry.action == "insights_dashboard_query"
    ).all()
    assert len(entries) == 1
    assert entries[0].actor_user_id == subscriber.id
    assert "Acme Co" in entries[0].detail
