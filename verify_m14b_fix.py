from app import get_db, get_offering_exemptions
from models import Offering, OfferingExemptionAssessment

db = next(get_db())

count_before = db.query(OfferingExemptionAssessment).count()
print("=== OfferingExemptionAssessment row count before:", count_before, "===")

result1 = get_offering_exemptions(1, db)
result2 = get_offering_exemptions(1, db)
count_after = db.query(OfferingExemptionAssessment).count()
print("=== row count after 2 endpoint calls:", count_after, "(should be unchanged) ===\n")

for a in result1["assessments"]:
    print(a["exemption_code"], "->", a["status"])
    print("   ", "; ".join(a["reasons"]))

db.rollback()
count_final = db.query(OfferingExemptionAssessment).count()
print("\n=== Residue check - count after rollback:", count_final, "(should match", count_before, ") ===")
