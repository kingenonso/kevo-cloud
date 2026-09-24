import requests

BASE = "http://127.0.0.1:8000"
TARGET_USER_ID = 73  # the throwaway "Audit Reset User" from the previous test

r = requests.post(f"{BASE}/login", json={"email": "authtest@kevo.local", "password": "AdminTest2026x"})
admin_token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {admin_token}"}

r = requests.put(f"{BASE}/users/{TARGET_USER_ID}/kyc-status", params={"status": "verified"}, headers=headers)
print("1. update_kyc_status:", r.status_code, r.text)

r = requests.get(f"{BASE}/audit-log", headers=headers)
entries = r.json()
matching = [e for e in entries if e["action"] == "kyc_status_changed" and e["target_id"] == TARGET_USER_ID]
print("2. matching kyc_status_changed audit entries:", matching)
