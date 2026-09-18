"""
M13 - seeds the first real ComplianceRule content for KEVO's buyer-side
investor-classification gate, for the three jurisdictions whose research
came back build-ready in the M13 buyer-side compliance research pass
(see kevo-m13-compliance-research-buyer-side.md in the KEVO project):
United States, Canada, Australia.

Deliberately bounded: only the classification-verification gate is
seeded. Two related, real findings from that research are NOT encoded
here, named rather than silently omitted:

  - US OFAC sanctions screening for foreign-issuer purchases - needs a
    new evidence field KEVO doesn't have yet (no sanctions-screening
    status is tracked anywhere in the schema). Out of scope for this pass.
  - Canada's "permitted client" gap for trades routed through a foreign
    dealer - conditional on a KEVO execution-model decision that hasn't
    been made yet.

UK, Singapore, and South Africa are deliberately not seeded here per
the same research doc's confidence/readiness findings.

Exercises two new M13 engine capabilities from this build:
  - AU-SOPH-001 sets fact_validity_days=180, so Australia's real 6-month
    sophisticated-investor certificate window is live, working expiry
    logic - not just tested via TEST fixtures.
  - All three rules set investor_classification, exercised via
    _check_investor_classification()'s missing/wrong/met distinction.

asset_type "Private Shares" matches the real convention already used
elsewhere in KEVO - NOT "common_stock", which was a wrong assumption
from an earlier, disconnected sandbox copy of this project.

issuer_jurisdiction is left blank (wildcard) on all three: the
requirement to be accredited/sophisticated is treated as a property of
the BUYER's own jurisdiction's securities law, applying regardless of
where the issuer is. Stated assumption, not independently re-confirmed -
flagged same as everything else requires_human_review=True marks.

investor_classification strings ("accredited", "sophisticated") are
compared case-insensitively against InvestorEligibility.classification.
Confirm real InvestorEligibility rows use matching wording before
relying on this in production - if actual stored values differ, these
rules will never match and every buyer lands in "missing evidence" for
classification, not a silent pass.

Idempotent: safe to re-run - skips any rule_code that already exists.
"""

from database import SessionLocal
from models import ComplianceRule


ASSET_TYPE = "Private Shares"

SEED_RULES = [
    {
        "rule_code": "US-ACCRED-001",
        "buyer_jurisdiction": "United States",
        "issuer_jurisdiction": None,
        "investor_classification": "accredited",
        "description": (
            "Buyer must be a verified accredited investor to purchase a "
            "private security under a US Reg D exemption."
        ),
        "fact_type": "eligibility_verified",
        "requirement": "verified",
        "decision_if_unmet": "blocked",
        "fact_validity_days": None,
        "source_reference": (
            "Securities Act of 1933, Regulation D, Rule 501(a) accredited "
            "investor definition - kevo-m13-compliance-research-buyer-side.md, "
            "US section"
        ),
    },
    {
        "rule_code": "CA-ACCRED-001",
        "buyer_jurisdiction": "Canada",
        "issuer_jurisdiction": None,
        "investor_classification": "accredited",
        "description": (
            "Buyer must be a verified accredited investor under NI 45-106 "
            "to purchase a private security via the accredited investor "
            "exemption."
        ),
        "fact_type": "eligibility_verified",
        "requirement": "verified",
        "decision_if_unmet": "blocked",
        "fact_validity_days": None,
        "source_reference": (
            "National Instrument 45-106, s.2.3 accredited investor exemption "
            "- kevo-m13-compliance-research-buyer-side.md, Canada section"
        ),
    },
    {
        "rule_code": "AU-SOPH-001",
        "buyer_jurisdiction": "Australia",
        "issuer_jurisdiction": None,
        "investor_classification": "sophisticated",
        "description": (
            "Buyer must be a verified sophisticated investor under "
            "s.708(8)/(11) to purchase a private security. The supporting "
            "accountant's certificate is only valid for 6 months before "
            "the specific offer - fact_validity_days enforces that window."
        ),
        "fact_type": "eligibility_verified",
        "requirement": "verified",
        "decision_if_unmet": "blocked",
        "fact_validity_days": 180,
        "source_reference": (
            "Corporations Act 2001 (Cth), s.708(8) sophisticated investor / "
            "s.708(11) professional investor, 6-month accountant's "
            "certificate window - kevo-m13-compliance-research-buyer-side.md, "
            "Australia section"
        ),
    },
]


def seed_compliance_rules(db):
    inserted = []
    skipped = []

    for rule_data in SEED_RULES:
        existing = db.query(ComplianceRule).filter(
            ComplianceRule.rule_code == rule_data["rule_code"]
        ).first()

        if existing is not None:
            skipped.append(rule_data["rule_code"])
            continue

        rule = ComplianceRule(
            buyer_jurisdiction=rule_data["buyer_jurisdiction"],
            issuer_jurisdiction=rule_data["issuer_jurisdiction"],
            asset_type=ASSET_TYPE,
            investor_classification=rule_data["investor_classification"],
            rule_code=rule_data["rule_code"],
            description=rule_data["description"],
            fact_type=rule_data["fact_type"],
            fact_validity_days=rule_data["fact_validity_days"],
            requirement=rule_data["requirement"],
            decision_if_unmet=rule_data["decision_if_unmet"],
            requires_human_review=True,
            active=True,
            source_reference=rule_data["source_reference"],
        )
        db.add(rule)
        inserted.append(rule_data["rule_code"])

    db.commit()
    return inserted, skipped


if __name__ == "__main__":
    session = SessionLocal()
    try:
        inserted, skipped = seed_compliance_rules(session)
        print(f"Inserted {len(inserted)} rule(s): {inserted}")
        print(f"Skipped {len(skipped)} already-existing rule(s): {skipped}")
    finally:
        session.close()
