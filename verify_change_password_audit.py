import requests
import time

BASE = "http://127.0.0.1:8000"

ts = int(time.time())
email = f"audit-test-{ts}@kevo.local"
password = "InitialPass2026x"

r = requests.post(f"{BASE}/users", json={
    "name": "Audit Test User",
    "email": email,
    "password": password,
    "role": "buyer"
})
print("1. create_user:", r.status_code, r.json())
user_id = r.json().get("id")

r = requests.post(f"{BASE}/login", json={"email": email, "password": password})
print("2. login (initial):", r.status_code)
token1 = r.json()["access_token"]
headers1 = {"Authorization": f"Bearer {token1}"}

new_password = "ChangedPass2026x"
r = requests.put(f"{BASE}/change-password", json={
    "current_password": password,
    "new_password": new_password
}, headers=headers1)
print("3. change_password:", r.status_code, r.json())

r = requests.put(f"{BASE}/change-password", json={
    "current_password": new_password,
    "new_password": new_password
}, headers=headers1)
print("4. old token after change (expect 401 revoked):", r.status_code, r.json())

r = requests.post(f"{BASE}/login", json={"email": email, "password": new_password})
print("5. login (new password):", r.status_code)
token2 = r.json()["access_token"]
headers2 = {"Authorization": f"Bearer {token2}"}

r = requests.get(f"{BASE}/audit-log", headers=headers2)
print("6. fresh token on admin-only endpoint (expect 403 not 401):", r.status_code, r.json())

print()
print("THROWAWAY_USER_ID:", user_id)
print("THROWAWAY_EMAIL:", email)
