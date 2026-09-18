# --- test_dealhealth.py ---
with open("test_dealhealth.py", "r") as f:
    content = f.read()

old_import = '''from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    OwnershipRecord, TransferabilityAssessment, Evidence,
)'''
new_import = '''from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    OwnershipRecord, TransferabilityAssessment, TransferabilityRule, Evidence,
)'''
count = content.count(old_import)
assert count == 1, "dealhealth import: expected 1, found " + str(count)
content = content.replace(old_import, new_import, 1)

old_test = '''def test_regulatory_uncertainty_picks_worst_of_multiple_real_assessments(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    good = TransferabilityAssessment(
        listing_id=listing.id, status="eligible", explanation="all clear"
    )
    bad = TransferabilityAssessment(
        listing_id=listing.id, status="blocked", explanation="holding period not met"
    )
    db_session.add(good)
    db_session.add(bad)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    reg = next(d for d in body["dimensions"] if d["dimension"] == "regulatory_uncertainty")
    assert reg["status"] == "blocked"
    assert reg["reason"] == "holding period not met"'''

new_test = '''def test_regulatory_uncertainty_reflects_live_transferability_status(client, db_session):
    # 2026-09-11 M14 fix: regulatory_uncertainty now calls evaluate_transferability()
    # live instead of reading stored TransferabilityAssessment rows - that table was
    # only ever populated by a write-on-GET bug in /transferability/listing/{id},
    # since there is no real way to create/update facts or evidence through the API.
    transaction, listing, buyer, seller = make_deal(db_session)
    listing.issuer_jurisdiction = "Testland"
    db_session.add(listing)
    db_session.commit()

    rule = TransferabilityRule(
        jurisdiction="Testland", asset_type="Private Shares",
        fact_type="some_required_fact", rule_code="TEST-RULE-REG-1",
        requirement="some required fact must be verified",
        decision_if_unmet="blocked", requires_human_review=True, active=True
    )
    db_session.add(rule)
    db_session.commit()

    response = client.get("/deal-health/transaction/" + str(transaction.id))
    body = response.json()
    reg = next(d for d in body["dimensions"] if d["dimension"] == "regulatory_uncertainty")
    assert reg["determinable"] is True
    assert reg["status"] == "blocked"
    assert "some_required_fact" in reg["reason"]'''

count = content.count(old_test)
assert count == 1, "dealhealth test: expected 1, found " + str(count)
content = content.replace(old_test, new_test, 1)

with open("test_dealhealth.py", "w") as f:
    f.write(content)
print("test_dealhealth.py fixed.")

# --- test_riskradar.py ---
with open("test_riskradar.py", "r") as f:
    content = f.read()

old_import = '''from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    TransferabilityAssessment,
)
from app import app, get_db'''
new_import = '''from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import (
    Base, User as UserModel, Listing as ListingModel, Transaction,
    TransferabilityAssessment, TransferabilityFact, TransferabilityRule,
)
from app import app, get_db'''
count = content.count(old_import)
assert count == 1, "riskradar import: expected 1, found " + str(count)
content = content.replace(old_import, new_import, 1)

old_conflict_test = '''def test_transferability_conflict_flagged_when_real_conflict_exists(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    a = TransferabilityAssessment(
        listing_id=listing.id, status="conflict",
        explanation="conflicting acquisition_date facts"
    )
    db_session.add(a)
    db_session.commit()

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_conflict")
    assert flag["status"] == "flagged"
    assert "conflicting acquisition_date facts" in flag["reason"]'''

new_conflict_test = '''def test_transferability_conflict_flagged_when_real_conflict_exists(client, db_session):
    # 2026-09-11 M14 fix: this flag now calls evaluate_transferability() live
    # instead of reading stored TransferabilityAssessment rows.
    transaction, listing, buyer, seller = make_deal(db_session)
    listing.issuer_jurisdiction = "Testland"
    db_session.add(listing)
    db_session.commit()

    rule = TransferabilityRule(
        jurisdiction="Testland", asset_type="Private Shares",
        fact_type="acquisition_date_source", rule_code="TEST-CONFLICT-1",
        requirement="acquisition_date_source must be verified",
        decision_if_unmet="review", requires_human_review=True, active=True
    )
    db_session.add(rule)
    db_session.commit()

    fact_a = TransferabilityFact(
        listing_id=listing.id, jurisdiction="Testland",
        fact_type="acquisition_date_source", fact_value="2020-01-01",
        verification_status="verified"
    )
    fact_b = TransferabilityFact(
        listing_id=listing.id, jurisdiction="Testland",
        fact_type="acquisition_date_source", fact_value="2021-06-15",
        verification_status="verified"
    )
    db_session.add(fact_a)
    db_session.add(fact_b)
    db_session.commit()

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_conflict")
    assert flag["status"] == "flagged"
    assert "acquisition_date_source" in flag["reason"]'''

count = content.count(old_conflict_test)
assert count == 1, "riskradar conflict test: expected 1, found " + str(count)
content = content.replace(old_conflict_test, new_conflict_test, 1)

old_forecast_test = '''def test_forecast_timing_flagged_when_blocked_assessment_has_real_forecast_date(client, db_session):
    transaction, listing, buyer, seller = make_deal(db_session)
    a = TransferabilityAssessment(
        listing_id=listing.id, status="blocked", explanation="holding period not met",
        forecast_date=date(2027, 1, 30)
    )
    db_session.add(a)
    db_session.commit()

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_forecast_timing")
    assert flag["status"] == "flagged"
    assert "2027-01-30" in flag["reason"]'''

new_forecast_test = '''def test_forecast_timing_flagged_when_blocked_assessment_has_real_forecast_date(client, db_session):
    # 2026-09-11 M14 fix: this flag now calls evaluate_transferability() live
    # instead of reading stored TransferabilityAssessment rows.
    transaction, listing, buyer, seller = make_deal(db_session)
    listing.issuer_jurisdiction = "Testland"
    db_session.add(listing)
    db_session.commit()

    rule = TransferabilityRule(
        jurisdiction="Testland", asset_type="Private Shares",
        fact_type="acquisition_date", rule_code="TEST-HOLD-1",
        requirement="6 month holding period", decision_if_unmet="blocked",
        requires_human_review=True, active=True, hold_period_days=180
    )
    db_session.add(rule)
    db_session.commit()

    acquisition_date = date.today() - timedelta(days=30)
    fact = TransferabilityFact(
        listing_id=listing.id, jurisdiction="Testland",
        fact_type="acquisition_date", fact_value=acquisition_date.isoformat(),
        as_of_date=acquisition_date, verification_status="verified"
    )
    db_session.add(fact)
    db_session.commit()

    expected_forecast_date = acquisition_date + timedelta(days=180)

    response = client.get("/risk-radar/transaction/" + str(transaction.id))
    body = response.json()
    flag = next(f for f in body["flags"] if f["flag_type"] == "transferability_forecast_timing")
    assert flag["status"] == "flagged"
    assert expected_forecast_date.isoformat() in flag["reason"]'''

count = content.count(old_forecast_test)
assert count == 1, "riskradar forecast test: expected 1, found " + str(count)
content = content.replace(old_forecast_test, new_forecast_test, 1)

with open("test_riskradar.py", "w") as f:
    f.write(content)
print("test_riskradar.py fixed.")
