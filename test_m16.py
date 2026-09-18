"""
Tests for M16 (Demand Heatmap / Blind Demand Curve) - written against the
REAL ~/KEVO implementation (2026-09-09). M16's own implementation summary
(claude/kevo-m16-implementation-summary.md) claims "15 tests in test_app.py,
all passing" - that file does not exist anywhere in this repo. This is the
first real test coverage this feature has ever had.

Also covers a real bug found and fixed this session: build_demand_curve()
merges trailing under-threshold buyers into the last displayed point (to
avoid showing a group too small to be anonymous) but was not adding their
desired_quantity into that point's cumulative_quantity - understating real
demand at the low end of the curve, in direct violation of the design's
own rule that this feature must never show a number that misrepresents
real demand. test_curve_trailing_merge_includes_full_cumulative_quantity
is the regression test for that fix.

Runs against an isolated in-memory SQLite database, same pattern as
test_m13.py / test_m14.py - does not touch the real Postgres config.
"""

import os

os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "kevo_test_placeholder")
os.environ.setdefault("DB_USER", "kevo_test_placeholder")
os.environ.setdefault("DB_PASSWORD", "kevo_test_placeholder")

import itertools
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base, User as UserModel, BuyerInterest
from app import app, get_db, build_demand_heatmap, build_demand_curve

_email_counter = itertools.count(1)


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


