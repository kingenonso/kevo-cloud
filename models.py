from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Boolean, Date
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(50), nullable=False, default="seller")
    kyc_status = Column(String(50), nullable=False, default="not_started")
    jurisdiction = Column(String(100), nullable=True)
    seller_affiliate_status = Column(String(50), nullable=True)

    listings = relationship("Listing", back_populates="seller")


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    company = Column(String(255), nullable=False)
    asset_type = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    asking_price = Column(Numeric(15, 2), nullable=False)
    is_transferable = Column(Boolean, nullable=False, default=False)
    issuer_jurisdiction = Column(String(100), nullable=True)
    issuer_reporting_status = Column(String(50), nullable=True)
    issuer_current_information_available = Column(Boolean, nullable=True)

    seller = relationship("User", back_populates="listings")

class OwnershipRecord(Base):
    __tablename__ = "ownership_records"

    id = Column(Integer, primary_key=True)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    company = Column(String(255), nullable=False)
    asset_type = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    acquisition_date = Column(Date, nullable=True)
    verification_status = Column(
        String(50),
        nullable=False,
        default="pending"
    )
    verification_reference = Column(String(255), nullable=True)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)

    listing_id = Column(
        Integer,
        ForeignKey("listings.id"),
        nullable=False
    )

    buyer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    seller_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    quantity = Column(Integer, nullable=False)

    agreed_price = Column(
        Numeric(15, 2),
        nullable=False
    )

    status = Column(
        String(50),
        nullable=False,
        default="interested"
    )

class BuyerInterest(Base):
    __tablename__ = "buyer_interests"

    id = Column(Integer, primary_key=True)

    buyer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    company = Column(
        String(255),
        nullable=False
    )

    asset_type = Column(
        String(100),
        nullable=False
    )

    desired_quantity = Column(
        Integer,
        nullable=False
    )

    maximum_price = Column(
        Numeric(15, 2),
        nullable=False
    )

    status = Column(
        String(50),
        nullable=False,
        default="active"
    )    
class InvestorEligibility(Base):
    __tablename__ = "investor_eligibility"

    id = Column(Integer, primary_key=True)

    buyer_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    investor_type = Column(
        String(100),
        nullable=False
    )

    classification = Column(
        String(150),
        nullable=False
    )

    status = Column(
        String(50),
        nullable=False,
        default="pending"
    )

    verification_method = Column(
        String(150),
        nullable=True
    )

    evidence_reference = Column(
        String(255),
        nullable=True
    )

    effective_date = Column(
        Date,
        nullable=True
    )

    review_date = Column(
        Date,
        nullable=True
    )

    jurisdiction = Column(
        String(100),
        nullable=True
    )
class ComplianceRule(Base):
    __tablename__ = "compliance_rules"

    id = Column(Integer, primary_key=True)

    buyer_jurisdiction = Column(
        String(100),
        nullable=True
    )

    issuer_jurisdiction = Column(
        String(100),
        nullable=True
    )

    asset_type = Column(
        String(100),
        nullable=True
    )

    investor_classification = Column(
        String(150),
        nullable=True
    )

    rule_code = Column(
        String(100),
        nullable=False,
        unique=True
    )

    description = Column(
        String(500),
        nullable=False
    )

    decision = Column(
        String(50),
        nullable=False
    )

    requires_human_review = Column(
        Boolean,
        nullable=False,
        default=True
    )

    active = Column(
        Boolean,
        nullable=False,
        default=True
    )

    source_reference = Column(
        String(500),
        nullable=True
    )
    
class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    ownership_record_id = Column(Integer, ForeignKey("ownership_records.id"), nullable=True)
    evidence_type = Column(String(100), nullable=False)
    description = Column(String(500), nullable=False)
    file_reference = Column(String(500), nullable=True)
    verification_status = Column(String(50), nullable=False, default="pending")
    source_reference = Column(String(500), nullable=True)

class TransferabilityFact(Base):
    __tablename__ = "transferability_facts"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    ownership_record_id = Column(Integer, ForeignKey("ownership_records.id"), nullable=True)
    evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=True)
    jurisdiction = Column(String(100), nullable=False)
    fact_type = Column(String(100), nullable=False)
    fact_value = Column(String(500), nullable=False)
    as_of_date = Column(Date, nullable=True)
    verification_status = Column(String(50), nullable=False, default="pending")
    source_reference = Column(String(500), nullable=True)

class TransferabilityRule(Base):
    __tablename__ = "transferability_rules"

    id = Column(Integer, primary_key=True)
    jurisdiction = Column(String(100), nullable=False)
    asset_type = Column(String(100), nullable=False)
    fact_type = Column(String(100), nullable=False)
    rule_code = Column(String(100), nullable=False, unique=True)
    requirement = Column(String(500), nullable=False)
    decision_if_unmet = Column(String(50), nullable=False)
    requires_human_review = Column(Boolean, nullable=False, default=True)
    active = Column(Boolean, nullable=False, default=True)
    last_verified_date = Column(Date, nullable=True)
    review_by = Column(Date, nullable=True)
    source_reference = Column(String(500), nullable=True)
    hold_period_days = Column(Integer, nullable=True)
    
class TransferabilityAssessment(Base):
    __tablename__ = "transferability_assessments"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    ownership_record_id = Column(Integer, ForeignKey("ownership_records.id"), nullable=True)
    status = Column(String(50), nullable=False, default="review")
    explanation = Column(String(500), nullable=False)
    path_to_eligibility = Column(String(500), nullable=True)
    forecast_date = Column(Date, nullable=True)
    source_reference = Column(String(500), nullable=True)