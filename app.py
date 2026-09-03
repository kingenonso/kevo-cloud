from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from datetime import date
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Listing as ListingModel
from models import User as UserModel
from models import OwnershipRecord, Transaction, BuyerInterest, InvestorEligibility, ComplianceRule
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
    OwnershipRecord.seller_id == listing.seller_id
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
        issuer_current_information_available=listing.issuer_current_information_available
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
            "issuer_current_information_available": new_listing.issuer_current_information_available
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
