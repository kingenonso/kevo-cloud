with open("app.py", "r") as f:
    content = f.read()

# --- Fix 1: stop GET /transferability/listing/{id} from writing to the database ---
old_endpoint = '''@app.get("/transferability/listing/{listing_id}")
def get_transferability_assessment(
    listing_id: int,
    db: Session = Depends(get_db)
):
    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    result = evaluate_transferability(listing, db)

    explanation = "; ".join(result["reasons"])

    assessment = TransferabilityAssessment(
        listing_id=listing.id,
        status=result["status"],
        explanation=explanation,
        path_to_eligibility=result["path_to_eligibility"],
        forecast_date=result["forecast_date"]
    )

    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    return {
        "listing_id": listing.id,
        "assessment_id": assessment.id,
        "status": result["status"],
        "reasons": result["reasons"],
        "applicable_rule_count": result["applicable_rule_count"],
        "path_to_eligibility": result["path_to_eligibility"],
        "forecast_date": result["forecast_date"]
    }'''

new_endpoint = '''@app.get("/transferability/listing/{listing_id}")
def get_transferability_assessment(
    listing_id: int,
    db: Session = Depends(get_db)
):
    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    result = evaluate_transferability(listing, db)

    return {
        "listing_id": listing.id,
        "status": result["status"],
        "reasons": result["reasons"],
        "applicable_rule_count": result["applicable_rule_count"],
        "path_to_eligibility": result["path_to_eligibility"],
        "forecast_date": result["forecast_date"]
    }'''

count = content.count(old_endpoint)
assert count == 1, "Fix 1: expected 1 match, found " + str(count)
content = content.replace(old_endpoint, new_endpoint, 1)
print("Fix 1 applied: transferability endpoint no longer writes to the database.")

# --- Fix 2: Deal Health Score's regulatory_uncertainty dimension reads live instead of stale rows ---
old_dealhealth = '''    # 5. Regulatory uncertainty - real transferability assessment on file for this listing
    transferability_assessments = db.query(TransferabilityAssessment).filter(
        TransferabilityAssessment.listing_id == listing.id
    ).all()

    if len(transferability_assessments) == 0:
        dimensions.append({
            "dimension": "regulatory_uncertainty",
            "determinable": False,
            "status": "cannot_determine",
            "reason": "No transferability assessment on file for this listing"
        })
    else:
        worst_priority = {"conflict": 0, "blocked": 1, "eligible_pending_review": 2, "eligible": 3}
        worst = min(transferability_assessments, key=lambda a: worst_priority.get(a.status, 2))
        dimensions.append({
            "dimension": "regulatory_uncertainty",
            "determinable": True,
            "status": worst.status,
            "reason": worst.explanation
        })'''

new_dealhealth = '''    # 5. Regulatory uncertainty - live transferability evaluation for this listing
    transferability_result = evaluate_transferability(listing, db)

    if transferability_result["applicable_rule_count"] == 0:
        dimensions.append({
            "dimension": "regulatory_uncertainty",
            "determinable": False,
            "status": "cannot_determine",
            "reason": "No transferability rules found for this listing's jurisdiction and asset type"
        })
    else:
        dimensions.append({
            "dimension": "regulatory_uncertainty",
            "determinable": True,
            "status": transferability_result["status"],
            "reason": "; ".join(transferability_result["reasons"])
        })'''

count = content.count(old_dealhealth)
assert count == 1, "Fix 2: expected 1 match, found " + str(count)
content = content.replace(old_dealhealth, new_dealhealth, 1)
print("Fix 2 applied: Deal Health Score's regulatory_uncertainty now reads live.")

# --- Fix 3a: Risk Radar's transferability_conflict flag reads live instead of stale rows ---
old_flag2 = '''    # 2. Conflicting transferability facts
    conflicting_assessments = db.query(TransferabilityAssessment).filter(
        TransferabilityAssessment.listing_id == listing.id,
        TransferabilityAssessment.status == "conflict"
    ).all()

    if len(conflicting_assessments) > 0:
        reasons = "; ".join(a.explanation for a in conflicting_assessments)
        flags.append({
            "flag_type": "transferability_conflict",
            "status": "flagged",
            "reason": str(len(conflicting_assessments)) + " conflicting transferability assessment(s) on file for this listing: " + reasons
        })
    else:
        flags.append({
            "flag_type": "transferability_conflict",
            "status": "clear",
            "reason": "No conflicting transferability facts on file for this listing."
        })'''

new_flag2 = '''    # 2. Conflicting transferability facts (live evaluation)
    transferability_result = evaluate_transferability(listing, db)

    if transferability_result["status"] == "conflict":
        flags.append({
            "flag_type": "transferability_conflict",
            "status": "flagged",
            "reason": "; ".join(transferability_result["reasons"])
        })
    else:
        flags.append({
            "flag_type": "transferability_conflict",
            "status": "clear",
            "reason": "No conflicting transferability facts on file for this listing."
        })'''

count = content.count(old_flag2)
assert count == 1, "Fix 3a: expected 1 match, found " + str(count)
content = content.replace(old_flag2, new_flag2, 1)
print("Fix 3a applied: Risk Radar's transferability_conflict flag now reads live.")

# --- Fix 3b: Risk Radar's transferability_forecast_timing flag reuses the same live result ---
old_flag4 = '''    # 4. Forecasted-but-not-yet-eligible timing
    forecasted_assessments = db.query(TransferabilityAssessment).filter(
        TransferabilityAssessment.listing_id == listing.id,
        TransferabilityAssessment.status.in_(["blocked", "conflict"]),
        TransferabilityAssessment.forecast_date.isnot(None)
    ).all()

    if len(forecasted_assessments) > 0:
        dates = "; ".join(str(a.forecast_date) for a in forecasted_assessments)
        flags.append({
            "flag_type": "transferability_forecast_timing",
            "status": "flagged",
            "reason": "Not currently eligible; forecast eligibility date(s) on file: " + dates
        })
    else:
        flags.append({
            "flag_type": "transferability_forecast_timing",
            "status": "clear",
            "reason": "No forecasted eligibility timing on file for this listing."
        })'''

new_flag4 = '''    # 4. Forecasted-but-not-yet-eligible timing (live evaluation)
    if transferability_result["forecast_date"] is not None:
        flags.append({
            "flag_type": "transferability_forecast_timing",
            "status": "flagged",
            "reason": "Not currently eligible; forecast eligibility date on file: " + str(transferability_result["forecast_date"])
        })
    else:
        flags.append({
            "flag_type": "transferability_forecast_timing",
            "status": "clear",
            "reason": "No forecasted eligibility timing on file for this listing."
        })'''

count = content.count(old_flag4)
assert count == 1, "Fix 3b: expected 1 match, found " + str(count)
content = content.replace(old_flag4, new_flag4, 1)
print("Fix 3b applied: Risk Radar's transferability_forecast_timing flag now reuses the live result.")

with open("app.py", "w") as f:
    f.write(content)

print("All 4 fixes written to app.py.")
