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
buyer1 = make_user("buyer1", role="buyer")
buyer2 = make_user("buyer2", role="buyer")
admin = make_admin("admin")
print("Created seller id=%s buyer1 id=%s buyer2 id=%s admin id=%s" % (seller["id"], buyer1["id"], buyer2["id"], admin["id"]))

r = requests.post(f"{BASE}/listings", headers=seller["headers"], json={
    "seller_id": seller["id"], "company": f"AuctionCo{suffix}", "asset_type": "Private Shares",
    "quantity": 1000, "asking_price": 50.0, "is_transferable": True,
})
assert r.status_code == 200, r.text
listing = r.json()["listing"]
print("Listing id=%s" % listing["id"])

# Seller cannot bid on their own listing
r = requests.post(f"{BASE}/listings/{listing['id']}/auction-bids", headers=seller["headers"], json={
    "quantity": 100, "bid_price": 55.0,
})
assert r.status_code == 403, r.text
print("Seller blocked from bidding on own listing (403) OK")

# Two buyers submit sealed bids
r = requests.post(f"{BASE}/listings/{listing['id']}/auction-bids", headers=buyer1["headers"], json={
    "quantity": 100, "bid_price": 55.0, "note": "Can close within a week",
})
assert r.status_code == 200, r.text
bid1 = r.json()
print("Bid 1 (buyer1):", bid1)

r = requests.post(f"{BASE}/listings/{listing['id']}/auction-bids", headers=buyer2["headers"], json={
    "quantity": 80, "bid_price": 58.0,
})
assert r.status_code == 200, r.text
bid2 = r.json()
print("Bid 2 (buyer2):", bid2)

# Sealed: buyer1 cannot see buyer2's bid, and vice versa
r = requests.get(f"{BASE}/listings/{listing['id']}/auction-bids", headers=buyer1["headers"])
assert r.status_code == 200, r.text
buyer1_view = r.json()
assert len(buyer1_view) == 1 and buyer1_view[0]["id"] == bid1["id"]
print("Buyer1 sees only their own bid OK (sealed)")

r = requests.get(f"{BASE}/listings/{listing['id']}/auction-bids", headers=buyer2["headers"])
assert r.status_code == 200, r.text
buyer2_view = r.json()
assert len(buyer2_view) == 1 and buyer2_view[0]["id"] == bid2["id"]
print("Buyer2 sees only their own bid OK (sealed)")

# Seller sees both
r = requests.get(f"{BASE}/listings/{listing['id']}/auction-bids", headers=seller["headers"])
assert r.status_code == 200, r.text
seller_view = r.json()
assert len(seller_view) == 2
print("Seller sees all %d bids OK" % len(seller_view))

# Seller rejects buyer1's bid, accepts buyer2's higher bid
r = requests.put(f"{BASE}/auction-bids/{bid1['id']}/reject", headers=seller["headers"])
assert r.status_code == 200, r.text
print("Bid 1 rejected:", r.json()["status"])

r = requests.put(f"{BASE}/auction-bids/{bid2['id']}/accept", headers=seller["headers"])
assert r.status_code == 200, r.text
accepted = r.json()
print("Bid 2 accepted:", accepted)
txn_id = accepted["resulting_transaction_id"]
assert txn_id is not None

# Confirm a real transaction now exists with the bid's own terms
r = requests.get(f"{BASE}/transactions/{txn_id}/status", headers=seller["headers"]) if False else None
db = SessionLocal()
from models import Transaction
txn = db.query(Transaction).filter(Transaction.id == txn_id).first()
assert txn is not None
assert txn.buyer_id == buyer2["id"]
assert txn.seller_id == seller["id"]
assert txn.quantity == 80
assert float(txn.agreed_price) == 58.0
assert txn.status == "accepted"
db.close()
print("Real transaction id=%s buyer=%s quantity=%s price=%s status=%s" % (
    txn.id, txn.buyer_id, txn.quantity, txn.agreed_price, txn.status))

# Can't accept an already-decided bid
r = requests.put(f"{BASE}/auction-bids/{bid2['id']}/accept", headers=seller["headers"])
assert r.status_code == 400, r.text
print("Re-accepting a decided bid correctly blocked (400)")

# Buyer1 can withdraw... but it's already rejected, so withdraw should fail
r = requests.put(f"{BASE}/auction-bids/{bid1['id']}/withdraw", headers=buyer1["headers"])
assert r.status_code == 400, r.text
print("Withdrawing an already-rejected bid correctly blocked (400)")

print("\nALL LIVE CHECKS PASSED")
