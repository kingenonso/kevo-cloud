with open("app.py", "r") as f:
    content = f.read()

old_endpoint = '''@app.get("/offering-exemptions/{offering_id}")
def get_offering_exemptions(
    offering_id: int,
    db: Session = Depends(get_db)
):
    offering = db.query(Offering).filter(
        Offering.id == offering_id
    ).first()

    if offering is None:
        raise HTTPException(
            status_code=404,
            detail="Offering not found"
        )

    assessments = evaluate_offering_exemptions(offering, db)

    for a in assessments:
        record = OfferingExemptionAssessment(
            offering_id=offering.id,
            exemption_code=a["exemption_code"],
            status=a["status"],
            reasons="; ".join(a["reasons"]),
            assessed_at=date.today()
        )
        db.add(record)

    db.commit()

    return {
        "offering_id": offering.id,
        "assessments": assessments
    }'''

new_endpoint = '''@app.get("/offering-exemptions/{offering_id}")
def get_offering_exemptions(
    offering_id: int,
    db: Session = Depends(get_db)
):
    offering = db.query(Offering).filter(
        Offering.id == offering_id
    ).first()

    if offering is None:
        raise HTTPException(
            status_code=404,
            detail="Offering not found"
        )

    assessments = evaluate_offering_exemptions(offering, db)

    return {
        "offering_id": offering.id,
        "assessments": assessments
    }'''

count = content.count(old_endpoint)
assert count == 1, "expected 1 match, found " + str(count)
content = content.replace(old_endpoint, new_endpoint, 1)

with open("app.py", "w") as f:
    f.write(content)
print("app.py fixed: /offering-exemptions/{offering_id} no longer writes to the database.")
