from database import SessionLocal
from models import ComplianceRule

db = SessionLocal()
rules = db.query(ComplianceRule).limit(3).all()
for r in rules:
    print(r.id, r.rule_code, r.jurisdiction, r.requirement, r.decision_if_unmet, r.hold_period_days, r.source_reference)
db.close()
