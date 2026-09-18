from app import get_db, build_deal_health, build_risk_radar, evaluate_transferability, get_transferability_assessment
from models import Listing as ListingModel, User as UserModel, Transaction, TransferabilityAssessment

db = next(get_db())

count_before = db.query(TransferabilityAssessment).count()
print("=== TransferabilityAssessment row count before:", count_before, "===")

listing10 = db.query(ListingModel).filter(ListingModel.id == 10).first()
print("\nListing 10 - issuer_jurisdiction:", listing10.issuer_jurisdiction, "| asset_type:", listing10.asset_type)

result1 = get_transferability_assessment(10, db)
result2 = get_transferability_assessment(10, db)
count_after = db.query(TransferabilityAssessment).count()
print("\n=== TransferabilityAssessment row count after 2 endpoint calls:", count_after, "(should be unchanged) ===")
print("\nLive evaluate_transferability() result for listing 10:")
print("  status:", result1["status"])
print("  reasons:", result1["reasons"])
print("  forecast_date:", result1["forecast_date"])

listing2 = db.query(ListingModel).filter(ListingModel.id == 2).first()
print("\n--- Listing 2 - issuer_jurisdiction:", listing2.issuer_jurisdiction, "| asset_type:", listing2.asset_type)
real_transactions_l2 = db.query(Transaction).filter(Transaction.listing_id == 2).all()

print("\n=== Deal Health Score - real transactions on listing 2 ===")
for t in real_transactions_l2:
    dh = build_deal_health(t, db)
    reg = next(d for d in dh["dimensions"] if d["dimension"] == "regulatory_uncertainty")
    print("Transaction", t.id, "(status:", t.status, ") regulatory_uncertainty:", reg["status"], "-", reg["reason"])

print("\n=== Risk Radar - real transactions on listing 2 ===")
for t in real_transactions_l2:
    rr = build_risk_radar(t, db)
    conflict = next(f for f in rr["flags"] if f["flag_type"] == "transferability_conflict")
    forecast = next(f for f in rr["flags"] if f["flag_type"] == "transferability_forecast_timing")
    print("Transaction", t.id, "- conflict:", conflict["status"], "| forecast_timing:", forecast["status"])

print("\n=== Throwaway in-memory transaction against real listing 10 (not persisted) ===")
real_buyer = db.query(UserModel).first()
throwaway_txn = Transaction(
    listing_id=listing10.id, buyer_id=real_buyer.id, seller_id=listing10.seller_id,
    quantity=1, agreed_price=1, status="interested"
)
dh10 = build_deal_health(throwaway_txn, db)
reg10 = next(d for d in dh10["dimensions"] if d["dimension"] == "regulatory_uncertainty")
print("Deal Health regulatory_uncertainty:", reg10["status"], "-", reg10["reason"])

rr10 = build_risk_radar(throwaway_txn, db)
conflict10 = next(f for f in rr10["flags"] if f["flag_type"] == "transferability_conflict")
forecast10 = next(f for f in rr10["flags"] if f["flag_type"] == "transferability_forecast_timing")
print("Risk Radar transferability_conflict:", conflict10["status"], "-", conflict10["reason"])
print("Risk Radar transferability_forecast_timing:", forecast10["status"], "-", forecast10["reason"])

db.rollback()
count_final = db.query(TransferabilityAssessment).count()
print("\n=== Residue check - TransferabilityAssessment count after rollback:", count_final, "(should match", count_before, ") ===")
