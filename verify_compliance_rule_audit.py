import requests

BASE = "http://127.0.0.1:8000"

r = requests.post(f"{BASE}/login", json={"email": "authtest@kevo.local", "password": "AdminTest2026x"})
admin_token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {admin_token}"}

# Safe no-op update: set description to its own current value, just to exercise the endpoint + audit logging
same_description = "Buyer must be a verified accredited investor to purchase a private security under a US Reg D exemption."
r = requests.put(f"{BASE}/compliance-rules/2", json={"description": same_description}, headers=headers)
print("1. update_compliance_rule:", r.status_code, r.text)

r = requests.get(f"{BASE}/audit-log", headers=headers)
entries = r.json()
matching = [e for e in entries if e["action"] == "compliance_rule_updated" and e["target_id"] == 2]
print("2. matching compliance_rule_updated audit entries:", matching)
