from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from datetime import date, timedelta
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Listing as ListingModel
from models import User as UserModel
from models import OwnershipRecord, Transaction, BuyerInterest, InvestorEligibility, ComplianceRule, TransferabilityRule, TransferabilityFact, TransferabilityAssessment, PositionPassport, Evidence, PositionEvent, Offering, OfferingFact, OfferingExemptionRule, OfferingExemptionAssessment
from models import Transaction
app = FastAPI(title="KEVO API")


class UserCreate(BaseModel):
    name: str
    email: str
    role: str = "buyer"
    seller_affiliate_status: str | None = None


class ListingCreate(BaseModel):
    seller_id: int
    listing_id: int | None = None
    company: str
    asset_type: str
    quantity: int
    asking_price: float
    issuer_reporting_status: str | None = None
    issuer_current_information_available: bool | None = None
    issuer_jurisdiction: str | None = None
    is_transferable: bool | None = None

class OwnershipCreate(BaseModel):
    listing_id: int
    seller_id: int
    company: str
    asset_type: str
    quantity: int
    acquisition_date: date | None = None


class TransactionCreate(BaseModel):
    listing_id: int
    buyer_id: int
    quantity: int
    agreed_price: float
class BuyerInterestCreate(BaseModel):
    buyer_id: int
    company: str
    asset_type: str
    desired_quantity: int
    maximum_price: float    

class InvestorEligibilityCreate(BaseModel):
    buyer_id: int
    investor_type: str
    classification: str
    status: str = "pending"
    verification_method: str | None = None
    evidence_reference: str | None = None
    effective_date: str | None = None
    review_date: str | None = None
    jurisdiction: str | None = None
class ComplianceRuleCreate(BaseModel):
    buyer_jurisdiction: str | None = None
    issuer_jurisdiction: str | None = None
    asset_type: str | None = None
    investor_classification: str | None = None
    rule_code: str
    description: str
    decision: str
    requires_human_review: bool = True
    active: bool = True
    source_reference: str | None = None

def check_compliance(buyer, listing, db):
    eligibility = db.query(InvestorEligibility).filter(
        InvestorEligibility.buyer_id == buyer.id
    ).first()
    ownership = db.query(OwnershipRecord).filter(
        OwnershipRecord.listing_id == listing.id,
        OwnershipRecord.seller_id == listing.seller_id,
        OwnershipRecord.verification_status == "verified"
    ).first()
    seller = db.query(UserModel).filter(
        UserModel.id == listing.seller_id
    ).first()

    checks = {
        "kyc_verified": buyer.kyc_status == "verified",
        "asset_transferable": listing.is_transferable,
        "eligibility_record_exists": eligibility is not None,
        "ownership_record_exists": ownership is not None,
        "issuer_reporting_status_present": listing.issuer_reporting_status is not None,
        "issuer_reporting_status": listing.issuer_reporting_status,
        "issuer_current_information_available": listing.issuer_current_information_available,
        "issuer_current_information_available_present": listing.issuer_current_information_available is not None,
        "seller_affiliate_status_present": (
            seller is not None
            and seller.seller_affiliate_status is not None
    ),
    "seller_affiliate_status": (
        seller.seller_affiliate_status
        if seller is not None
        else None
),
    "eligibility_verified": (
        eligibility is not None
        and eligibility.status == "verified"
    ),
    "acquisition_date_present": (
        ownership is not None
        and ownership.acquisition_date is not None
),
    "acquisition_date": (
    ownership.acquisition_date
    if ownership is not None
    else None
)
}
    reasons = []

    if not checks["kyc_verified"]:
        reasons.append("Buyer KYC is not verified")

    if not checks["asset_transferable"]:
        reasons.append("Listing is not confirmed transferable")

    if buyer.jurisdiction is None:
        reasons.append("Buyer jurisdiction is missing")

    if listing.issuer_jurisdiction is None:
        reasons.append("Issuer jurisdiction is missing")
    if not checks["ownership_record_exists"]:
        reasons.append("Ownership record is missing for regulatory review")
    if checks["ownership_record_exists"] and not checks["acquisition_date_present"]:
        reasons.append("Ownership acquisition date is missing for regulatory review")
    if not checks["issuer_current_information_available_present"]:
        reasons.append("Current issuer information availability is missing for regulatory review")
    if not checks["issuer_reporting_status_present"]:
        reasons.append("Issuer reporting status is missing for regulatory review")
    if not checks["seller_affiliate_status_present"]:
        reasons.append("Seller affiliate status is missing for regulatory review")

    if not checks["kyc_verified"] or not checks["asset_transferable"]:
        return {
            "status": "blocked",
            "reasons": reasons,
            "checks": checks
        }

    if buyer.jurisdiction is None or listing.issuer_jurisdiction is None:
        return {
            "status": "review",
            "reasons": reasons,
            "checks": checks
        }

    if not checks["eligibility_record_exists"]:
        return {
            "status": "review",
            "reasons": reasons + [
                "Investor eligibility record is missing"
            ],
            "checks": checks
        }

    if not checks["eligibility_verified"]:
        return {
            "status": "review",
            "reasons": reasons + [
                "Investor eligibility has not been verified"
            ]       ,
            "checks": checks
        }

    return {
        "status": "review",
        "reasons": reasons + [
            "Jurisdiction eligibility requires applicable legal and regulatory rule evaluation"
        ],
        "checks": checks
    }
def find_applicable_rules(buyer, listing, db):
    eligibility = db.query(InvestorEligibility).filter(
        InvestorEligibility.buyer_id == buyer.id
    ).first()

    investor_classification = None

    if eligibility is not None:
        investor_classification = eligibility.classification

    rules = db.query(ComplianceRule).filter(
        ComplianceRule.active == True
    ).all()

    applicable_rules = []

    for rule in rules:
        if (
            rule.buyer_jurisdiction is not None
            and rule.buyer_jurisdiction != buyer.jurisdiction
        ):
            continue

        if (
            rule.issuer_jurisdiction is not None
            and rule.issuer_jurisdiction != listing.issuer_jurisdiction
        ):
            continue

        if (
            rule.asset_type is not None
            and rule.asset_type != listing.asset_type
        ):
            continue

        if (
            rule.investor_classification is not None
            and rule.investor_classification != investor_classification
        ):
            continue

        applicable_rules.append(rule)

    return applicable_rules

