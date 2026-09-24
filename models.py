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
    tokens_valid_since = Column(DateTime, nullable=True)
    # Batch B accountability extension (2026-09-24): a real, first-party
    # consequence for defaulting on a seller-financing agreement -- KEVO
    # restricting the buyer's OWN account on KEVO's OWN platform, not a
    # credit report compiled for other companies to use (that would risk
    # FCRA "consumer reporting agency" exposure). Admin-lifted only, same
    # posture as every other "only an admin can attest this is resolved"
    # gate already in the app (verify_ownership, kyc-status, etc.).
    seller_financing_blocked = Column(Boolean, nullable=False, default=False)
    seller_financing_blocked_at = Column(DateTime, nullable=True)
    seller_financing_blocked_reason = Column(String(1000), nullable=True)
    phone_number = Column(String(30), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    terms_accepted = Column(Boolean, nullable=False, default=False)
    terms_accepted_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    deactivated_at = Column(DateTime, nullable=True)
    deactivation_reason = Column(String(500), nullable=True)

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

    # M26C (2026-09-19): KEVO deliberately does not attempt to handle
    # cross-currency FX risk itself - dedicated research found the closest
    # real precedent (EquityZen) sidesteps the problem the same way: every
    # transaction settles in a single currency, and any conversion a
    # non-USD party needs happens at their own bank, entirely outside
    # KEVO. This column makes that already-implicit assumption explicit
    # and queryable for the first time, rather than leaving it undefined.
    # Deliberately fixed, not derived from listing/buyer/seller
    # jurisdiction - introducing a currency-per-jurisdiction mapping would
    # recreate the FX-tracking problem this design choice avoids.
    settlement_currency = Column(
        String(3),
        nullable=False,
        default="USD"
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
    escrow_release_initiated = Column(Boolean, nullable=False, default=False)
    responded_at = Column(DateTime, nullable=True)
    source_reference = Column(String(500), nullable=True)
class PasswordResetToken(Base):
    """
    Full-gap-closure pass (Batch B, group 3 item 15), 2026-09-24 - the
    real forgot-password flow that's been a flagged gap since M18/M28
    (a user locked out with no way to prove identity by email had no
    path back in). Stores only a SHA-256 hash of the reset token, never
    the raw value - the raw token exists only in the emailed link and
    the requester's browser, mirroring how KEVO never stores a raw
    password either. Single-use (used_at) and time-limited (expires_at).
    """
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class SettlementRecord(Base):
    """
    M26 (first slice) - Settlement status tracking, orchestration-only.

    KEVO never holds client funds or acts as custodian - that would create
    real money-transmitter and (per the California DFPI Escrow Law example
    already researched) potentially state escrow-licensing exposure. This
    table tracks the real-world confirmations a licensed escrow/bank
    provider would report once KEVO integrates with one - it does not move
    money itself. Every field is admin-recorded because, until a real
    provider integration exists, these are facts only KEVO's own team can
    attest to; a buyer or seller can never self-declare "funds received."

    Release is deliberately sequential, not atomic: funds_released can only
    be set once both funds_received and shares_confirmed_transferable are
    true. True delivery-versus-payment (money and shares becoming
    conditional on each other atomically) is M26E's scope, built on top of
    this table, not this first slice's.
    """
    __tablename__ = "settlement_records"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, unique=True)
    status = Column(String(50), nullable=False, default="pending")
    escrow_provider_reference = Column(String(500), nullable=True)
    funds_received = Column(Boolean, nullable=False, default=False)
    funds_received_at = Column(DateTime, nullable=True)
    shares_confirmed_transferable = Column(Boolean, nullable=False, default=False)
    shares_confirmed_transferable_at = Column(DateTime, nullable=True)
    funds_released = Column(Boolean, nullable=False, default=False)
    funds_released_at = Column(DateTime, nullable=True)
    notes = Column(String(1000), nullable=True)
    escrow_release_initiated = Column(Boolean, nullable=False, default=False)


class LoanRequest(Base):
    """
    M26B (first slice) - Share-backed lending, broker/matcher only.

    KEVO never originates a loan, never funds one, and never takes or holds
    the collateral itself - a holder's shares stay exactly where they
    already are. This table tracks a holder's request to borrow against
    verified shares through to a real, licensed external lender: KEVO
    connects and tracks, it does not lend. Matching to a real lender
    (name/reference) and closing the record are admin-recorded, mirroring
    SettlementRecord's pattern - these are facts only KEVO's own team can
    attest to until a real lender integration exists.
    """
    __tablename__ = "loan_requests"

    id = Column(Integer, primary_key=True)
    holder_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ownership_record_id = Column(Integer, ForeignKey("ownership_records.id"), nullable=False)
    requested_amount = Column(Numeric(15, 2), nullable=False)
    status = Column(String(50), nullable=False, default="requested")
    external_lender_name = Column(String(255), nullable=True)
    external_lender_reference = Column(String(255), nullable=True)
    matched_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    notes = Column(String(1000), nullable=True)
    escrow_release_initiated = Column(Boolean, nullable=False, default=False)


class OptionFundingReferral(Base):
    """
    M26D (first slice) - Option Exercise Funding, referral/tracking only.

    Research found this milestone is NOT a lighter version of M26B's
    share-backed lending: real option-exercise funders (EquityBee, Secfi,
    ESO Fund) structure the product as a prepaid variable forward contract
    - the same instrument class that got M25B parked over SEC
    swap-reclassification risk - and comply with securities law by running
    their investor side through their own registered broker-dealer
    subsidiary, restricted to accredited investors. That is a heavier lift
    than anything KEVO has built. So KEVO builds nothing of the financial
    instrument itself here: this table only tracks that a holder asked for
    a referral, and that KEVO's own team pointed them at a named, real,
    already-licensed provider who handles the entire funding arrangement
    independently. KEVO originates nothing, structures nothing, and holds
    no interest in the outcome.
    """
    __tablename__ = "option_funding_referrals"

    id = Column(Integer, primary_key=True)
    holder_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company = Column(String(255), nullable=False)
    notes = Column(String(1000), nullable=True)
    escrow_release_initiated = Column(Boolean, nullable=False, default=False)
    status = Column(String(50), nullable=False, default="requested")
    referred_provider_name = Column(String(255), nullable=True)
    referred_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)

