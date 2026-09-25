import requests, random
from datetime import date, datetime
from database import SessionLocal
from models import User as UserModel

BASE = "http://127.0.0.1:8000"
suffix = random.randint(100000, 999999)

def make_user(name_suffix, role="buyer", jurisdiction="NG"):
    email = f"live{suffix}{name_suffix}@example.com"
    r = requests.post(f"{BASE}/users", json={
        "name": f"Live {name_suffix}", "email": email, "role": role,
        "password": "testpass123",
        "phone_number": "+2348000000000",
        "date_of_birth": "1990-01-01",
        "jurisdiction": jurisdiction,
        "terms_accepted": True,
    })
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    r2 = requests.post(f"{BASE}/login", json={"email": email, "password": "testpass123"})
    assert r2.status_code == 200, r2.text
    token = r2.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "email": email, **user}

def make_admin(name_suffix):
    from app import hash_password
    email = f"live{suffix}{name_suffix}@example.com"
    db = SessionLocal()
    admin_row = UserModel(
        name="Live Admin", email=email, role="admin", account_type="admin",
        kyc_status="not_started", hashed_password=hash_password("testpass123"),
        phone_number="+2348000000001",
        date_of_birth=date(1990, 1, 1),
        jurisdiction="NG",
        terms_accepted=True,
        terms_accepted_at=datetime.utcnow(),
    )
    db.add(admin_row)
    db.commit()
    db.refresh(admin_row)
    admin_id = admin_row.id
    db.close()
    r2 = requests.post(f"{BASE}/login", json={"email": email, "password": "testpass123"})
    assert r2.status_code == 200, r2.text
    token = r2.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "id": admin_id}

seller = make_user("seller", role="seller")
buyer = make_user("buyer", role="buyer", jurisdiction="United States")
admin = make_admin("admin")
print("Created seller id=%s buyer id=%s admin id=%s" % (seller["id"], buyer["id"], admin["id"]))

r = requests.put(f"{BASE}/users/{buyer['id']}/kyc-status", headers=admin["headers"], params={"status": "verified"})
assert r.status_code == 200, r.text
print("Buyer KYC verified OK")

r = requests.post(f"{BASE}/listings", headers=seller["headers"], json={
    "seller_id": seller["id"], "company": f"RuleAlertCo{suffix}", "asset_type": "common_stock",
    "quantity": 1000, "asking_price": 50.0, "is_transferable": True,
    "issuer_jurisdiction": "United States",
    "issuer_reporting_status": "reporting",
})
assert r.status_code == 200, r.text
listing = r.json()["listing"]
print("Listing id=%s issuer_reporting_status=%s" % (listing["id"], listing.get("issuer_reporting_status")))

rule_code = f"LIVE-RULE-ALERT-{suffix}"
r = requests.post(f"{BASE}/compliance-rules", headers=admin["headers"], json={
    "buyer_jurisdiction": "United States",
    "issuer_jurisdiction": "United States",
    "asset_type": "common_stock",
    "rule_code": rule_code,
    "description": "Live test rule - not real regulatory content.",
    "fact_type": "issuer_reporting_status",
    "requirement": "non-reporting",
    "decision_if_unmet": "blocked",
    "active": True,
    "source_reference": "Live test fixture only",
})
assert r.status_code == 200, r.text
rule = r.json()["compliance_rule"]
print("Rule id=%s code=%s" % (rule["id"], rule["rule_code"]))

r = requests.post(f"{BASE}/transactions", headers=buyer["headers"], json={
    "listing_id": listing["id"], "buyer_id": buyer["id"], "quantity": 100, "agreed_price": 10000.0
})
assert r.status_code == 200, r.text
txn = r.json()["transaction"]
print("Transaction id=%s status=%s" % (txn["id"], txn["status"]))

db = SessionLocal()
from models import ComplianceDecisionLedger
entry = db.query(ComplianceDecisionLedger).filter(ComplianceDecisionLedger.transaction_id == txn["id"]).first()
print("Ledger decision_status at creation:", entry.decision_status)
assert entry.decision_status == "blocked", f"expected blocked, got {entry.decision_status}"
db.close()

r = requests.get(f"{BASE}/rule-change-alerts", headers=admin["headers"])
assert r.status_code == 200, r.text
assert len([a for a in r.json()["alerts"] if a["transaction_id"] == txn["id"]]) == 0
print("No alerts yet, as expected")

r = requests.put(f"{BASE}/compliance-rules/{rule['id']}", headers=admin["headers"], json={
    "active": False,
})
assert r.status_code == 200, r.text
print("Rule deactivated")

r = requests.get(f"{BASE}/rule-change-alerts", headers=admin["headers"])
assert r.status_code == 200, r.text
matching = [a for a in r.json()["alerts"] if a["transaction_id"] == txn["id"]]
assert len(matching) == 1, f"expected exactly 1 alert for this transaction, got {len(matching)}"
alert = matching[0]
print("Alert:", alert)
assert alert["previous_decision_status"] == "blocked"
assert alert["new_decision_status"] != "blocked"
assert alert["buyer_id"] == buyer["id"]
assert alert["is_read"] is False

r = requests.get(f"{BASE}/rule-change-alerts", headers=buyer["headers"])
assert r.status_code == 200, r.text
buyer_alerts = r.json()["alerts"]
assert len(buyer_alerts) == 1
assert buyer_alerts[0]["id"] == alert["id"]
print("Buyer sees own alert OK")

r = requests.put(f"{BASE}/rule-change-alerts/{alert['id']}/mark-read", headers=buyer["headers"])
assert r.status_code == 200, r.text
assert r.json()["is_read"] is True
print("Buyer marked alert read OK")

r = requests.put(f"{BASE}/compliance-rules/{rule['id']}", headers=admin["headers"], json={
    "description": "Second edit, still inactive, same verdict as before.",
})
assert r.status_code == 200, r.text

r = requests.get(f"{BASE}/rule-change-alerts", headers=admin["headers"])
assert r.status_code == 200, r.text
matching_after = [a for a in r.json()["alerts"] if a["transaction_id"] == txn["id"]]
assert len(matching_after) == 1, f"expected still exactly 1 alert, got {len(matching_after)}"
print("No duplicate alert on an unrelated edit OK")

print("\nALL LIVE CHECKS PASSED")