def evaluate_compliance_rules(buyer, listing, db):
    rules = find_applicable_rules(
        buyer,
        listing,
        db
    )

    evaluations = []

    for rule in rules:
        evaluations.append({
            "rule_id": rule.id,
            "rule_code": rule.rule_code,
            "decision": rule.decision,
            "requires_human_review": rule.requires_human_review,
            "source_reference": rule.source_reference
        })

    return evaluations
    
def find_applicable_transferability_rules(listing, db):
    rules = db.query(TransferabilityRule).filter(
        TransferabilityRule.active == True
    ).all()

    applicable_rules = []

    for rule in rules:
        if rule.jurisdiction != listing.issuer_jurisdiction:
            continue

        if rule.asset_type != listing.asset_type:
            continue

        applicable_rules.append(rule)

    return applicable_rules
    
def evaluate_transferability(listing, db):
    rules = find_applicable_transferability_rules(listing, db)

    if not rules:
        return {
            "status": "review",
            "reasons": [
                "No transferability rules found for this listing's jurisdiction and asset type"
            ],
            "applicable_rule_count": 0,
            "path_to_eligibility": None,
            "forecast_date": None
        }

    reasons = []
    statuses = []
    path_to_eligibility = None
    forecast_date = None

    estate_fact = db.query(TransferabilityFact).filter(
        TransferabilityFact.listing_id == listing.id,
        TransferabilityFact.fact_type == "holder_deceased_estate_distribution",
        TransferabilityFact.verification_status == "verified"
    ).first()

    for rule in rules:
        facts = db.query(TransferabilityFact).filter(
            TransferabilityFact.listing_id == listing.id,
            TransferabilityFact.fact_type == rule.fact_type,
            TransferabilityFact.superseded_by_id.is_(None)
        ).all()

        if not facts:
            statuses.append(rule.decision_if_unmet)
            reasons.append(
                "Missing required fact '" + rule.fact_type + "' for rule " + rule.rule_code
            )
            continue

        verified_facts = [f for f in facts if f.verification_status == "verified"]
        distinct_values = set(f.fact_value for f in verified_facts)

        if len(distinct_values) > 1:
            statuses.append("conflict")
            conflict_detail = "; ".join(
                "'" + f.fact_value + "' (source: " + (f.source_reference or "unknown") + ")"
                for f in verified_facts
            )
            reasons.append(
                "Conflicting verified facts for '" + rule.fact_type + "' under rule " + rule.rule_code +
                " — " + conflict_detail + " — issuer or authorized-party verification needed to resolve"
            )
            continue

        if not verified_facts:
            statuses.append("review")
            reasons.append(
                "Fact '" + rule.fact_type + "' for rule " + rule.rule_code + " is not yet verified"
            )
            continue

        fact = verified_facts[0]

        if estate_fact is not None and rule.jurisdiction == "United States":
            reasons.append(
                "Rule " + rule.rule_code + " holding period does not apply — SEC Rule 144(d)(3)(vii) estate exemption applies to a verified estate distribution"
            )
            continue

        if rule.hold_period_days is not None:
            if fact.as_of_date is None:
                statuses.append("needs_evidence")
                reasons.append(
                    "Fact '" + rule.fact_type + "' for rule " + rule.rule_code + " is missing a date"
                )
                continue

            rule_forecast_date = fact.as_of_date + timedelta(days=rule.hold_period_days)

            if date.today() < rule_forecast_date:
                statuses.append("blocked")
                reasons.append(
                    "Rule " + rule.rule_code + " holding period not yet met — eligible once it ends on " + rule_forecast_date.isoformat()
                )
                path_to_eligibility = (
                    "Eligible once the holding period required by " + rule.rule_code +
                    " ends on " + rule_forecast_date.isoformat()
                )
                if forecast_date is None or rule_forecast_date > forecast_date:
                    forecast_date = rule_forecast_date
                continue

    if "conflict" in statuses:
        overall_status = "conflict"
    elif "blocked" in statuses:
        overall_status = "blocked"
    elif "needs_evidence" in statuses:
        overall_status = "needs_evidence"
    elif "review" in statuses:
        overall_status = "review"
    else:
        overall_status = "eligible_pending_review"

    if not reasons:
        reasons.append(
            "All applicable transferability facts are present and verified — this is not a legal conclusion, human/legal review is still required"
        )

    return {
        "status": overall_status,
        "reasons": reasons,
        "applicable_rule_count": len(rules),
        "path_to_eligibility": path_to_eligibility,
        "forecast_date": forecast_date
    }
@app.get("/")
def home():
    return {"message": "Welcome to KEVO API"}


@app.get("/health")
def health():
    return {"status": "healthy"}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/compliance-rules/matches/{buyer_id}/{listing_id}")
def get_applicable_compliance_rules(
    buyer_id: int,
    listing_id: int,
    db: Session = Depends(get_db)
):
    buyer = db.query(UserModel).filter(
        UserModel.id == buyer_id
    ).first()

    if buyer is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer not found"
        )

    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    evaluations = evaluate_compliance_rules(
        buyer,
        listing,
        db
    )

    return {
        "buyer_id": buyer.id,
        "listing_id": listing.id,
        "evaluated_rules": evaluations
 
    }
    
@app.get("/transferability/listing/{listing_id}")
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
    }