class ComplianceDecisionLedger(Base):
    """
    M27 (first slice) - Hash-Chained Compliance Decision Ledger.

    Audit found real assess_compliance() decisions were never persisted
    anywhere - every call (matching, transaction creation, Deal Health
    Score, Deal Room, ROFR requests) computed live and was thrown away,
    with no way to later prove what KEVO's system actually told a specific
    buyer about a specific listing at a specific point in time. Also found:
    compliance never actually gates a transaction today - create_transaction()
    doesn't call assess_compliance() at all. So this table snapshots the real
    compliance verdict at two real, meaningful transaction lifecycle moments -
    creation and every status change - purely informational, never blocking,
    preserving the standing no-trade-term-setting invariant (2026-09-09).
    Each entry is cryptographically chained to the one immediately before it
    across the whole platform (one global chain, not per-transaction), so the
    decision history can be mathematically proven untampered - not just
    logged. Append-only: no API endpoint writes to this table directly, only
    internal application logic does, at the two trigger points above.
    """
    __tablename__ = "compliance_decision_ledger"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    decision_status = Column(String(50), nullable=False)
    explanation = Column(String(1000), nullable=True)
    applicable_rule_codes = Column(String(500), nullable=False)
    triggered_by = Column(String(100), nullable=False)
    decided_at = Column(DateTime, nullable=False)
    previous_hash = Column(String(64), nullable=False)
    entry_hash = Column(String(64), nullable=False)



class TenderOfferProgram(Base):
    """
    M30B (first slice) - Company-Sponsored Tender Offer Program.
    KEVO has no "company"/"issuer" login-capable actor (confirmed by direct
    audit, 2026-09-20) and building one was confirmed out of scope for this
    milestone. Follows the same admin-administered pattern already used for
    RofrRequest and SettlementRecord: an admin creates and manages a program
    on a real company's behalf, recording price/window/eligibility the
    company already agreed to outside the platform - KEVO never sets or
    suggests these terms itself, preserving the standing no-trade-term-
    setting invariant (2026-09-09). Jurisdictional research (2026-09-20,
    claude/kevo-m30b-tender-offer-program-research-and-audit.md) found this
    is fundamentally a corporate-governance matter (a resolution the company
    and its shareholders make themselves) in 5 of KEVO's 6 active
    jurisdictions - Canada is deliberately excluded (enforced in app.py, not
    here) since it currently lacks a clean small-private-company issuer-bid
    exemption; the CSA's proposed Selective Repurchase Exemption is not yet
    in force.
    """
    __tablename__ = "tender_offer_programs"

    id = Column(Integer, primary_key=True)
    company = Column(String(255), nullable=False)
    jurisdiction = Column(String(100), nullable=False)
    price_per_share = Column(Numeric(15, 2), nullable=False)
    opens_at = Column(DateTime, nullable=False)
    closes_at = Column(DateTime, nullable=False)
    status = Column(String(50), nullable=False, default="open")
    source_reference = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False)


class TenderOfferElection(Base):
    """
    M30B (first slice) - a holder's election to participate in a
    TenderOfferProgram. Self-submit by the holder (mirroring
    LoanRequest/OptionFundingReferral), gated on the same verified-ownership
    check M13/M26B already enforce elsewhere. shares_accepted stays null
    until an admin finalizes the election, recording the company's own real
    allocation decision - KEVO never computes or suggests an allocation.
    """
    __tablename__ = "tender_offer_elections"

    id = Column(Integer, primary_key=True)
    program_id = Column(Integer, ForeignKey("tender_offer_programs.id"), nullable=False)
    ownership_record_id = Column(Integer, ForeignKey("ownership_records.id"), nullable=False)
    holder_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shares_offered = Column(Integer, nullable=False)
    shares_accepted = Column(Integer, nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False)
    decided_at = Column(DateTime, nullable=True)


