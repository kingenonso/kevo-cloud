import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app, get_db, hash_password
from models import Base, User

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


def make_legacy_user(db_session, role="seller", name="Legacy User"):
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


def make_user_with_password(db_session, plain_password="already-set-password", role="seller", name="Has Password"):
    _email_counter[0] += 1
    user = User(
        name=name,
        email=f"haspw{_email_counter[0]}@test.com",
        role=role,
        hashed_password=hash_password(plain_password),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_set_password_succeeds_for_legacy_user_with_no_password(client, db_session):
    legacy = make_legacy_user(db_session)

    response = client.post(f"/users/{legacy.id}/set-password", json={"password": "brand-new-password1"})

    assert response.status_code == 200

    db_session.refresh(legacy)
    assert legacy.hashed_password is not None
    assert legacy.hashed_password != "brand-new-password1"
    assert legacy.hashed_password.startswith("$2b$")


def test_can_log_in_after_setting_password(client, db_session):
    legacy = make_legacy_user(db_session)
    client.post(f"/users/{legacy.id}/set-password", json={"password": "brand-new-password1"})

    login_response = client.post("/login", json={
        "email": legacy.email,
        "password": "brand-new-password1",
    })

    assert login_response.status_code == 200
    assert "access_token" in login_response.json()


def test_set_password_rejected_when_user_already_has_one(client, db_session):
    user = make_user_with_password(db_session)

    response = client.post(f"/users/{user.id}/set-password", json={"password": "trying-to-overwrite"})

    assert response.status_code == 400


def test_set_password_does_not_overwrite_existing_password(client, db_session):
    user = make_user_with_password(db_session, plain_password="original-password1")

    client.post(f"/users/{user.id}/set-password", json={"password": "trying-to-overwrite"})

    login_response = client.post("/login", json={
        "email": user.email,
        "password": "original-password1",
    })
    assert login_response.status_code == 200

    failed_login = client.post("/login", json={
        "email": user.email,
        "password": "trying-to-overwrite",
    })
    assert failed_login.status_code == 401


def test_set_password_404_for_unknown_user(client, db_session):
    response = client.post("/users/999999/set-password", json={"password": "whatever123"})
    assert response.status_code == 404