@app.get("/transferability/matrix")
def get_transferability_matrix(
    asset_type: str = "Private Shares",
    db: Session = Depends(get_db)
):
    rules = db.query(TransferabilityRule).filter(
        TransferabilityRule.asset_type == asset_type,
        TransferabilityRule.active == True
    ).all()

    matrix = {}

    for rule in rules:
        if rule.jurisdiction not in matrix:
            matrix[rule.jurisdiction] = []

        matrix[rule.jurisdiction].append({
            "rule_code": rule.rule_code,
            "requirement": rule.requirement,
            "decision_if_unmet": rule.decision_if_unmet,
            "hold_period_days": rule.hold_period_days,
            "source_reference": rule.source_reference
        })

    return {
        "asset_type": asset_type,
        "jurisdictions": matrix
    }
@app.post("/users")
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db)
):
    existing_user = db.query(UserModel).filter(
        UserModel.email == user.email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    if user.role not in ["buyer", "seller"]:
        raise HTTPException(
            status_code=400,
            detail="Role must be buyer or seller"
        )

    new_user = UserModel(
        name=user.name,
        email=user.email,
        role=user.role,
        seller_affiliate_status=user.seller_affiliate_status
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "User created",
        "user": {
            "id": new_user.id,
            "name": new_user.name,
            "email": new_user.email,
            "role": new_user.role,
            "seller_affiliate_status": new_user.seller_affiliate_status
        }
    }


@app.get("/users")
def get_users(db: Session = Depends(get_db)):
    users = db.query(UserModel).all()

    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
        for user in users
    ]


@app.post("/ownership")
def create_ownership(
    ownership: OwnershipCreate,
    db: Session = Depends(get_db)
):
    seller = db.query(UserModel).filter(
        UserModel.id == ownership.seller_id
    ).first()

    if seller is None:
        raise HTTPException(
            status_code=404,
            detail="Seller not found"
        )

    if seller.role != "seller":
        raise HTTPException(
            status_code=400,
            detail="User is not a seller"
        )

    new_ownership = OwnershipRecord(
        seller_id=ownership.seller_id,
        listing_id=ownership.listing_id,
        company=ownership.company,
        asset_type=ownership.asset_type,
        quantity=ownership.quantity,
        acquisition_date=ownership.acquisition_date
)

    db.add(new_ownership)
    db.commit()
    db.refresh(new_ownership)

    return {
        "message": "Ownership record created",
        "ownership": {
            "id": new_ownership.id,
            "seller_id": new_ownership.seller_id,
            "listing_id": new_ownership.listing_id,
            "company": new_ownership.company,
            "asset_type": new_ownership.asset_type,
           "quantity": new_ownership.quantity,
            "acquisition_date": new_ownership.acquisition_date,
            "verification_status": new_ownership.verification_status
        }
    }

@app.post("/transactions")
def create_transaction(
    transaction: TransactionCreate,
    db: Session = Depends(get_db)
):
    listing = db.query(ListingModel).filter(
        ListingModel.id == transaction.listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    seller = db.query(UserModel).filter(
        UserModel.id == listing.seller_id
    ).first()

    if seller is None:
        raise HTTPException(
            status_code=404,
            detail="Seller not found"
        )

    if seller.role != "seller":
        raise HTTPException(
            status_code=400,
            detail="User is not a seller"
        )
    buyer = db.query(UserModel).filter(
        UserModel.id == transaction.buyer_id
    ).first()

    if buyer is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer not found"
        )

    if buyer.role != "buyer":
        raise HTTPException(
            status_code=400,
            detail="User is not a buyer"
        )
    if buyer.id == seller.id:
        raise HTTPException(
            status_code=400,
            detail="Buyer and seller cannot be the same user"
        )
    if transaction.agreed_price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Agreed price must be greater than zero"
        )
    if transaction.quantity > listing.quantity:
        raise HTTPException(
            status_code=400,
            detail="Not enough quantity available"
        )

    new_transaction = Transaction(
        listing_id=transaction.listing_id,
        buyer_id=transaction.buyer_id,
        seller_id=listing.seller_id,
        quantity=transaction.quantity,
        agreed_price=transaction.agreed_price,
        status="interested"
    )

    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)

    return {
        "message": "Transaction created",
        "transaction": {
            "id": new_transaction.id,
            "listing_id": new_transaction.listing_id,
            "buyer_id": new_transaction.buyer_id,
            "seller_id": new_transaction.seller_id,
            "quantity": new_transaction.quantity,
            "agreed_price": new_transaction.agreed_price,
            "status": new_transaction.status
        }
    }      


@app.put("/ownership/{ownership_id}/verify")
def verify_ownership(
    ownership_id: int,
    status: str,
    verification_reference: str,
    db: Session = Depends(get_db)
):
    ownership = db.query(OwnershipRecord).filter(
        OwnershipRecord.id == ownership_id
    ).first()

    if ownership is None:
        raise HTTPException(
            status_code=404,
            detail="Ownership record not found"
        )

    if status not in ["verified", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Status must be verified or rejected"
        )

    ownership.verification_status = status
    ownership.verification_reference = verification_reference

    db.commit()
    db.refresh(ownership)

    return {
        "message": "Ownership verification updated",
        "ownership": {
            "id": ownership.id,
            "seller_id": ownership.seller_id,
            "company": ownership.company,
            "asset_type": ownership.asset_type,
            "quantity": ownership.quantity,
            "verification_status": ownership.verification_status,
            "verification_reference": ownership.verification_reference
        }
    }



