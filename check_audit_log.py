import requests
import json

BASE = "http://127.0.0.1:8000"

r = requests.post(f"{BASE}/login", json={"email": "authtest@kevo.local", "password": "AdminTest2026x"})
print("admin login:", r.status_code)
admin_token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {admin_token}"}

r = requests.get(f"{BASE}/audit-log", headers=headers)
print("audit-log fetch:", r.status_code)
entries = r.json()

password_changed_entries = [e for e in entries if e["action"] == "password_changed"]
print(f"\ntotal audit entries: {len(entries)}")
print(f"password_changed entries: {len(password_changed_entries)}")
for e in password_changed_entries[-3:]:
    print(json.dumps(e, indent=2))
