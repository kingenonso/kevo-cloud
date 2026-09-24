from database import SessionLocal
from models import ComplianceRule
from sqlalchemy import inspect

db = SessionLocal()
rule = db.query(ComplianceRule).first()
if rule is None:
    print("NO RULES FOUND")
else:
    mapper = inspect(ComplianceRule)
    for col in mapper.columns:
        print(col.key, "=", getattr(rule, col.key))
db.close()