@app.post("/listings")
def create_listing(
    listing: ListingCreate,
    db: Session = Depends(get_db)
):
    seller = db.query(UserModel).filter(
        UserModel.id == listing.seller_id
    ).first()

    if seller is None:
        raise HTTPException(
            status_code=404,
            detail="Seller not found"
        )

    if seller.role != "seller":
        raise HTTPException(
            status_code=400,
            detail="User is not a seller"
        )

    new_listing = ListingModel(
        seller_id=listing.seller_id,
        company=listing.company,
        asset_type=listing.asset_type,
        quantity=listing.quantity,
        asking_price=listing.asking_price,
        issuer_reporting_status=listing.issuer_reporting_status,
        issuer_current_information_available=listing.issuer_current_information_available,
        issuer_jurisdiction=listing.issuer_jurisdiction,
        is_transferable=listing.is_transferable if listing.is_transferable is not None else False
    )

    db.add(new_listing)
    db.commit()
    db.refresh(new_listing)

    return {
        "message": "Listing created",
        "listing": {
            "id": new_listing.id,
            "seller_id": new_listing.seller_id,
            "company": new_listing.company,
            "asset_type": new_listing.asset_type,
            "quantity": new_listing.quantity,
            "asking_price": float(new_listing.asking_price),
            "issuer_reporting_status": new_listing.issuer_reporting_status,
            "issuer_current_information_available": new_listing.issuer_current_information_available,
            "issuer_jurisdiction": new_listing.issuer_jurisdiction,
            "is_transferable": new_listing.is_transferable
        }
    }


@app.get("/listings")
def get_listings(db: Session = Depends(get_db)):
    listings = db.query(ListingModel).all()

    return [
        {
            "id": listing.id,
            "seller_id": listing.seller_id,
            "company": listing.company,
            "asset_type": listing.asset_type,
            "quantity": listing.quantity,
            "asking_price": float(listing.asking_price)
        }
        for listing in listings
    ]


@app.get("/listings/{listing_id}")
def get_listing(
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

    seller = db.query(UserModel).filter(
        UserModel.id == listing.seller_id
    ).first()

    return {
        "listing": {
            "id": listing.id,
            "company": listing.company,
            "asset_type": listing.asset_type,
            "quantity": listing.quantity,
            "asking_price": float(listing.asking_price)
        },
        "seller": {
            "id": seller.id,
            "name": seller.name,
            "email": seller.email,
            "role": seller.role
        }
    }
@app.put("/listings/{listing_id}")
def update_listing(
    listing_id: int,
    listing_data: ListingCreate,
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

    seller = db.query(UserModel).filter(
        UserModel.id == listing_data.seller_id
    ).first()

    if seller is None:
        raise HTTPException(
            status_code=404,
            detail="Seller not found"
        )

    if seller.role != "seller":
        raise HTTPException(
            status_code=400,
            detail="User is not a seller"
        )

    listing.seller_id = listing_data.seller_id
    listing.company = listing_data.company
    listing.asset_type = listing_data.asset_type
    listing.quantity = listing_data.quantity
    listing.asking_price = listing_data.asking_price

    db.commit()
    db.refresh(listing)

    return {
        "message": "Listing updated",
        "listing": {
            "id": listing.id,
            "seller_id": listing.seller_id,
            "company": listing.company,
            "asset_type": listing.asset_type,
            "quantity": listing.quantity,
            "asking_price": float(listing.asking_price)
        }
    }


@app.delete("/listings/{listing_id}")
def delete_listing(
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

    db.delete(listing)
    db.commit()

    return {
        "message": "Listing deleted",
        "listing_id": listing_id
    }
@app.post("/ownership/{ownership_id}/verify")
def verify_ownership(
    ownership_id: int,
    verification_reference: str,
    db: Session = Depends(get_db)
):
    ownership = db.query(OwnershipRecord).filter(
        OwnershipRecord.id == ownership_id
    ).first()

    if ownership is None:
        raise HTTPException(
            status_code=404,
            detail="Ownership record not found"
        )

    ownership.verification_status = "verified"
    ownership.verification_reference = verification_reference

    db.commit()
    db.refresh(ownership)

    return {
        "message": "Ownership verified",
        "ownership": {
            "id": ownership.id,
            "listing_id": ownership.listing_id,
            "seller_id": ownership.seller_id,
            "company": ownership.company,
            "asset_type": ownership.asset_type,
            "quantity": ownership.quantity,
            "verification_status": ownership.verification_status,
            "verification_reference": ownership.verification_reference
        }
    }

@app.patch("/transactions/{transaction_id}/status")
def update_transaction_status(
    transaction_id: int,
    status: str,
    db: Session = Depends(get_db)
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )

    allowed_statuses = [
        "interested",
        "accepted",
        "settlement_pending",
        "completed",
        "rejected",
        "cancelled"
    ]

    if status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Invalid transaction status"
        )

    allowed_transitions = {
        "interested": ["accepted", "rejected", "cancelled"],
        "accepted": ["settlement_pending", "cancelled"],
        "settlement_pending": ["completed", "cancelled"],
        "completed": [],
        "rejected": [],
        "cancelled": []
    }

    if status not in allowed_transitions[transaction.status]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change transaction status from {transaction.status} to {status}"
        )
    transaction.status = status

    db.commit()
    db.refresh(transaction)

    return {
        "message": "Transaction status updated",
        "transaction": {
            "id": transaction.id,
            "listing_id": transaction.listing_id,
            "buyer_id": transaction.buyer_id,
            "seller_id": transaction.seller_id,
            "quantity": transaction.quantity,
            "agreed_price": transaction.agreed_price,
            "status": transaction.status
        }
    }    

@app.post("/buyer-interests")
def create_buyer_interest(
    interest: BuyerInterestCreate,
    db: Session = Depends(get_db)
):
    buyer = db.query(UserModel).filter(
        UserModel.id == interest.buyer_id
    ).first()

    if buyer is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer not found"
        )

    if buyer.role != "buyer":
        raise HTTPException(
            status_code=400,
            detail="User is not a buyer"
        )

    new_interest = BuyerInterest(
        buyer_id=interest.buyer_id,
        company=interest.company,
        asset_type=interest.asset_type,
        desired_quantity=interest.desired_quantity,
        maximum_price=interest.maximum_price
    )

    db.add(new_interest)
    db.commit()
    db.refresh(new_interest)

    return {
        "message": "Buyer interest created",
        "buyer_interest": {
            "id": new_interest.id,
            "buyer_id": new_interest.buyer_id,
            "company": new_interest.company,
            "asset_type": new_interest.asset_type,
            "desired_quantity": new_interest.desired_quantity,
            "maximum_price": float(new_interest.maximum_price),
            "status": new_interest.status
        }
    }    