def make_buyer(db, jurisdiction=None):
    n = next(_email_counter)
    user = UserModel(
        name=f"Buyer{n}",
        email=f"buyer{n}@example.com",
        role="buyer",
        jurisdiction=jurisdiction,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_interest(db, buyer_id, company="Acme Inc", asset_type="Private Shares",
                   desired_quantity=100, maximum_price=50.0, status="active"):
    interest = BuyerInterest(
        buyer_id=buyer_id,
        company=company,
        asset_type=asset_type,
        desired_quantity=desired_quantity,
        maximum_price=maximum_price,
        status=status,
    )
    db.add(interest)
    db.commit()
    db.refresh(interest)
    return interest


def make_n_buyers_with_interest(db, n, jurisdiction=None, **interest_kwargs):
    """Creates n distinct buyers, each with one active BuyerInterest."""
    buyers = []
    for _ in range(n):
        b = make_buyer(db, jurisdiction=jurisdiction)
        make_interest(db, b.id, **interest_kwargs)
        buyers.append(b)
    return buyers


# ---------------------------------------------------------------------------
# build_demand_heatmap - anonymization gate
# ---------------------------------------------------------------------------

def test_heatmap_insufficient_data_when_fewer_than_5_buyers(db_session):
    make_n_buyers_with_interest(db_session, 4, maximum_price=50.0)

    result = build_demand_heatmap("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "insufficient_data"


def test_heatmap_ok_with_exactly_5_buyers_same_price_same_jurisdiction(db_session):
    make_n_buyers_with_interest(db_session, 5, jurisdiction="United States",
                                 maximum_price=50.0, desired_quantity=100)

    result = build_demand_heatmap("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "ok"
    assert len(result["cells"]) == 1
    cell = result["cells"][0]
    assert cell["jurisdiction"] == "United States"
    assert cell["buyer_count"] == 5
    assert cell["total_desired_quantity"] == 500
    assert cell["price_band_low"] == 50.0
    assert cell["price_band_high"] == 50.0


# ---------------------------------------------------------------------------
# suppression: pool across jurisdictions within a band before widening bands
# ---------------------------------------------------------------------------

def test_heatmap_pools_thin_jurisdictions_within_same_band(db_session):
    # Same price -> single band. 3 US + 2 Canada, each thin alone, 5 combined.
    make_n_buyers_with_interest(db_session, 3, jurisdiction="United States",
                                 maximum_price=50.0, desired_quantity=100)
    make_n_buyers_with_interest(db_session, 2, jurisdiction="Canada",
                                 maximum_price=50.0, desired_quantity=100)

    result = build_demand_heatmap("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "ok"
    assert len(result["cells"]) == 1
    cell = result["cells"][0]
    assert cell["jurisdiction"] is None  # jurisdiction split dropped
    assert cell["buyer_count"] == 5
    assert cell["total_desired_quantity"] == 500


def test_heatmap_widens_price_band_when_still_thin_after_jurisdiction_pool(db_session):
    # Two distinct prices -> two bands (10 and 20 split at their midpoint).
    # 2 buyers at the low price, 3 at the high price - each band thin alone,
    # 5 combined once bands are merged.
    make_n_buyers_with_interest(db_session, 2, jurisdiction="United States",
                                 maximum_price=10.0, desired_quantity=100)
    make_n_buyers_with_interest(db_session, 3, jurisdiction="United States",
                                 maximum_price=20.0, desired_quantity=100)

    result = build_demand_heatmap("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "ok"
    assert len(result["cells"]) == 1
    cell = result["cells"][0]
    assert cell["jurisdiction"] is None
    assert cell["buyer_count"] == 5
    assert cell["total_desired_quantity"] == 500
    assert cell["price_band_low"] == 10.0
    assert cell["price_band_high"] == 20.0


def test_heatmap_drops_residual_that_never_reaches_threshold(db_session):
    # Band at price=10: 5 US buyers on their own -> published directly.
    # Band at price=20: 2 Canada buyers -> thin, nothing left to merge with
    # (last band), must be dropped entirely, not grafted onto the first cell.
    make_n_buyers_with_interest(db_session, 5, jurisdiction="United States",
                                 maximum_price=10.0, desired_quantity=100)
    make_n_buyers_with_interest(db_session, 2, jurisdiction="Canada",
                                 maximum_price=20.0, desired_quantity=100)

    result = build_demand_heatmap("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "ok"
    # Only the valid 5-buyer cell appears; the 2 Canada buyers are nowhere.
    assert len(result["cells"]) == 1
    cell = result["cells"][0]
    assert cell["jurisdiction"] == "United States"
    assert cell["buyer_count"] == 5
    assert cell["price_band_low"] == 10.0
    assert cell["price_band_high"] == 15.0
    total_buyers_shown = sum(c["buyer_count"] for c in result["cells"])
    assert total_buyers_shown == 5  # the 2 dropped buyers are not counted anywhere


# ---------------------------------------------------------------------------
# filtering: active-only, company/asset_type scoping
# ---------------------------------------------------------------------------

def test_heatmap_excludes_non_active_interests(db_session):
    make_n_buyers_with_interest(db_session, 4, jurisdiction="United States",
                                 maximum_price=50.0, status="active")
    make_n_buyers_with_interest(db_session, 3, jurisdiction="United States",
                                 maximum_price=50.0, status="withdrawn")

    # 7 total rows exist, but only 4 are active -> still insufficient_data.
    result = build_demand_heatmap("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "insufficient_data"


def test_heatmap_scopes_strictly_by_company_and_asset_type(db_session):
    make_n_buyers_with_interest(db_session, 5, jurisdiction="United States",
                                 company="Acme Inc", asset_type="Private Shares",
                                 maximum_price=50.0, desired_quantity=100)
    # Same company, different asset_type - must not leak in.
    make_n_buyers_with_interest(db_session, 5, jurisdiction="United States",
                                 company="Acme Inc", asset_type="Preferred Shares",
                                 maximum_price=50.0, desired_quantity=100)
    # Different company entirely.
    make_n_buyers_with_interest(db_session, 1, jurisdiction="United States",
                                 company="Other Co", asset_type="Private Shares",
                                 maximum_price=50.0, desired_quantity=100)

    result = build_demand_heatmap("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "ok"
    total_buyers_shown = sum(c["buyer_count"] for c in result["cells"])
    assert total_buyers_shown == 5  # only the Acme/Private Shares group

    other = build_demand_heatmap("Other Co", "Private Shares", db_session)
    assert other["status"] == "insufficient_data"  # only 1 buyer there


# ---------------------------------------------------------------------------
# build_demand_curve - anonymization gate and cumulative correctness
# ---------------------------------------------------------------------------

def test_curve_insufficient_data_when_fewer_than_5_buyers(db_session):
    make_n_buyers_with_interest(db_session, 4, maximum_price=50.0)

    result = build_demand_curve("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "insufficient_data"


def test_curve_single_point_when_top_price_group_alone_clears_threshold(db_session):
    make_n_buyers_with_interest(db_session, 5, maximum_price=100.0, desired_quantity=20)

    result = build_demand_curve("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "ok"
    assert len(result["points"]) == 1
    point = result["points"][0]
    assert point["price_at_or_above"] == 100.0
    assert point["cumulative_quantity"] == 100
    assert point["distinct_buyers_in_step"] == 5


def test_curve_cumulative_quantity_is_monotonic_across_points(db_session):
    make_n_buyers_with_interest(db_session, 5, maximum_price=100.0, desired_quantity=20)
    make_n_buyers_with_interest(db_session, 5, maximum_price=90.0, desired_quantity=20)

    result = build_demand_curve("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "ok"
    assert len(result["points"]) == 2
    assert result["points"][0]["price_at_or_above"] == 100.0
    assert result["points"][0]["cumulative_quantity"] == 100
    assert result["points"][1]["price_at_or_above"] == 90.0
    assert result["points"][1]["cumulative_quantity"] == 200
    assert result["points"][1]["cumulative_quantity"] > result["points"][0]["cumulative_quantity"]


def test_curve_trailing_merge_includes_full_cumulative_quantity(db_session):
    # THE BUG FIX REGRESSION TEST.
    # price=100: 3 buyers (thin) -> no emit.
    # price=90: 3 more buyers -> pool reaches 6 -> emits a point with
    #   cumulative_quantity=60 at this moment.
    # price=80: 2 more buyers (thin, trailing, nothing left to merge with)
    #   -> gets folded into the last point instead of shown on its own.
    # Real total demand across all three groups is 30+30+20=80. Before the
    # fix, the last point's cumulative_quantity stayed frozen at 60 -
    # silently dropping the trailing group's 20 units of real demand.
    make_n_buyers_with_interest(db_session, 3, maximum_price=100.0, desired_quantity=10)
    make_n_buyers_with_interest(db_session, 3, maximum_price=90.0, desired_quantity=10)
    make_n_buyers_with_interest(db_session, 2, maximum_price=80.0, desired_quantity=10)

    result = build_demand_curve("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "ok"
    assert len(result["points"]) == 1  # the trailing group merged into the one point
    point = result["points"][0]
    assert point["price_at_or_above"] == 80.0  # extended down to the lowest merged price
    assert point["distinct_buyers_in_step"] == 8  # 3 + 3 + 2
    assert point["cumulative_quantity"] == 80  # the actual fix: full total, not 60


def test_curve_excludes_non_active_interests(db_session):
    make_n_buyers_with_interest(db_session, 4, maximum_price=50.0, status="active")
    make_n_buyers_with_interest(db_session, 3, maximum_price=50.0, status="fulfilled")

    result = build_demand_curve("Acme Inc", "Private Shares", db_session)
    assert result["status"] == "insufficient_data"


# ---------------------------------------------------------------------------
# HTTP endpoints - confirm they're wired to the same functions
# ---------------------------------------------------------------------------

def test_get_demand_heatmap_endpoint(db_session):
    make_n_buyers_with_interest(db_session, 5, jurisdiction="United States",
                                 maximum_price=50.0, desired_quantity=100)
    client = TestClient(app)

    response = client.get("/demand-heatmap", params={"company": "Acme Inc", "asset_type": "Private Shares"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert len(body["cells"]) == 1
    assert body["cells"][0]["buyer_count"] == 5


def test_get_demand_curve_endpoint(db_session):
    make_n_buyers_with_interest(db_session, 3, maximum_price=100.0, desired_quantity=10)
    client = TestClient(app)

    response = client.get("/demand-curve", params={"company": "Acme Inc", "asset_type": "Private Shares"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_data"  # only 3 buyers total
