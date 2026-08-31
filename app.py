from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Listing as ListingModel
from models import User as UserModel
from models import OwnershipRecord, Transaction, BuyerInterest
from models import Transaction

app = FastAPI(title="KEVO API")


class UserCreate(BaseModel):
    name: str
    email: str
    role: str = "buyer"


class ListingCreate(BaseModel):
    seller_id: int
    listing_id: int | None = None
    company: str
    asset_type: str
    quantity: int
    asking_price: float

class OwnershipCreate(BaseModel):
    listing_id: int
    seller_id: int
    company: str
    asset_type: str
    quantity: int


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
        role=user.role
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
            "role": new_user.role
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
        quantity=ownership.quantity
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
        asking_price=listing.asking_price
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
            "asking_price": float(new_listing.asking_price)
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

    matches = db.query(ListingModel).filter(
        ListingModel.company == interest.company,
        ListingModel.asset_type == interest.asset_type,
        ListingModel.asking_price <= interest.maximum_price,
        ListingModel.quantity >= interest.desired_quantity
    ).all()

    return {
        "buyer_interest_id": interest.id,
        "matches_found": len(matches),
        "matches": [
            {
                "listing_id": listing.id,
                "seller_id": listing.seller_id,
                "company": listing.company,
                "asset_type": listing.asset_type,
                "quantity": listing.quantity,
                "asking_price": float(listing.asking_price)
            }
            for listing in matches
        ]
    }    