@app.post("/investor-eligibility")
def create_investor_eligibility(
    eligibility: InvestorEligibilityCreate,
    db: Session = Depends(get_db)
):
    buyer = db.query(UserModel).filter(
        UserModel.id == eligibility.buyer_id
    ).first()

    if buyer is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer not found"
        )

    if buyer.role != "buyer":
        raise HTTPException(
            status_code=400,
            detail="User is not a buyer"
        )

    new_eligibility = InvestorEligibility(
        buyer_id=eligibility.buyer_id,
        investor_type=eligibility.investor_type,
        classification=eligibility.classification,
        status=eligibility.status,
        verification_method=eligibility.verification_method,
        evidence_reference=eligibility.evidence_reference,
        effective_date=eligibility.effective_date,
        review_date=eligibility.review_date,
        jurisdiction=eligibility.jurisdiction
    )

    db.add(new_eligibility)
    db.commit()
    db.refresh(new_eligibility)

    return {
        "message": "Investor eligibility created",
        "investor_eligibility": {
            "id": new_eligibility.id,
            "buyer_id": new_eligibility.buyer_id,
            "investor_type": new_eligibility.investor_type,
            "classification": new_eligibility.classification,
            "status": new_eligibility.status,
            "verification_method": new_eligibility.verification_method,
            "evidence_reference": new_eligibility.evidence_reference,
            "effective_date": new_eligibility.effective_date,
            "review_date": new_eligibility.review_date,
            "jurisdiction": new_eligibility.jurisdiction
        }
    }
@app.post("/compliance-rules")
def create_compliance_rule(
    rule: ComplianceRuleCreate,
    db: Session = Depends(get_db)
):
    existing_rule = db.query(ComplianceRule).filter(
        ComplianceRule.rule_code == rule.rule_code
    ).first()

    if existing_rule is not None:
        raise HTTPException(
            status_code=400,
            detail="Rule code already exists"
        )

    new_rule = ComplianceRule(
        buyer_jurisdiction=rule.buyer_jurisdiction,
        issuer_jurisdiction=rule.issuer_jurisdiction,
        asset_type=rule.asset_type,
        investor_classification=rule.investor_classification,
        rule_code=rule.rule_code,
        description=rule.description,
        decision=rule.decision,
        requires_human_review=rule.requires_human_review,
        active=rule.active,
        source_reference=rule.source_reference
    )

    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)

    return {
        "message": "Compliance rule created",
        "compliance_rule": {
            "id": new_rule.id,
            "buyer_jurisdiction": new_rule.buyer_jurisdiction,
            "issuer_jurisdiction": new_rule.issuer_jurisdiction,
            "asset_type": new_rule.asset_type,
            "investor_classification": new_rule.investor_classification,
            "rule_code": new_rule.rule_code,
            "description": new_rule.description,
            "decision": new_rule.decision,
            "requires_human_review": new_rule.requires_human_review,
            "active": new_rule.active,
            "source_reference": new_rule.source_reference
        }
    }
@app.get("/compliance-rules")
def get_compliance_rules(
    db: Session = Depends(get_db)
):
    rules = db.query(ComplianceRule).all()

    return [
        {
            "id": rule.id,
            "buyer_jurisdiction": rule.buyer_jurisdiction,
            "issuer_jurisdiction": rule.issuer_jurisdiction,
            "asset_type": rule.asset_type,
            "investor_classification": rule.investor_classification,
            "rule_code": rule.rule_code,
            "description": rule.description,
            "decision": rule.decision,
            "requires_human_review": rule.requires_human_review,
            "active": rule.active,
            "source_reference": rule.source_reference
        }
        for rule in rules
    ]


@app.get("/buyer-interests/{interest_id}/matches")
def find_matches(
    interest_id: int,
    db: Session = Depends(get_db)
):
    interest = db.query(BuyerInterest).filter(
        BuyerInterest.id == interest_id
    ).first()

    if interest is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer interest not found"
        )

    buyer = db.query(UserModel).filter(
        UserModel.id == interest.buyer_id
    ).first()

    if buyer is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer not found"
        )
    matches = db.query(ListingModel).filter(
        ListingModel.company == interest.company,
        ListingModel.asset_type == interest.asset_type,
        ListingModel.asking_price <= interest.maximum_price,
        ListingModel.quantity >= interest.desired_quantity
    ).all()

    compliance_results = []

    for listing in matches:
        compliance = check_compliance(buyer, listing, db)

        if compliance["status"] == "blocked":
            match_status = "blocked"
        elif compliance["status"] == "review":
            match_status = "review"
        else:
            match_status = "eligible"

        compliance_results.append({
            "listing_id": listing.id,
            "seller_id": listing.seller_id,
            "company": listing.company,
            "asset_type": listing.asset_type,
            "quantity": listing.quantity,
            "asking_price": float(listing.asking_price),
            "compliance_status": compliance["status"],
            "compliance_reasons": compliance["reasons"],
            "compliance_checks": compliance["checks"],
            "match_status": match_status
        })
    return {
        "buyer_interest_id": interest.id,
        "matches_found": len(matches),
        "matches": compliance_results
    }    

