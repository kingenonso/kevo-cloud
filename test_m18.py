import pytest
import jwt as pyjwt
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app, get_db, SECRET_KEY, JWT_ALGORITHM, hash_password
from models import Base, User, Listing

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


_email_counter = [0]


def make_user_with_password(db_session, plain_password="correct-horse-battery", role="seller", name="Test User"):
    _email_counter[0] += 1
    user = User(
        name=name,
        email=f"user{_email_counter[0]}@test.com",
        role=role,
        hashed_password=hash_password(plain_password),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def make_legacy_user_no_password(db_session, role="seller", name="Legacy User"):
    _email_counter[0] += 1
    user = User(
        name=name,
        email=f"legacy{_email_counter[0]}@test.com",
        role=role,
        hashed_password=None,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def make_listing(db_session, seller, company="Test Co", asset_type="Private Shares",
                  quantity=100, asking_price=10000, is_transferable=True):
    listing = Listing(
        seller_id=seller.id,
        company=company,
        asset_type=asset_type,
        quantity=quantity,
        asking_price=asking_price,
        is_transferable=is_transferable,
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)
    return listing


def make_expired_token(user_id):
    expire = datetime.utcnow() - timedelta(minutes=5)
    payload = {"sub": str(user_id), "exp": expire}
    return pyjwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Signup stores a hash, never the plain password

def test_signup_stores_bcrypt_hash_not_plaintext(client, db_session):
    response = client.post("/users", json={
        "name": "New User",
        "email": "newuser@test.com",
        "role": "seller",
        "password": "supersecret123",
    })
    assert response.status_code == 200

    stored = db_session.query(User).filter(User.email == "newuser@test.com").first()
    assert stored is not None
    assert stored.hashed_password is not None
    assert stored.hashed_password != "supersecret123"
    assert stored.hashed_password.startswith("$2b$")


# ---------------------------------------------------------------------------
# Login

def test_login_succeeds_with_correct_credentials_and_returns_valid_jwt(client, db_session):
    user = make_user_with_password(db_session, plain_password="mypassword1")

    response = client.post("/login", json={
        "email": user.email,
        "password": "mypassword1",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert "access_token" in data

    decoded = pyjwt.decode(data["access_token"], SECRET_KEY, algorithms=[JWT_ALGORITHM])
    assert decoded["sub"] == str(user.id)


def test_login_fails_with_wrong_password(client, db_session):
    user = make_user_with_password(db_session, plain_password="mypassword1")

    response = client.post("/login", json={
        "email": user.email,
        "password": "wrong-password",
    })

    assert response.status_code == 401


def test_login_fails_with_nonexistent_email(client, db_session):
    response = client.post("/login", json={
        "email": "nobody@test.com",
        "password": "whatever",
    })

    assert response.status_code == 401


def test_login_fails_for_legacy_user_with_no_password_set(client, db_session):
    legacy = make_legacy_user_no_password(db_session)

    response = client.post("/login", json={
        "email": legacy.email,
        "password": "anything",
    })

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /users - protected

def test_get_users_rejects_missing_auth_header(client, db_session):
    response = client.get("/users")
    assert response.status_code == 401


def test_get_users_rejects_invalid_token(client, db_session):
    response = client.get("/users", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_get_users_rejects_expired_token(client, db_session):
    user = make_user_with_password(db_session)
    expired = make_expired_token(user.id)
    response = client.get("/users", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401


def test_get_users_succeeds_with_valid_token(client, db_session):
    user = make_user_with_password(db_session, plain_password="mypassword1")
    login_response = client.post("/login", json={"email": user.email, "password": "mypassword1"})
    token = login_response.json()["access_token"]

    response = client.get("/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /listings/{listing_id} - protected

def test_get_listing_rejects_missing_auth_header(client, db_session):
    seller = make_user_with_password(db_session)
    listing = make_listing(db_session, seller)

    response = client.get(f"/listings/{listing.id}")
    assert response.status_code == 401


def test_get_listing_rejects_invalid_token(client, db_session):
    seller = make_user_with_password(db_session)
    listing = make_listing(db_session, seller)

    response = client.get(f"/listings/{listing.id}", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


def test_get_listing_succeeds_with_valid_token(client, db_session):
    seller = make_user_with_password(db_session, plain_password="mypassword1")
    listing = make_listing(db_session, seller)

    login_response = client.post("/login", json={"email": seller.email, "password": "mypassword1"})
    token = login_response.json()["access_token"]

    response = client.get(f"/listings/{listing.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["listing"]["id"] == listing.id


# ---------------------------------------------------------------------------
# Spot-check: an unrelated, still-unprotected endpoint remains open

def test_portfolio_liquidity_endpoint_now_requires_auth(client, db_session):
    seller = make_user_with_password(db_session, plain_password="mypassword1")

    response = client.get(f"/portfolio-liquidity/seller/{seller.id}")
    assert response.status_code == 401

    login_response = client.post("/login", json={"email": seller.email, "password": "mypassword1"})
    token = login_response.json()["access_token"]
    response = client.get(f"/portfolio-liquidity/seller/{seller.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
