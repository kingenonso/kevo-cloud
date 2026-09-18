import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app, get_db
from models import Base

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


def test_transferability_assessment_requires_auth(client):
    response = client.get("/transferability/listing/999999")
    assert response.status_code == 401


def test_transferability_matrix_requires_auth(client):
    response = client.get("/transferability/matrix")
    assert response.status_code == 401


def test_passport_requires_auth(client):
    response = client.get("/passport/listing/999999")
    assert response.status_code == 401


def test_position_events_requires_auth(client):
    response = client.get("/position-events/listing/999999")
    assert response.status_code == 401


def test_offering_exemptions_requires_auth(client):
    response = client.get("/offering-exemptions/999999")
    assert response.status_code == 401


def test_liquidity_path_listing_requires_auth(client):
    response = client.get("/liquidity-path/listing/999999")
    assert response.status_code == 401


def test_liquidity_path_transaction_requires_auth(client):
    response = client.get("/liquidity-path/transaction/999999")
    assert response.status_code == 401


def test_portfolio_liquidity_requires_auth(client):
    response = client.get("/portfolio-liquidity/seller/999999")
    assert response.status_code == 401


def test_deal_health_requires_auth(client):
    response = client.get("/deal-health/transaction/999999")
    assert response.status_code == 401


def test_risk_radar_requires_auth(client):
    response = client.get("/risk-radar/transaction/999999")
    assert response.status_code == 401