def build_position_passport(listing, db):
    ownership_record = db.query(OwnershipRecord).filter(
        OwnershipRecord.listing_id == listing.id
    ).first()

    ownership_status = ownership_record.verification_status if ownership_record else "not_on_file"

    transferability_result = evaluate_transferability(listing, db)
    transferability_status = transferability_result["status"]
    transferability_summary = "; ".join(transferability_result["reasons"])

    evidence_query = db.query(Evidence).filter(
        Evidence.listing_id == listing.id
    )
    evidence_verified_count = evidence_query.filter(
        Evidence.verification_status == "verified"
    ).count()
    evidence_pending_count = evidence_query.filter(
        Evidence.verification_status != "verified"
    ).count()

    lifecycle_result = build_position_events(listing, db)
    lifecycle_status = lifecycle_result["status"]
    position_quantity = lifecycle_result["current_quantity"]
    quantity_basis = lifecycle_result["quantity_basis"]

    reasons = []

    if ownership_status != "verified":
        reasons.append("Ownership is not yet verified (status: " + ownership_status + ")")

    if transferability_status != "eligible_pending_review":
        reasons.append("Transferability status is '" + transferability_status + "' — " + transferability_summary)

    if evidence_pending_count > 0:
        reasons.append(str(evidence_pending_count) + " piece(s) of evidence still pending verification")

    if lifecycle_status == "conflict":
        reasons.append("Position lifecycle events disagree on quantity — " + quantity_basis)

    if not reasons:
        overall_readiness = "ready"
        reasons.append("Ownership verified, transferability eligible, and all evidence verified — this is not a legal conclusion, human/legal review is still required")
    elif ownership_status != "verified" or transferability_status == "blocked":
        overall_readiness = "not_ready"
    else:
        overall_readiness = "needs_evidence"

    return {
        "ownership_record_id": ownership_record.id if ownership_record else None,
        "ownership_status": ownership_status,
        "transferability_status": transferability_status,
        "transferability_summary": transferability_summary,
        "evidence_verified_count": evidence_verified_count,
        "evidence_pending_count": evidence_pending_count,
        "lifecycle_status": lifecycle_status,
        "position_quantity": position_quantity,
        "quantity_basis": quantity_basis,
        "overall_readiness": overall_readiness,
        "reasons": "; ".join(reasons)
    }


@app.get("/passport/listing/{listing_id}")
def get_position_passport(
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

    result = build_position_passport(listing, db)

    passport = PositionPassport(
        listing_id=listing.id,
        ownership_record_id=result["ownership_record_id"],
        ownership_status=result["ownership_status"],
        transferability_status=result["transferability_status"],
        transferability_summary=result["transferability_summary"],
        evidence_verified_count=result["evidence_verified_count"],
        evidence_pending_count=result["evidence_pending_count"],
        lifecycle_status=result["lifecycle_status"],
        position_quantity=result["position_quantity"],
        quantity_basis=result["quantity_basis"],
        overall_readiness=result["overall_readiness"],
        reasons=result["reasons"],
        issued_at=date.today()
    )

    db.add(passport)
    db.commit()
    db.refresh(passport)

    return {
        "listing_id": listing.id,
        "passport_id": passport.id,
        "ownership_status": result["ownership_status"],
        "transferability_status": result["transferability_status"],
        "evidence_verified_count": result["evidence_verified_count"],
        "evidence_pending_count": result["evidence_pending_count"],
        "lifecycle_status": result["lifecycle_status"],
        "position_quantity": result["position_quantity"],
        "quantity_basis": result["quantity_basis"],
        "overall_readiness": result["overall_readiness"],
        "reasons": result["reasons"],
        "issued_at": passport.issued_at
    }


def build_position_events(listing, db):
    events = db.query(PositionEvent).filter(
        PositionEvent.listing_id == listing.id,
        PositionEvent.superseded_by_id.is_(None)
    ).order_by(PositionEvent.effective_date.asc().nullslast()).all()

    verified_events = [e for e in events if e.verification_status == "verified"]

    ownership_record = db.query(OwnershipRecord).filter(
        OwnershipRecord.listing_id == listing.id
    ).first()

    conflict_events = []

    if verified_events:
        dated_events = [e for e in verified_events if e.effective_date is not None]
        if dated_events:
            latest_date = max(e.effective_date for e in dated_events)
            events_at_latest_date = [e for e in dated_events if e.effective_date == latest_date]
        else:
            latest_date = None
            events_at_latest_date = [e for e in verified_events if e.effective_date is None]

        distinct_quantities = set(e.quantity_after for e in events_at_latest_date)

        if len(events_at_latest_date) > 1 and len(distinct_quantities) > 1:
            conflict_events = events_at_latest_date
            current_quantity = None
            quantity_basis = (
                str(len(events_at_latest_date)) + " verified events disagree on the position quantity as of " +
                (latest_date.isoformat() if latest_date else "an undated effective date") +
                " — issuer or authorized-party verification needed"
            )
        else:
            latest_event = verified_events[-1]
            current_quantity = latest_event.quantity_after
            quantity_basis = (
                "Latest verified event: " + latest_event.event_type +
                " effective " + (latest_event.effective_date.isoformat() if latest_event.effective_date else "unknown date")
            )
    elif ownership_record is not None:
        current_quantity = ownership_record.quantity
        quantity_basis = "No verified position events on file — quantity taken from OwnershipRecord"
    else:
        current_quantity = None
        quantity_basis = "No ownership record or verified position events on file"

    return {
        "current_quantity": current_quantity,
        "quantity_basis": quantity_basis,
        "status": "conflict" if conflict_events else "ok",
        "conflicting_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "effective_date": e.effective_date,
                "source": e.source,
                "submitting_party": e.submitting_party,
                "quantity_after": e.quantity_after
            }
            for e in conflict_events
        ],
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "effective_date": e.effective_date,
                "source": e.source,
                "submitting_party": e.submitting_party,
                "verification_status": e.verification_status,
                "quantity_before": e.quantity_before,
                "quantity_after": e.quantity_after,
                "notes": e.notes
            }
            for e in events
        ]
    }


