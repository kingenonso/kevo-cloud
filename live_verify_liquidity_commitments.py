import requests
from datetime import date

BASE = "http://127.0.0.1:8000"

def signup_and_login(email, role="buyer"):
    signup_payload = {
        "name": f"Test {email}",
        "email": email,
        "password": "testpass123",
        "role": role,
        "jurisdiction": "US",
        "phone_number": "5555550100",
        "date_of_birth": "1990-01-01",
        "terms_accepted": True,
    }
    r = requests.post(f"{BASE}/users", json=signup_payload)
    assert r.status_code == 200, f"signup failed: {r.status_code} {r.text}"
    raw = r.json()
    user = raw.get("user", raw)
    if "id" not in user:
        print(f"DEBUG signup response for {email}: {raw}")
        raise SystemExit("Unexpected signup response shape - see DEBUG line above")

    login_r = requests.post(f"{BASE}/login", json={"email": email, "password": "testpass123"})
    assert login_r.status_code == 200, f"login failed: {login_r.status_code} {login_r.text}"
    token = login_r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return user, headers

buyer1, buyer1_headers = signup_and_login("liq_buyer1b@example.com")
buyer2, buyer2_headers = signup_and_login("liq_buyer2b@example.com")
print("Buyer 1 and Buyer 2 created")

# --- create: buyer creates own commitment ---
payload = {
    "buyer_id": buyer1["id"],
    "company": "Acme Corp",
    "asset_type": "common_stock",
    "min_quantity": 100,
    "max_quantity": 1000,
    "min_price": 5.00,
    "max_price": 12.50,
    "expiration_date": str(date(2027, 1, 1)),
    "conditions": "Only if company completes next funding round",
}
r = requests.post(f"{BASE}/liquidity-commitments", json=payload, headers=buyer1_headers)
assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
commitment = r.json()
assert commitment["buyer_id"] == buyer1["id"]
assert "disclaimer" in commitment and "non-binding" in commitment["disclaimer"]
assert commitment["status"] == "active"
commitment_id = commitment["id"]
print(f"Buyer 1 created commitment {commitment_id}: 200 OK, disclaimer present, status=active")

# --- create: cannot create for another buyer ---
bad_payload = dict(payload, buyer_id=buyer2["id"])
r = requests.post(f"{BASE}/liquidity-commitments", json=bad_payload, headers=buyer1_headers)
assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"
print("Buyer 1 attempting to create for Buyer 2: 403 correctly blocked")

# --- create: min > max quantity -> 400 ---
bad_qty = dict(payload, min_quantity=500, max_quantity=100)
r = requests.post(f"{BASE}/liquidity-commitments", json=bad_qty, headers=buyer1_headers)
assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
print("min_quantity > max_quantity: 400 correctly rejected")

# --- create: min > max price -> 400 ---
bad_price = dict(payload, min_price=50.00, max_price=10.00)
r = requests.post(f"{BASE}/liquidity-commitments", json=bad_price, headers=buyer1_headers)
assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"
print("min_price > max_price: 400 correctly rejected")

# --- create: unauthenticated -> 401 ---
r = requests.post(f"{BASE}/liquidity-commitments", json=payload)
assert r.status_code == 401, f"expected 401, got {r.status_code} {r.text}"
print("Unauthenticated create: 401 correctly blocked")

# --- buyer2 creates their own commitment too, for scoping check ---
payload2 = dict(payload, buyer_id=buyer2["id"], company="Beta Inc")
r = requests.post(f"{BASE}/liquidity-commitments", json=payload2, headers=buyer2_headers)
assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
commitment2_id = r.json()["id"]
print(f"Buyer 2 created commitment {commitment2_id}")

# --- list: scoped to own ---
r = requests.get(f"{BASE}/liquidity-commitments", headers=buyer1_headers)
assert r.status_code == 200
ids = [c["id"] for c in r.json()]
assert commitment_id in ids
assert commitment2_id not in ids
print("Buyer 1 list: sees own commitment only, not Buyer 2's")

# --- get: owner can view ---
r = requests.get(f"{BASE}/liquidity-commitments/{commitment_id}", headers=buyer1_headers)
assert r.status_code == 200
print("Buyer 1 viewing own commitment: 200 OK")

# --- get: stranger cannot view ---
r = requests.get(f"{BASE}/liquidity-commitments/{commitment_id}", headers=buyer2_headers)
assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"
print("Buyer 2 viewing Buyer 1's commitment: 403 correctly blocked")

# --- get: not found ---
r = requests.get(f"{BASE}/liquidity-commitments/999999", headers=buyer1_headers)
assert r.status_code == 404
print("Unknown commitment id: 404 correctly returned")

# --- withdraw: stranger cannot withdraw ---
r = requests.put(f"{BASE}/liquidity-commitments/{commitment_id}/withdraw", headers=buyer2_headers)
assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text}"
print("Buyer 2 attempting to withdraw Buyer 1's commitment: 403 correctly blocked")

# --- withdraw: owner can withdraw ---
r = requests.put(f"{BASE}/liquidity-commitments/{commitment_id}/withdraw", headers=buyer1_headers)
assert r.status_code == 200, f"withdraw failed: {r.status_code} {r.text}"
assert r.json()["status"] == "withdrawn"
print("Buyer 1 withdrawing own commitment: 200 OK, status=withdrawn")

print("\nALL LIVE CHECKS PASSED")