class DealAlert(Base):
    """
    M31 (first slice, 2026-09-21) - Smart Deal Alerts.

    Reuses the exact same non-discretionary matching criteria as
    find_matches() (GET /buyer-interests/{id}/matches) - company,
    asset_type, price, quantity - fired automatically when a new listing
    is created that matches an existing active BuyerInterest, so a buyer
    doesn't have to keep re-checking manually. Flat and chronological by
    design, never ranked or scored - matching M11's own corrected
    no-scoring posture, kept for the same Rule 3b-16 non-discretionary
    reasons.
    """
    __tablename__ = "deal_alerts"

    id = Column(Integer, primary_key=True)
    buyer_interest_id = Column(Integer, ForeignKey("buyer_interests.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_read = Column(Boolean, nullable=False, default=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False)



class AuditLogEntry(Base):
    """
    Full-gap-closure pass (Batch B, group 3 item 8), 2026-09-24 - M22's
    security audit explicitly deferred this as its own real design
    decision, not something to fold quietly into a "quick wins" pass.
    Records a curated set of security/compliance-relevant events - never
    an attempt to log everything the platform does. actor_user_id is
    nullable because some events (a failed login against a real email
    that still doesn't verify) are worth recording even when there is no
    fully-authenticated actor for the request itself. Admin-only reads,
    via GET /audit-log. Append-only by convention - nothing in app.py
    ever updates or deletes a row here.
    """
    __tablename__ = "audit_log_entries"

    id = Column(Integer, primary_key=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=True)
    target_id = Column(Integer, nullable=True)
    detail = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False)


class SellerFinancingAgreement(Base):
    """
    Batch B Group 3 item 9 (2026-09-24) - Seller Financing, tracking-only.

    Dedicated research (the Reves v. Ernst & Young "family resemblance"
    test for when a note is a security, TILA's business-purpose exemption,
    and state-by-state usury variation) found this is buildable safely
    under the same posture already approved for M26B/M26C/M26D: KEVO never
    originates, funds, holds, or services this credit arrangement. The
    seller and buyer negotiate their own principal, interest rate, and
    term directly - the same caller-supplied-terms invariant already
    enforced on Transaction.agreed_price - and KEVO only records the
    agreement and its scheduled payments. No money moves through KEVO for
    the installment payments; that happens directly between buyer and
    seller, exactly as it would with no platform involved at all. Because
    the note is a single, privately-negotiated, bilateral instrument tied
    to one specific already-agreed transaction (never pooled, marketed, or
    resold to other investors), it lands on the "not a security" side of
    the Reves test - the same shape as an ordinary seller note in a
    business sale. Because the purpose is buying an investment asset (not
    a personal/household loan), it's exempt from TILA/Reg Z by design.
    Usury limits vary by jurisdiction and are the contracting parties' own
    responsibility, exactly like KEVO never validates agreed_price against
    any jurisdiction's pricing rules.
    """
    __tablename__ = "seller_financing_agreements"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False, unique=True)
    principal_amount = Column(Numeric(15, 2), nullable=False)
    annual_interest_rate_pct = Column(Numeric(6, 3), nullable=False, default=0)
    term_months = Column(Integer, nullable=False)
    payment_frequency = Column(String(20), nullable=False, default="monthly")
    first_payment_due_date = Column(Date, nullable=False)
    status = Column(String(50), nullable=False, default="active")
    source_reference = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False)
    default_reason = Column(String(1000), nullable=True)
    defaulted_at = Column(DateTime, nullable=True)
    resolution_notes = Column(String(1000), nullable=True)
    resolved_at = Column(DateTime, nullable=True)


class SellerFinancingPayment(Base):
    """
    One scheduled installment under a SellerFinancingAgreement. The full
    schedule is generated deterministically (standard amortization math)
    from the agreement's own caller-supplied principal/rate/term/frequency
    at creation time - KEVO computes the arithmetic, never the terms
    themselves. The seller (who is owed the money) marks a payment
    received; KEVO never independently confirms money changed hands beyond
    taking the seller's word, the same "can only attest to what we're
    told" posture already accepted for buyer-interest/evidence
    self-submission elsewhere in the app.
    """
    __tablename__ = "seller_financing_payments"

    id = Column(Integer, primary_key=True)
    agreement_id = Column(Integer, ForeignKey("seller_financing_agreements.id"), nullable=False)
    installment_number = Column(Integer, nullable=False)
    due_date = Column(Date, nullable=False)
    amount_due = Column(Numeric(15, 2), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    paid_at = Column(DateTime, nullable=True)
    paid_amount = Column(Numeric(15, 2), nullable=True)
    notes = Column(String(1000), nullable=True)