@app.get("/position-events/listing/{listing_id}")
def get_position_events(
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

    result = build_position_events(listing, db)

    return {
        "listing_id": listing.id,
        "current_quantity": result["current_quantity"],
        "quantity_basis": result["quantity_basis"],
        "status": result["status"],
        "conflicting_events": result["conflicting_events"],
        "events": result["events"]
    }


def get_offering_fact_status(offering_id, fact_type, db):
    facts = db.query(OfferingFact).filter(
        OfferingFact.offering_id == offering_id,
        OfferingFact.fact_type == fact_type,
        OfferingFact.superseded_by_id.is_(None)
    ).all()

    if not facts:
        return ("missing", None)

    verified = [f for f in facts if f.verification_status == "verified"]
    distinct_values = set(f.fact_value for f in verified)

    if len(distinct_values) > 1:
        return ("conflict", None)
    if verified:
        return ("verified", verified[0].fact_value)
    return ("pending", None)


def get_offering_exemption_rule_value(exemption_code, jurisdiction, requirement_type, db):
    rule = db.query(OfferingExemptionRule).filter(
        OfferingExemptionRule.exemption_code == exemption_code,
        OfferingExemptionRule.jurisdiction == jurisdiction,
        OfferingExemptionRule.requirement_type == requirement_type
    ).first()
    if rule is None:
        return None
    return rule.requirement_value


def evaluate_506b(offering, db):
    reasons = []
    blocking = False
    needs_evidence = False
    conflict = False

    if offering.general_solicitation_used:
        reasons.append("506(b) does not permit general solicitation, and this offering uses it")
        blocking = True

    state, value = get_offering_fact_status(offering.id, "bad_actor_disqualification_clear", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for bad actor disqualification")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Bad actor disqualification check not yet verified")
    elif value != "true":
        blocking = True
        reasons.append("A bad actor disqualification event was found among covered persons")

    state, value = get_offering_fact_status(offering.id, "non_accredited_investor_count", db)
    non_accredited_count = None
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for non-accredited investor count")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Non-accredited investor count not yet verified")
    else:
        try:
            non_accredited_count = int(value)
            if non_accredited_count > 35:
                blocking = True
                reasons.append("More than 35 non-accredited investors (" + value + ") exceeds the 506(b) limit")
        except ValueError:
            needs_evidence = True
            reasons.append("Non-accredited investor count fact value is not a valid number")

    if non_accredited_count is not None and non_accredited_count > 0:
        state, value = get_offering_fact_status(offering.id, "non_accredited_investors_sophisticated", db)
        if state == "conflict":
            conflict = True
            reasons.append("Conflicting verified facts for non-accredited investor sophistication")
        elif state in ("missing", "pending"):
            needs_evidence = True
            reasons.append("Non-accredited investor sophistication not yet verified")
        elif value != "true":
            blocking = True
            reasons.append("Non-accredited investors have not been confirmed sophisticated")

        state, value = get_offering_fact_status(offering.id, "disclosure_provided_to_non_accredited", db)
        if state == "conflict":
            conflict = True
            reasons.append("Conflicting verified facts for non-accredited disclosure")
        elif state in ("missing", "pending"):
            needs_evidence = True
            reasons.append("Required disclosure to non-accredited investors not yet verified")
        elif value != "true":
            blocking = True
            reasons.append("Required disclosure has not been provided to non-accredited investors")

    if conflict:
        status = "conflict"
    elif blocking:
        status = "ineligible"
    elif needs_evidence:
        status = "needs_evidence"
    else:
        status = "eligible"

    if not reasons:
        reasons.append(
            "All checked facts for 506(b) are present and verified \u2014 this is not a legal conclusion, human/legal review is still required"
        )

    return {"exemption_code": "US-REG-D-506B", "status": status, "reasons": reasons}


def evaluate_506c(offering, db):
    reasons = []
    blocking = False
    needs_evidence = False
    conflict = False

    state, value = get_offering_fact_status(offering.id, "bad_actor_disqualification_clear", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for bad actor disqualification")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Bad actor disqualification check not yet verified")
    elif value != "true":
        blocking = True
        reasons.append("A bad actor disqualification event was found among covered persons")

    state, value = get_offering_fact_status(offering.id, "all_investors_accredited", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for investor accreditation status")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Investor accreditation status not yet verified")
    elif value != "true":
        blocking = True
        reasons.append("506(c) requires all investors to be accredited \u2014 at least one is not")

    state, value = get_offering_fact_status(offering.id, "accreditation_verification_documented", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for accreditation verification documentation")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Documented \'reasonable steps to verify\' accreditation not yet on file")
    elif value != "true":
        blocking = True
        reasons.append("506(c) requires documented reasonable steps to verify accreditation \u2014 self-certification alone is not sufficient")

    if conflict:
        status = "conflict"
    elif blocking:
        status = "ineligible"
    elif needs_evidence:
        status = "needs_evidence"
    else:
        status = "eligible"

    if not reasons:
        reasons.append(
            "All checked facts for 506(c) are present and verified \u2014 this is not a legal conclusion, human/legal review is still required"
        )

    return {"exemption_code": "US-REG-D-506C", "status": status, "reasons": reasons}


def evaluate_regcf(offering, db):
    reasons = []
    blocking = False
    needs_evidence = False
    conflict = False

    cap_value = get_offering_exemption_rule_value("US-REG-CF", offering.jurisdiction, "raise_cap_12mo", db)
    if cap_value is None:
        needs_evidence = True
        reasons.append("Regulation Crowdfunding raise cap is not on file for this jurisdiction")
    elif offering.target_raise_amount is None:
        needs_evidence = True
        reasons.append("Offering has no target raise amount on file")
    else:
        try:
            cap_amount = float(cap_value)
            if float(offering.target_raise_amount) > cap_amount:
                blocking = True
                reasons.append(
                    "Target raise amount (" + str(offering.target_raise_amount) +
                    ") exceeds the Regulation Crowdfunding rolling 12-month cap (" + str(cap_amount) + ")"
                )
        except (TypeError, ValueError):
            needs_evidence = True
            reasons.append("Regulation Crowdfunding raise cap value on file is not a valid number")

    state, value = get_offering_fact_status(offering.id, "bad_actor_disqualification_clear", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for bad actor disqualification")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Bad actor disqualification check not yet verified")
    elif value != "true":
        blocking = True
        reasons.append("A bad actor disqualification event was found among covered persons")

    state, value = get_offering_fact_status(offering.id, "funding_portal_or_broker_dealer_used", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for funding portal / broker-dealer use")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Use of an SEC-registered funding portal or broker-dealer not yet verified")
    elif value != "true":
        blocking = True
        reasons.append("Regulation Crowdfunding requires selling through an SEC-registered funding portal or broker-dealer")

    if conflict:
        status = "conflict"
    elif blocking:
        status = "ineligible"
    elif needs_evidence:
        status = "needs_evidence"
    else:
        status = "eligible"

    if not reasons:
        reasons.append(
            "All checked facts for Regulation Crowdfunding are present and verified \u2014 this is not a legal conclusion, human/legal review is still required"
        )

    return {"exemption_code": "US-REG-CF", "status": status, "reasons": reasons}


