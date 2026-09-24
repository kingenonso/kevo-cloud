import requests

BASE = "http://127.0.0.1:8000"

r = requests.post(f"{BASE}/login", json={"email": "authtest@kevo.local", "password": "AdminTest2026x"})
admin_token = r.json()["access_token"]
admin_headers = {"Authorization": f"Bearer {admin_token}"}

r = requests.get(f"{BASE}/transactions", headers=admin_headers)
print("transactions available:", r.status_code)
transactions = r.json()
tx_list = transactions if isinstance(transactions, list) else transactions.get("transactions", [])
print("count:", len(tx_list))
if tx_list:
    sample = tx_list[0]
    print("sample transaction:", sample)

if tx_list:
    tx_id = tx_list[0]["id"]

    # 1. Admin, tied to a real transaction, auto-derived valuation, no fees entered
    r = requests.post(f"{BASE}/transaction-cost-estimate", json={"transaction_id": tx_id}, headers=admin_headers)
    print("\n1. admin, real transaction, no fees:", r.status_code, r.json())

    # 2. Admin, tied to a real transaction, with fee inputs
    r = requests.post(f"{BASE}/transaction-cost-estimate", json={
        "transaction_id": tx_id,
        "legal_fee": 500,
        "platform_fee": 0,
        "settlement_fee": 150,
        "custody_fee": 25,
        "fx_fee": 0,
        "transfer_fee": 10,
        "taxes_other": 1000
    }, headers=admin_headers)
    print("\n2. admin, real transaction, with fees:", r.status_code, r.json())

# 3. Non-party, non-admin user should get 403 if transaction exists
r = requests.post(f"{BASE}/users", json={
    "name": "Cost Calc Stranger",
    "email": "costcalc-stranger@kevo.local",
    "password": "StrangerPass2026x",
    "role": "buyer"
})
r = requests.post(f"{BASE}/login", json={"email": "costcalc-stranger@kevo.local", "password": "StrangerPass2026x"})
stranger_token = r.json()["access_token"]
stranger_headers = {"Authorization": f"Bearer {stranger_token}"}

if tx_list:
    r = requests.post(f"{BASE}/transaction-cost-estimate", json={"transaction_id": tx_list[0]["id"]}, headers=stranger_headers)
    print("\n3. non-party stranger (expect 403):", r.status_code, r.json())

# 4. Ad-hoc, no transaction_id, manual headline_valuation
r = requests.post(f"{BASE}/transaction-cost-estimate", json={
    "headline_valuation": 100000,
    "legal_fee": 2000,
    "settlement_fee": 300,
    "taxes_other": 15000
}, headers=stranger_headers)
print("\n4. ad-hoc estimate, no transaction:", r.status_code, r.json())

# 5. No transaction_id AND no headline_valuation - expect 400
r = requests.post(f"{BASE}/transaction-cost-estimate", json={"legal_fee": 500}, headers=stranger_headers)
print("\n5. missing both transaction_id and headline_valuation (expect 400):", r.status_code, r.json())

# 6. Negative fee should be rejected (422)
r = requests.post(f"{BASE}/transaction-cost-estimate", json={"headline_valuation": 1000, "legal_fee": -50}, headers=stranger_headers)
print("\n6. negative fee (expect 422):", r.status_code, r.json())
