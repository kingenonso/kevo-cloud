"""
Tests for M25B's Forward Sale / Pre-Liquidity-Event Contracts,
structured-safe scope (POST/accept/cancel/governing-document-review/
settle + GET /forward-sale-contracts), 2026-10-23.

M25B was formally deferred on 2026-09-18 (claude/kevo-m25b-forward-sale-
legal-research.md) over three independent obstacles: Dodd-Frank
security-based-swap reclassification risk, IRC Section 1259 constructive-
sale tax risk, and unverifiable per-company governing-document
prohibitions. Confirmed with Eze via AskUserQuestion, 2026-10-23: build
with fixes for the first two (buyer must be an admin-verified Eligible
Contract Participant; floor/cap price range instead of one fixed price)
and an explicit, KEVO-unverified attestation/review flag for the third.

Written against the real ~/KEVO implementation, same fixture pattern as
test_m17b_spv_pools.py.
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

from models import Base, User as UserModel, Listing as ListingModel, InvestorEligibility, ForwardSaleContract
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


def make_user(db, suffix="1", role="buyer", account_type="participant", kyc_status="verified"):
    user = UserModel(
        name=f"User {suffix}",
        email=f"fwd{suffix}-{id(object())}@example.com",
        role=role,
        account_type=account_type,
        kyc_status=kyc_status,
        hashed_password=hash_password("testpass123"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_listing(db, seller):
    listing = ListingModel(
        seller_id=seller.id,
        company="Acme Inc",
        asset_type="Private Shares",
        quantity=1000,
        asking_price=50000.0,
        is_transferable=True,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def make_verified_ecp(db, buyer):
    record = InvestorEligibility(
        buyer_id=buyer.id,
        investor_type="institutional",
        classification="eligible_contract_participant",
        status="verified",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def base_payload(listing, buyer):
    return {
        "listing_id": listing.id,
        "buyer_id": buyer.id,
        "floor_price": 40000.0,
        "cap_price": 60000.0,
        "prepaid_amount": 45000.0,
        "trigger_event": "holding_period_expiration",
        "seller_attests_no_governing_document_prohibition": True,
    }


# --- POST /forward-sale-contracts ---

def test_seller_can_propose_contract_with_verified_ecp_buyer(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)

    resp = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "proposed"
    assert data["seller_id"] == seller.id
    assert data["buyer_id"] == buyer.id
    assert data["governing_document_review_status"] == "not_reviewed"
    assert "not tax or legal advice" in data["disclaimer"]


def test_create_rejects_buyer_without_verified_ecp_status(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")

    resp = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller))

    assert resp.status_code == 400
    assert "eligible_contract_participant" in resp.json()["detail"]


def test_create_rejects_unverified_ecp_record(client, db_session):
    """A pending (not yet admin-verified) InvestorEligibility record must not satisfy the gate."""
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    record = InvestorEligibility(
        buyer_id=buyer.id,
        investor_type="institutional",
        classification="eligible_contract_participant",
        status="pending",
    )
    db_session.add(record)
    db_session.commit()

    resp = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller))

    assert resp.status_code == 400


def test_create_rejects_equal_floor_and_cap_price(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    payload = {**base_payload(listing, buyer), "cap_price": 40000.0}

    resp = client.post("/forward-sale-contracts", params=payload, headers=auth_headers(seller))

    assert resp.status_code == 400
    assert "1259" in resp.json()["detail"]


def test_create_rejects_cap_below_floor(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    payload = {**base_payload(listing, buyer), "floor_price": 60000.0, "cap_price": 40000.0}

    resp = client.post("/forward-sale-contracts", params=payload, headers=auth_headers(seller))

    assert resp.status_code == 400


def test_create_rejects_non_positive_prepaid_amount(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    payload = {**base_payload(listing, buyer), "prepaid_amount": 0}

    resp = client.post("/forward-sale-contracts", params=payload, headers=auth_headers(seller))

    assert resp.status_code == 400


def test_create_requires_seller_attestation(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    payload = {**base_payload(listing, buyer), "seller_attests_no_governing_document_prohibition": False}

    resp = client.post("/forward-sale-contracts", params=payload, headers=auth_headers(seller))

    assert resp.status_code == 400
    assert "attest" in resp.json()["detail"]


def test_create_rejects_invalid_trigger_event(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    payload = {**base_payload(listing, buyer), "trigger_event": "rumored_future_ipo"}

    resp = client.post("/forward-sale-contracts", params=payload, headers=auth_headers(seller))

    assert resp.status_code == 400


def test_create_requires_caller_to_be_a_party(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    stranger = make_user(db_session, "x1")

    resp = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(stranger))

    assert resp.status_code == 403


def test_create_404_on_missing_listing(client, db_session):
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    payload = {
        "listing_id": 999999,
        "buyer_id": buyer.id,
        "floor_price": 40000.0,
        "cap_price": 60000.0,
        "prepaid_amount": 45000.0,
        "trigger_event": "holding_period_expiration",
        "seller_attests_no_governing_document_prohibition": True,
    }

    resp = client.post("/forward-sale-contracts", params=payload, headers=auth_headers(buyer))

    assert resp.status_code == 404


def test_create_requires_auth(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")

    resp = client.post("/forward-sale-contracts", params=base_payload(listing, buyer))

    assert resp.status_code == 401


# --- PUT /forward-sale-contracts/{id}/accept ---

def test_buyer_can_accept_a_seller_proposed_contract(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(buyer))

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "accepted"
    assert data["accepted_at"] is not None


def test_proposer_cannot_accept_their_own_proposal(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(seller))

    assert resp.status_code == 400


def test_non_party_cannot_accept(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    stranger = make_user(db_session, "x1")
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(stranger))

    assert resp.status_code == 403


def test_cannot_accept_already_accepted_contract(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()
    client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(buyer))

    resp = client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(buyer))

    assert resp.status_code == 400


# --- PUT /forward-sale-contracts/{id}/cancel ---

def test_either_party_can_cancel_a_proposed_contract(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(f"/forward-sale-contracts/{created['id']}/cancel", headers=auth_headers(buyer))

    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_non_party_cannot_cancel(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    stranger = make_user(db_session, "x1")
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(f"/forward-sale-contracts/{created['id']}/cancel", headers=auth_headers(stranger))

    assert resp.status_code == 403


def test_cannot_cancel_a_settled_contract(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    admin = make_user(db_session, "a1", account_type="admin")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()
    client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(buyer))
    client.put(f"/forward-sale-contracts/{created['id']}/settle", params={"final_price": 50000.0}, headers=auth_headers(admin))

    resp = client.put(f"/forward-sale-contracts/{created['id']}/cancel", headers=auth_headers(seller))

    assert resp.status_code == 400


# --- PUT /forward-sale-contracts/{id}/governing-document-review ---

def test_admin_can_record_governing_document_review(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    admin = make_user(db_session, "a1", account_type="admin")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(
        f"/forward-sale-contracts/{created['id']}/governing-document-review",
        params={"review_status": "reviewed_ok", "review_notes": "Bylaws checked by counsel, no transfer-restriction conflict found"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["governing_document_review_status"] == "reviewed_ok"
    assert "counsel" in data["governing_document_review_notes"]


def test_non_admin_cannot_record_governing_document_review(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(
        f"/forward-sale-contracts/{created['id']}/governing-document-review",
        params={"review_status": "reviewed_ok"},
        headers=auth_headers(seller),
    )

    assert resp.status_code == 403


def test_review_rejects_invalid_status_value(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    admin = make_user(db_session, "a1", account_type="admin")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(
        f"/forward-sale-contracts/{created['id']}/governing-document-review",
        params={"review_status": "looks_fine_to_me"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400


# --- PUT /forward-sale-contracts/{id}/settle ---

def test_admin_can_settle_accepted_contract_within_price_range(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    admin = make_user(db_session, "a1", account_type="admin")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()
    client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(buyer))

    resp = client.put(
        f"/forward-sale-contracts/{created['id']}/settle",
        params={"final_price": 50000.0, "settlement_notes": "IPO priced shares at 50000/unit"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "settled"
    assert data["final_price"] == 50000.0
    assert data["final_quantity"] == pytest.approx(45000.0 / 50000.0)
    assert data["settled_at"] is not None


def test_settle_rejects_price_outside_floor_cap_range(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    admin = make_user(db_session, "a1", account_type="admin")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()
    client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(buyer))

    resp = client.put(
        f"/forward-sale-contracts/{created['id']}/settle",
        params={"final_price": 100000.0},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400


def test_settle_requires_admin(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()
    client.put(f"/forward-sale-contracts/{created['id']}/accept", headers=auth_headers(buyer))

    resp = client.put(
        f"/forward-sale-contracts/{created['id']}/settle",
        params={"final_price": 50000.0},
        headers=auth_headers(buyer),
    )

    assert resp.status_code == 403


def test_settle_requires_accepted_status(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    admin = make_user(db_session, "a1", account_type="admin")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.put(
        f"/forward-sale-contracts/{created['id']}/settle",
        params={"final_price": 50000.0},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400


# --- GET /forward-sale-contracts ---

def test_party_sees_own_contracts_only(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller))
    other_seller = make_user(db_session, "s2", role="seller")
    other_listing = make_listing(db_session, other_seller)
    other_buyer = make_user(db_session, "b2")
    make_verified_ecp(db_session, other_buyer)
    client.post("/forward-sale-contracts", params=base_payload(other_listing, other_buyer), headers=auth_headers(other_seller))

    resp = client.get("/forward-sale-contracts", headers=auth_headers(seller))

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["seller_id"] == seller.id


def test_admin_sees_all_contracts(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    admin = make_user(db_session, "a1", account_type="admin")
    make_verified_ecp(db_session, buyer)
    client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller))

    resp = client.get("/forward-sale-contracts", headers=auth_headers(admin))

    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_requires_auth(client, db_session):
    resp = client.get("/forward-sale-contracts")

    assert resp.status_code == 401


# --- GET /forward-sale-contracts/{id} ---

def test_party_can_get_contract_by_id(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.get(f"/forward-sale-contracts/{created['id']}", headers=auth_headers(buyer))

    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_non_party_gets_404_not_403_on_get_by_id(client, db_session):
    seller = make_user(db_session, "s1", role="seller")
    listing = make_listing(db_session, seller)
    buyer = make_user(db_session, "b1")
    make_verified_ecp(db_session, buyer)
    stranger = make_user(db_session, "x1")
    created = client.post("/forward-sale-contracts", params=base_payload(listing, buyer), headers=auth_headers(seller)).json()

    resp = client.get(f"/forward-sale-contracts/{created['id']}", headers=auth_headers(stranger))

    assert resp.status_code == 404


def test_get_by_id_404_when_missing(client, db_session):
    seller = make_user(db_session, "s1")

    resp = client.get("/forward-sale-contracts/999999", headers=auth_headers(seller))

    assert resp.status_code == 404