def evaluate_reg_a_tier1(offering, db):
    reasons = []
    blocking = False
    needs_evidence = False
    conflict = False

    cap_value = get_offering_exemption_rule_value("US-REG-A-TIER1", offering.jurisdiction, "raise_cap_12mo", db)
    if cap_value is None:
        needs_evidence = True
        reasons.append("Regulation A+ Tier 1 raise cap is not on file for this jurisdiction")
    elif offering.target_raise_amount is None:
        needs_evidence = True
        reasons.append("Offering has no target raise amount on file")
    else:
        try:
            cap_amount = float(cap_value)
            if float(offering.target_raise_amount) > cap_amount:
                blocking = True
                reasons.append(
                    "Target raise amount (" + str(offering.target_raise_amount) +
                    ") exceeds the Regulation A+ Tier 1 12-month cap (" + str(cap_amount) + ")"
                )
        except (TypeError, ValueError):
            needs_evidence = True
            reasons.append("Regulation A+ Tier 1 raise cap value on file is not a valid number")

    state, value = get_offering_fact_status(offering.id, "bad_actor_disqualification_clear", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for bad actor disqualification")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Bad actor disqualification check not yet verified")
    elif value != "true":
        blocking = True
        reasons.append("A bad actor disqualification event was found among covered persons")

    state, value = get_offering_fact_status(offering.id, "sec_qualification_obtained", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for SEC qualification status")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("SEC qualification under Form 1-A has not yet been verified as obtained")
    elif value != "true":
        blocking = True
        reasons.append("Regulation A+ requires actual SEC qualification, not just a filed application")

    if conflict:
        status = "conflict"
    elif blocking:
        status = "ineligible"
    elif needs_evidence:
        status = "needs_evidence"
    else:
        status = "eligible"

    if not reasons:
        reasons.append(
            "All checked facts for Regulation A+ Tier 1 are present and verified \u2014 this is not a legal conclusion, human/legal review is still required"
        )

    return {"exemption_code": "US-REG-A-TIER1", "status": status, "reasons": reasons}


def evaluate_reg_a_tier2(offering, db):
    reasons = []
    blocking = False
    needs_evidence = False
    conflict = False

    cap_value = get_offering_exemption_rule_value("US-REG-A-TIER2", offering.jurisdiction, "raise_cap_12mo", db)
    if cap_value is None:
        needs_evidence = True
        reasons.append("Regulation A+ Tier 2 raise cap is not on file for this jurisdiction")
    elif offering.target_raise_amount is None:
        needs_evidence = True
        reasons.append("Offering has no target raise amount on file")
    else:
        try:
            cap_amount = float(cap_value)
            if float(offering.target_raise_amount) > cap_amount:
                blocking = True
                reasons.append(
                    "Target raise amount (" + str(offering.target_raise_amount) +
                    ") exceeds the Regulation A+ Tier 2 12-month cap (" + str(cap_amount) + ")"
                )
        except (TypeError, ValueError):
            needs_evidence = True
            reasons.append("Regulation A+ Tier 2 raise cap value on file is not a valid number")

    state, value = get_offering_fact_status(offering.id, "bad_actor_disqualification_clear", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for bad actor disqualification")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Bad actor disqualification check not yet verified")
    elif value != "true":
        blocking = True
        reasons.append("A bad actor disqualification event was found among covered persons")

    state, value = get_offering_fact_status(offering.id, "sec_qualification_obtained", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for SEC qualification status")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("SEC qualification under Form 1-A has not yet been verified as obtained")
    elif value != "true":
        blocking = True
        reasons.append("Regulation A+ requires actual SEC qualification, not just a filed application")

    state, value = get_offering_fact_status(offering.id, "tier2_non_accredited_limits_compliance_documented", db)
    if state == "conflict":
        conflict = True
        reasons.append("Conflicting verified facts for Tier 2 non-accredited investment limit compliance")
    elif state in ("missing", "pending"):
        needs_evidence = True
        reasons.append("Tier 2 non-accredited investment limit compliance not yet verified")
    elif value != "true":
        blocking = True
        reasons.append("Tier 2 requires documented compliance with the 10%-of-income/net-worth non-accredited investment limit")

    if conflict:
        status = "conflict"
    elif blocking:
        status = "ineligible"
    elif needs_evidence:
        status = "needs_evidence"
    else:
        status = "eligible"

    if not reasons:
        reasons.append(
            "All checked facts for Regulation A+ Tier 2 are present and verified \u2014 this is not a legal conclusion, human/legal review is still required"
        )

    return {"exemption_code": "US-REG-A-TIER2", "status": status, "reasons": reasons}


def evaluate_offering_exemptions(offering, db):
    return [
        evaluate_506b(offering, db),
        evaluate_506c(offering, db),
        evaluate_regcf(offering, db),
        evaluate_reg_a_tier1(offering, db),
        evaluate_reg_a_tier2(offering, db)
    ]


@app.get("/offering-exemptions/{offering_id}")
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
    }

