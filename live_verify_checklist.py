import requests, random
from datetime import date, datetime
from database import SessionLocal
from models import User as UserModel

BASE = "http://127.0.0.1:8000"
suffix = random.randint(100000, 999999)

def make_user(name_suffix, role="buyer"):
    email = f"live{suffix}{name_suffix}@example.com"
    r = requests.post(f"{BASE}/users", json={
        "name": f"Live {name_suffix}", "email": email, "role": role,
        "password": "testpass123",
        "phone_number": "+2348000000000",
        "date_of_birth": "1990-01-01",
        "jurisdiction": "NG",
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
buyer = make_user("buyer", role="buyer")
stranger = make_user("stranger", role="buyer")
admin = make_admin("admin")
print("Created seller id=%s buyer id=%s stranger id=%s admin id=%s" % (seller["id"], buyer["id"], stranger["id"], admin["id"]))

r = requests.post(f"{BASE}/listings", headers=seller["headers"], json={
    "seller_id": seller["id"], "company": f"ChecklistCo{suffix}", "asset_type": "Private Shares",
    "quantity": 1000, "asking_price": 50.0, "is_transferable": True,
})
assert r.status_code == 200, r.text
listing = r.json()["listing"]
print("Listing id=%s" % listing["id"])

r = requests.post(f"{BASE}/transactions", headers=buyer["headers"], json={
    "listing_id": listing["id"], "buyer_id": buyer["id"], "quantity": 100, "agreed_price": 10000.0
})
assert r.status_code == 200, r.text
txn = r.json()["transaction"]
print("Transaction id=%s status=%s" % (txn["id"], txn["status"]))

r = requests.post(f"{BASE}/transactions/999999999/checklist-items", headers=buyer["headers"], json={
    "description": "Should not exist",
})
assert r.status_code == 404, r.text
print("404 for unknown transaction OK")

r = requests.post(f"{BASE}/transactions/{txn['id']}/checklist-items", headers=buyer["headers"], json={
    "description": "Confirm title documents", "source_reference": "Live test item 1",
})
assert r.status_code == 200, r.text
item = r.json()
print("Checklist item created:", item)
assert item["status"] == "pending"
assert item["created_by_user_id"] == buyer["id"]

r = requests.get(f"{BASE}/transactions/{txn['id']}/checklist-items", headers=stranger["headers"])
assert r.status_code == 403, r.text
print("Stranger GET correctly blocked (403)")

r = requests.put(f"{BASE}/checklist-items/{item['id']}", headers=stranger["headers"], params={"status": "complete"})
assert r.status_code == 403, r.text
print("Stranger PUT correctly blocked (403)")

r = requests.get(f"{BASE}/transactions/{txn['id']}/checklist-items", headers=seller["headers"])
assert r.status_code == 200, r.text
items = r.json()
assert len(items) == 1 and items[0]["id"] == item["id"]
print("Seller GET sees the item OK")

r = requests.put(f"{BASE}/checklist-items/{item['id']}", headers=seller["headers"], params={"status": "complete"})
assert r.status_code == 200, r.text
completed = r.json()
print("Completed by seller:", completed)
assert completed["status"] == "complete"
assert completed["completed_by_user_id"] == seller["id"]
assert completed["completed_at"] is not None

r = requests.post(f"{BASE}/transactions/{txn['id']}/checklist-items", headers=admin["headers"], json={
    "description": "Confirm compliance sign-off",
})
assert r.status_code == 200, r.text
item2 = r.json()
assert item2["created_by_user_id"] == admin["id"]

r = requests.put(f"{BASE}/checklist-items/{item2['id']}", headers=admin["headers"], params={"status": "not_applicable"})
assert r.status_code == 200, r.text
assert r.json()["status"] == "not_applicable"
print("Admin create + update OK")

r = requests.get(f"{BASE}/transactions/{txn['id']}/checklist-items", headers=buyer["headers"])
assert r.status_code == 200, r.text
final_items = r.json()
assert len(final_items) == 2
print("Final checklist:", [(i["id"], i["status"]) for i in final_items])

print("\nALL LIVE CHECKS PASSED")
