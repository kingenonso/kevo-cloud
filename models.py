from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Boolean, Date, DateTime
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
    hashed_password = Column(String(255), nullable=True)
    account_type = Column(String(50), nullable=False, default="participant")
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)

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

    fact_type = Column(
        String(100),
        nullable=False
    )

    fact_validity_days = Column(
        Integer,
        nullable=True
    )

    requirement = Column(
        String(500),
        nullable=False
    )

    decision_if_unmet = Column(
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
    file_hash = Column(String(64), nullable=True)
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
    superseded_by_id = Column(Integer, ForeignKey("transferability_facts.id"), nullable=True)


class KYCFact(Base):
    __tablename__ = "kyc_facts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    jurisdiction = Column(String(100), nullable=True)
    fact_type = Column(String(100), nullable=False)
    fact_value = Column(String(500), nullable=False)
    as_of_date = Column(Date, nullable=True)
    verification_status = Column(String(50), nullable=False, default="pending")
    evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=True)
    source_reference = Column(String(500), nullable=True)
    superseded_by_id = Column(Integer, ForeignKey("kyc_facts.id"), nullable=True)


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
    expected_fact_value = Column(String(500), nullable=True)
    
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
    
class PositionPassport(Base):
    __tablename__ = "position_passports"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    ownership_record_id = Column(Integer, ForeignKey("ownership_records.id"), nullable=True)
    ownership_status = Column(String(50), nullable=False)
    transferability_status = Column(String(50), nullable=False)
    transferability_summary = Column(String(500), nullable=True)
    evidence_verified_count = Column(Integer, nullable=False, default=0)
    evidence_pending_count = Column(Integer, nullable=False, default=0)
    lifecycle_status = Column(String(50), nullable=True)
    position_quantity = Column(Integer, nullable=True)
    quantity_basis = Column(String(500), nullable=True)
    overall_readiness = Column(String(50), nullable=False, default="review")
    reasons = Column(String(500), nullable=False)
    issued_at = Column(Date, nullable=True)
    source_reference = Column(String(500), nullable=True)

class PositionEvent(Base):
    __tablename__ = "position_events"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    ownership_record_id = Column(Integer, ForeignKey("ownership_records.id"), nullable=True)
    event_type = Column(String(50), nullable=False)
    effective_date = Column(Date, nullable=True)
    source = Column(String(100), nullable=False)
    submitting_party = Column(String(200), nullable=True)
    evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=True)
    verification_status = Column(String(50), nullable=False, default="pending")
    quantity_before = Column(Integer, nullable=True)
    quantity_after = Column(Integer, nullable=True)
    notes = Column(String(500), nullable=True)
    source_reference = Column(String(500), nullable=True)
    superseded_by_id = Column(Integer, ForeignKey("position_events.id"), nullable=True)

class Offering(Base):
    __tablename__ = "offerings"

    id = Column(Integer, primary_key=True)
    issuer_name = Column(String(200), nullable=False)
    jurisdiction = Column(String(100), nullable=False)
    target_raise_amount = Column(Numeric, nullable=True)
    offering_start_date = Column(Date, nullable=True)
    offering_end_date = Column(Date, nullable=True)
    general_solicitation_used = Column(Boolean, nullable=False, default=False)
    status = Column(String(50), nullable=False, default="planning")

class OfferingFact(Base):
    __tablename__ = "offering_facts"

    id = Column(Integer, primary_key=True)
    offering_id = Column(Integer, ForeignKey("offerings.id"), nullable=False)
    evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=True)
    fact_type = Column(String(100), nullable=False)
    fact_value = Column(String(500), nullable=False)
    as_of_date = Column(Date, nullable=True)
    verification_status = Column(String(50), nullable=False, default="pending")
    source_reference = Column(String(500), nullable=True)
    superseded_by_id = Column(Integer, ForeignKey("offering_facts.id"), nullable=True)

class OfferingExemptionRule(Base):
    __tablename__ = "offering_exemption_rules"

    id = Column(Integer, primary_key=True)
    jurisdiction = Column(String(100), nullable=False)
    exemption_code = Column(String(100), nullable=False)
    requirement_type = Column(String(100), nullable=False)
    requirement_value = Column(String(500), nullable=False)
    source_reference = Column(String(500), nullable=False)
    last_verified_date = Column(Date, nullable=True)
    review_by = Column(Date, nullable=True)

class OfferingExemptionAssessment(Base):
    __tablename__ = "offering_exemption_assessments"

    id = Column(Integer, primary_key=True)
    offering_id = Column(Integer, ForeignKey("offerings.id"), nullable=False)
    exemption_code = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)
    reasons = Column(String(500), nullable=False)
    assessed_at = Column(Date, nullable=True)

class LiquidityPathStep(Base):
    __tablename__ = "liquidity_path_steps"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    ownership_record_id = Column(Integer, ForeignKey("ownership_records.id"), nullable=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    run_id = Column(String(64), nullable=False)
    computed_at = Column(Date, nullable=True)
    step_type = Column(String(50), nullable=False)
    sequence_position = Column(Integer, nullable=False)
    required = Column(Boolean, nullable=True)
    complete = Column(Boolean, nullable=False, default=False)
    evidence_reference_type = Column(String(100), nullable=True)
    evidence_reference_id = Column(Integer, nullable=True)
    responsible_party = Column(String(50), nullable=False)
    blocking_step_id = Column(Integer, ForeignKey("liquidity_path_steps.id"), nullable=True)
    completion_trigger = Column(String(500), nullable=True)
    determinability = Column(String(50), nullable=False, default="cannot_determine")
    reasons = Column(String(500), nullable=False)
    source_milestone = Column(String(100), nullable=True)


class RofrRequest(Base):
    """
    M25 (first slice) - Right of First Refusal, consent request + response
    log. Deliberately NOT deadline-driven: no jurisdiction has a real,
    sourced ROFR response-window on file (TransferabilityRule.hold_period_days
    means something different - time held before sale, not time to
    respond to a ROFR notice - and is empty for the one real ROFR rule
    that exists, ZA-COMPANIES-S8-ROFR-CONSENT). Also deliberately avoids
    an auto-triggered countdown, the specific mechanism flagged as
    patent-adjacent in claude/kevo-m25-rofr-patent-claim-analysis.md
    (Nasdaq Private Market US 12,572,980). KEVO has no "issuer" or
    "existing shareholder" user concept yet, so this follows the same
    self-submit/admin-verify pattern already used for Evidence, KYCFact,
    and OwnershipRecord: the seller (who actually needs the consent)
    submits the request; only an admin can record the real-world response.
    """
    __tablename__ = "rofr_requests"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    transferability_rule_id = Column(Integer, ForeignKey("transferability_rules.id"), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    response_notes = Column(String(1000), nullable=True)
    responded_at = Column(DateTime, nullable=True)
    source_reference = Column(String(500), nullable=True)
