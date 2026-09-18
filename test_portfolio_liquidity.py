import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import app, get_db, hash_password, create_access_token
from models import Base, User, Listing, LiquidityPathStep

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

    auth_user = User(
        name="Auth Test User",
        email="__test_auth_user__@kevo.local",
        role="buyer",
        hashed_password=hash_password("testpass123"),
    )
    db_session.add(auth_user)
    db_session.commit()
    db_session.refresh(auth_user)
    token = create_access_token(auth_user.id)

    yield TestClient(app, headers={"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()


_email_counter = [0]


def make_seller(db_session, name="Test Seller"):
    _email_counter[0] += 1
    seller = User(
        name=name,
        email=f"seller{_email_counter[0]}@test.com",
        role="seller",
    )
    db_session.add(seller)
    db_session.commit()
    db_session.refresh(seller)
    return seller


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


def fake_step(step_type, sequence_position, required, complete, determinability, reasons="test fixture"):
    return {
        "step_type": step_type,
        "sequence_position": sequence_position,
        "required": required,
        "complete": complete,
        "evidence_reference_type": None,
        "evidence_reference_id": None,
        "responsible_party": "holder",
        "completion_trigger": "n/a",
        "determinability": determinability,
        "reasons": reasons,
        "source_milestone": "TEST",
    }


# ---------------------------------------------------------------------------

def test_seller_not_found_returns_404(client):
    response = client.get("/portfolio-liquidity/seller/999999")
    assert response.status_code == 404


def test_seller_with_no_listings_returns_empty_portfolio(client, db_session):
    seller = make_seller(db_session)

    response = client.get(f"/portfolio-liquidity/seller/{seller.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["seller_id"] == seller.id
    assert data["listing_count"] == 0
    assert data["listings_fully_complete"] == 0
    assert data["next_blocking_step_counts"] == {}
    assert data["listings"] == []


def test_bare_listing_blocks_on_ownership_verification(client, db_session):
    seller = make_seller(db_session)
    listing = make_listing(db_session, seller, company="Bare Co")

    response = client.get(f"/portfolio-liquidity/seller/{seller.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["listing_count"] == 1
    assert data["listings_fully_complete"] == 0
    assert data["next_blocking_step_counts"] == {"OWNERSHIP_VERIFICATION": 1}
    assert data["listings"][0]["listing_id"] == listing.id
    assert data["listings"][0]["company"] == "Bare Co"
    assert data["listings"][0]["asset_type"] == "Private Shares"
    assert "steps" in data["listings"][0]
    assert data["listings"][0]["total_steps"] == len(data["listings"][0]["steps"])


def test_multiple_bare_listings_all_tally_to_ownership(client, db_session):
    seller = make_seller(db_session)
    make_listing(db_session, seller, company="Co A")
    make_listing(db_session, seller, company="Co B")
    make_listing(db_session, seller, company="Co C")

    response = client.get(f"/portfolio-liquidity/seller/{seller.id}")

    data = response.json()
    assert data["listing_count"] == 3
    assert data["listings_fully_complete"] == 0
    assert data["next_blocking_step_counts"] == {"OWNERSHIP_VERIFICATION": 3}


def test_only_the_requested_sellers_listings_are_included(client, db_session):
    seller_a = make_seller(db_session, name="Seller A")
    seller_b = make_seller(db_session, name="Seller B")
    make_listing(db_session, seller_a, company="A's Listing 1")
    make_listing(db_session, seller_a, company="A's Listing 2")
    make_listing(db_session, seller_b, company="B's Listing")

    response_a = client.get(f"/portfolio-liquidity/seller/{seller_a.id}")
    response_b = client.get(f"/portfolio-liquidity/seller/{seller_b.id}")

    data_a = response_a.json()
    data_b = response_b.json()
    assert data_a["listing_count"] == 2
    assert {l["company"] for l in data_a["listings"]} == {"A's Listing 1", "A's Listing 2"}
    assert data_b["listing_count"] == 1
    assert data_b["listings"][0]["company"] == "B's Listing"


def test_endpoint_does_not_persist_anything(client, db_session):
    seller = make_seller(db_session)
    make_listing(db_session, seller, company="Co A")
    make_listing(db_session, seller, company="Co B")

    before = db_session.query(LiquidityPathStep).count()

    response = client.get(f"/portfolio-liquidity/seller/{seller.id}")
    assert response.status_code == 200

    after = db_session.query(LiquidityPathStep).count()
    assert before == after == 0


def test_listings_fully_complete_and_blockers_counted_correctly(client, db_session):
    seller = make_seller(db_session)
    listing_complete = make_listing(db_session, seller, company="Complete Co")
    listing_blocked_transfer = make_listing(db_session, seller, company="Transfer-Blocked Co")
    listing_blocked_ownership = make_listing(db_session, seller, company="Ownership-Blocked Co")

    def fake_build_liquidity_path(listing, db):
        if listing.company == "Complete Co":
            steps = [
                fake_step("OWNERSHIP_VERIFICATION", 1, True, True, "known_complete"),
                fake_step("TRANSFERABILITY_CLEARANCE", 2, True, True, "known_complete"),
                fake_step("DOCUMENTATION_COMPLETE", 3, None, False, "required_but_unverified"),
            ]
        elif listing.company == "Transfer-Blocked Co":
            steps = [
                fake_step("OWNERSHIP_VERIFICATION", 1, True, True, "known_complete"),
                fake_step("TRANSFERABILITY_CLEARANCE", 2, True, False, "known_incomplete"),
            ]
        else:
            steps = [
                fake_step("OWNERSHIP_VERIFICATION", 1, True, False, "known_incomplete"),
                fake_step("TRANSFERABILITY_CLEARANCE", 2, True, False, "cannot_determine"),
            ]
        return {"ownership_record_id": None, "steps": steps}

    with patch("app.build_liquidity_path", side_effect=fake_build_liquidity_path):
        response = client.get(f"/portfolio-liquidity/seller/{seller.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["listing_count"] == 3
    assert data["listings_fully_complete"] == 1
    assert data["next_blocking_step_counts"] == {
        "TRANSFERABILITY_CLEARANCE": 1,
        "OWNERSHIP_VERIFICATION": 1,
    }

    by_company = {l["company"]: l for l in data["listings"]}
    assert by_company["Complete Co"]["complete_count"] == 2
    assert by_company["Complete Co"]["total_steps"] == 3
    assert by_company["Transfer-Blocked Co"]["complete_count"] == 1
    assert by_company["Ownership-Blocked Co"]["cannot_determine_count"] == 1


def test_summary_counts_match_step_data(client, db_session):
    seller = make_seller(db_session)
    make_listing(db_session, seller, company="Cross-check Co")

    response = client.get(f"/portfolio-liquidity/seller/{seller.id}")
    data = response.json()
    listing_result = data["listings"][0]

    steps = listing_result["steps"]
    expected_complete = sum(1 for s in steps if s["complete"])
    expected_cannot_determine = sum(1 for s in steps if s["determinability"] == "cannot_determine")

    assert listing_result["complete_count"] == expected_complete
    assert listing_result["cannot_determine_count"] == expected_cannot_determine
    assert listing_result["total_steps"] == len(steps)
    assert str(expected_complete) in listing_result["summary"]
    assert str(expected_cannot_determine) in listing_result["summary"]
