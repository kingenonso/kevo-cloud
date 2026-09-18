import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app, get_db
from models import Base, User as UserModel, Listing as ListingModel

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


def make_buyer(db_session, email="buyer@test.com"):
    buyer = UserModel(name="Buyer", email=email, role="buyer")
    db_session.add(buyer)
    db_session.commit()
    db_session.refresh(buyer)
    return buyer


def make_listing(db_session, seller_id=1, company="Test Co"):
    listing = ListingModel(
        seller_id=seller_id, company=company, asset_type="Private Shares",
        quantity=100, asking_price=10000,
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)
    return listing


def test_compliance_rules_matches_requires_auth(client, db_session):
    buyer = make_buyer(db_session)
    listing = make_listing(db_session, seller_id=buyer.id)
    response = client.get(f"/compliance-rules/matches/{buyer.id}/{listing.id}")
    assert response.status_code == 401


def test_update_kyc_status_requires_auth(client, db_session):
    buyer = make_buyer(db_session)
    response = client.put(f"/users/{buyer.id}/kyc-status", params={"status": "verified"})
    assert response.status_code == 401


def test_create_investor_eligibility_requires_auth(client, db_session):
    response = client.post("/investor-eligibility", json={})
    assert response.status_code == 401


def test_create_compliance_rule_requires_auth(client, db_session):
    response = client.post("/compliance-rules", json={})
    assert response.status_code == 401


def test_get_compliance_rules_requires_auth(client, db_session):
    response = client.get("/compliance-rules")
    assert response.status_code == 401
