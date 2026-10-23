from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, Boolean, Date, DateTime, JSON
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    role = Column(String(50), nullable=False, default="seller")
    # Real Postgres ARRAY in production; falls back to JSON under SQLite, which
    # has no native array type - this is what the in-memory pytest fixtures
    # across the whole suite use, and ARRAY alone made every one of them fail
    # to even create the users table (found 2026-10-01, while writing new
    # tests - a real regression introduced when `roles` was added, not caught
    # earlier because the full test suite hadn't been re-run since). JSON
    # stores/reads the same Python list correctly; it just can't do Postgres
    # array-specific operators, which nothing in this codebase uses on `roles`.
    roles = Column(ARRAY(String(50)).with_variant(JSON(), "sqlite"), nullable=False, default=lambda: ["seller"])
    kyc_status = Column(String(50), nullable=False, default="not_started")
    jurisdiction = Column(String(100), nullable=True)
    seller_affiliate_status = Column(String(50), nullable=True)
    hashed_password = Column(String(255), nullable=True)
    account_type = Column(String(50), nullable=False, default="participant")
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)
    tokens_valid_since = Column(DateTime, nullable=True)

    # Seller Financing default/accountability extension (2026-09-24).
    # FCRA research found that sharing a buyer's payment-default history
    # WITH OTHER SELLERS would make KEVO a "consumer reporting agency"
    # under 15 U.S.C. Sec 1681a(f) - real liability exposure. This is a
    # first-party-only consequence instead: it restricts the buyer's OWN
    # KEVO account, never a shared credit-style flag visible to anyone
    # else. Same shape as failed_login_attempts/locked_until above.
    seller_financing_blocked = Column(Boolean, nullable=False, default=False)
    seller_financing_blocked_at = Column(DateTime, nullable=True)
    seller_financing_blocked_reason = Column(String(1000), nullable=True)
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

    # M15 gap-closure item, 2026-10-22 - Discount-for-Speed. Nullable on
    # purpose: historical rows created before this column existed have no
    # honest value to backfill (no fabricated timestamps - the project's
    # standing "no fabricated specificity" principle), so they stay NULL
    # rather than getting an invented creation time. Every new transaction
    # going forward is created with this set explicitly (see
    # create_transaction / accept_auction_bid in app.py), the same pattern
    # LiquidityCommitment.created_at already uses. Paired with
    # SettlementRecord.funds_released_at (which already exists) to derive
    # a real "time to sale" for a completed transaction, without adding a
    # redundant completed_at column.
    created_at = Column(DateTime, nullable=True)

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
    rofr_response_window_days = Column(Integer, nullable=True)  # M25: real, sourced per-rule ROFR response window in days; null = not sourced yet, never invented
    
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
    log. Response deadlines are never invented: no jurisdiction sets a
    statutory ROFR response window (confirmed by research 2026-09-25) -
    it is always a company's own contractual term. TransferabilityRule.
    rofr_response_window_days holds the real, sourced window for a
    specific rule when one is known (entered directly, same as other
    curated facts); response_due_date is computed from it at request
    creation time and stays null when the window isn't known. Still
    deliberately avoids
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
    response_due_date = Column(Date, nullable=True)  # M25: computed from the matched rule's rofr_response_window_days at creation time, when known
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


class WithdrawalConfirmation(Base):
    """
    M32 continuation - step-up authentication for large withdrawals
    (spec Section 15). Mirrors PasswordResetToken's pattern exactly:
    only a SHA-256 hash of the confirmation token is stored, never the
    raw value - the raw token exists only in the emailed link. Single-use
    (used_at) and time-limited (expires_at). Stores the withdrawal's own
    parameters so the actual wallet_client.withdraw() call only fires
    once the token is confirmed - nothing moves before that.
    """
    __tablename__ = "withdrawal_confirmations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    amount = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    bank_account_id = Column(Integer, nullable=False)
    idempotency_key = Column(String(100), nullable=False)
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

    # M30B gap-closure wiring, 2026-10-22 - recurring open/close schedule
    # support. recurrence_interval_days is the company's own stated cadence
    # (e.g. 182 for "about every January and July") - KEVO stores it but
    # never auto-generates a new cycle on a timer (no background scheduler
    # exists in this stack, and silently spinning one up was never asked
    # for); POST /tender-offer-programs/{id}/next-cycle is an explicit
    # admin action that uses this interval to compute the next window's
    # dates, while still requiring the admin to restate price_per_share
    # every cycle - a commercial term is never carried over silently,
    # preserving the standing no-trade-term-setting invariant.
    is_recurring = Column(Boolean, nullable=False, default=False)
    recurrence_interval_days = Column(Integer, nullable=True)
    previous_program_id = Column(Integer, ForeignKey("tender_offer_programs.id"), nullable=True)


class TenderOfferElection(Base):
    """
    M30B (first slice) - a holder's election to participate in a
    TenderOfferProgram. Self-submit by the holder (mirroring
    LoanRequest/OptionFundingReferral), gated on the same verified-ownership
    check M13/M26B already enforce elsewhere. shares_accepted stays null
    until an admin finalizes the election, recording the company's own real
    allocation decision - KEVO never computes or suggests an allocation.

    M30B gap-closure wiring, 2026-10-22 - transfer_reviewed / rofr_cleared
    added per the first slice's own documented gap ("transfer review, ROFR,
    and settlement are not yet wired into the program flow"). Deliberately
    simple admin-attested flags here, not a reuse of RofrRequest's own
    transaction_id-keyed table: a company tender offer's counterparty is
    the company itself, and standard ROFR drafting almost always carves
    out repurchases by the issuer from ROFR entirely (ROFR exists to
    control who ELSE becomes a shareholder, which doesn't happen in a
    buyback) - so treating ROFR as a mandatory gate here would likely be
    legally backwards for the common case. rofr_cleared therefore stays
    optional/informational (an admin records it only when a specific
    company's agreement is unusual enough to require it), while
    transfer_reviewed is a hard gate before settlement can begin, since
    every real buyback genuinely needs the company's own transfer/cap-
    table approval step regardless of ROFR.
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
    transfer_reviewed = Column(Boolean, nullable=False, default=False)
    transfer_reviewed_at = Column(DateTime, nullable=True)
    rofr_cleared = Column(Boolean, nullable=True)
    rofr_notes = Column(String(1000), nullable=True)


class TenderOfferSettlement(Base):
    """
    M30B gap-closure wiring, 2026-10-22 - settlement tracking for an
    accepted TenderOfferElection, mirroring SettlementRecord's exact
    admin-attested, sequential-release shape (funds_received -> shares_
    confirmed_transferable -> funds_released). Keyed to election_id, not
    transaction_id, because a tender offer buyback has no Transaction row
    to attach to - KEVO deliberately has no company/issuer login actor
    (confirmed out of scope, M30B's own research doc), so there is no real
    buyer User to construct a Transaction with. Building one with a fake
    placeholder buyer would be exactly the kind of fabricated specificity
    this project avoids, so this is a parallel, purpose-fit table instead
    of a forced reuse. No Escrow.com integration (M26E's scope) - a
    company's own buyback payment is a treasury/payroll-style disbursement
    the company makes directly, not a peer-to-peer escrow flow, so this
    stays at M26's original base-layer admin-attestation shape.
    """
    __tablename__ = "tender_offer_settlements"

    id = Column(Integer, primary_key=True)
    election_id = Column(Integer, ForeignKey("tender_offer_elections.id"), nullable=False, unique=True)
    status = Column(String(50), nullable=False, default="pending")
    funds_received = Column(Boolean, nullable=False, default=False)
    funds_received_at = Column(DateTime, nullable=True)
    shares_confirmed_transferable = Column(Boolean, nullable=False, default=False)
    shares_confirmed_transferable_at = Column(DateTime, nullable=True)
    funds_released = Column(Boolean, nullable=False, default=False)
    funds_released_at = Column(DateTime, nullable=True)
    notes = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False)


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
    Seller Financing (2026-09-24).

    Legal grounding: a bilateral, privately-negotiated, non-pooled,
    non-resold promissory note between two specific parties fails every
    prong of the Reves "family resemblance" test, so it is "not a
    security" and doesn't drag in securities registration. TILA's
    business-purpose exemption (Reg Z Sec 1026.3(a)) applies because these
    are investment share purchases, not consumer credit. Usury ceilings
    vary by state/country with no single safe number, so - mirroring the
    standing agreed_price invariant - KEVO never computes or suggests
    annual_interest_rate_pct; it only stores what the two parties already
    agreed off-platform.

    restricts_transfer_until_paid is an explicit, OPT-IN term the parties
    choose at creation - KEVO enforces it (blocking a new listing for the
    same position while the agreement is unresolved, see create_listing)
    only when the parties actually agreed to it, never as a KEVO-invented
    default restriction.
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

    # Default/accountability extension.
    default_reason = Column(String(1000), nullable=True)
    defaulted_at = Column(DateTime, nullable=True)
    resolution_notes = Column(String(1000), nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    # Protection System extension.
    restricts_transfer_until_paid = Column(Boolean, nullable=False, default=False)
    quantity_transferred = Column(Integer, nullable=False, default=0)


class SellerFinancingPayment(Base):
    """
    One scheduled installment of a SellerFinancingAgreement. The private
    payment-history ledger the Protection System exposes is just a scoped
    read of this table (buyer/seller on the agreement, or an admin) - no
    separate ledger table needed.

    reminder_upcoming_sent_at / reminder_overdue_sent_at are idempotency
    markers for the automatic reminder scan (run_seller_financing_reminder_scan
    in app.py): each reminder fires at most once per payment, ever.
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

    reminder_upcoming_sent_at = Column(DateTime, nullable=True)
    reminder_overdue_sent_at = Column(DateTime, nullable=True)


class SellerFinancingReserve(Base):
    """
    Seller Financing Protection System - security deposit / reserve
    tracking (2026-09-24).

    KEVO never moves money (same reasoning as SettlementRecord).
    required_amount is an explicit term the parties themselves agreed to
    (seller or admin records it - never computed or suggested by KEVO).
    funded/released are admin-only attestations of a real-world fact,
    exactly like SettlementRecord.funds_received. released_to records who
    the parties themselves decided the reserve went to (buyer or seller) -
    KEVO records that outcome, it never decides it.
    """
    __tablename__ = "seller_financing_reserves"

    id = Column(Integer, primary_key=True)
    agreement_id = Column(Integer, ForeignKey("seller_financing_agreements.id"), nullable=False, unique=True)
    required_amount = Column(Numeric(15, 2), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    funded_at = Column(DateTime, nullable=True)
    funded_reference = Column(String(500), nullable=True)
    released_at = Column(DateTime, nullable=True)
    released_to = Column(String(20), nullable=True)
    released_reference = Column(String(500), nullable=True)
    notes = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False)


class SellerFinancingCollateral(Base):
    """
    Seller Financing Protection System - collateral / security-interest
    tracking, "where legally permitted" (2026-09-24).

    UCC Article 9 research found that actually PERFECTING a security
    interest in investment property requires either a filed UCC-1
    financing statement or a control agreement with the custodian/issuer -
    both real legal/administrative acts outside any software system. So
    this table is deliberately descriptive-only: it records what the
    parties privately agreed to pledge and its status, exactly as they
    tell KEVO - it does NOT create, file, or perfect a security interest,
    and every record starts legal_review_status="not_reviewed" so nothing
    is treated as a real, enforceable lien until an admin (or the
    parties' own counsel) has actually looked at it.
    """
    __tablename__ = "seller_financing_collateral"

    id = Column(Integer, primary_key=True)
    agreement_id = Column(Integer, ForeignKey("seller_financing_agreements.id"), nullable=False)
    description = Column(String(1000), nullable=False)
    collateral_type = Column(String(100), nullable=False)
    estimated_value = Column(Numeric(15, 2), nullable=True)
    status = Column(String(50), nullable=False, default="pledged")
    legal_review_status = Column(String(50), nullable=False, default="not_reviewed")
    legal_review_notes = Column(String(1000), nullable=True)
    source_reference = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=True)
    released_at = Column(DateTime, nullable=True)


class DueDiligenceChecklistItem(Base):
    """
    M25 gap-closure item, 2026-09-25 - a structured due-diligence checklist
    per transaction. Purely organizational (unlike ROFR or the sealed-bid
    auction mechanism also being built under M25) - no legal-exposure
    research needed. Any party to the transaction (buyer, seller) or an
    admin can add or complete an item, mirroring the deal room's own
    collaborative posture rather than the stricter self-submit/admin-verify
    pattern used for KYC/Evidence (those verify facts about identity or
    ownership; a checklist item is just organizational state to track,
    nothing to certify).
    """
    __tablename__ = "due_diligence_checklist_items"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    description = Column(String(500), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    evidence_id = Column(Integer, ForeignKey("evidence.id"), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    completed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    source_reference = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False)


class SecondaryAuctionBid(Base):
    """
    M25 gap-closure item, 2026-09-25 - the third and final M25 sub-piece:
    Structured Secondary Auctions. A sealed-bid mechanism for a listing -
    buyers submit their own freely-chosen price and quantity (KEVO never
    computes, suggests, or ranks a price), each buyer can see only their
    own bid (never another buyer's terms), and the listing's seller
    privately reviews every bid and manually accepts exactly one, which
    becomes a normal Transaction. KEVO performs no automated matching,
    ranking, or clearing-price computation - the seller's own manual
    accept decision is what keeps this a negotiation process rather than
    an automated exchange (see 2026-09-25 SEC Rule 3b-16 research: an
    "exchange" is defined by non-discretionary, automated order matching;
    preserving human/seller discretion at the point of acceptance is what
    keeps a bid-collection mechanism like this one outside that
    definition).
    """
    __tablename__ = "secondary_auction_bids"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    bidder_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    bid_price = Column(Numeric(15, 2), nullable=False)
    note = Column(String(500), nullable=True)
    status = Column(String(50), nullable=False, default="submitted")
    created_at = Column(DateTime, nullable=False)
    decided_at = Column(DateTime, nullable=True)
    decided_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resulting_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)


class ComplianceRuleChangeAlert(Base):
    """
    M27 gap-closure item, 2026-09-25 - compliance rule-change impact
    alerts, the second of M27's two remaining pieces (the Hash-Chained
    Compliance Decision Ledger, M27's first piece, already shipped
    2026-09-19). Built on top of that Ledger rather than a new rule-
    versioning system: when an admin edits a ComplianceRule (the
    already-existing PUT /compliance-rules/{rule_id}), KEVO finds every
    still-open transaction whose most recent Ledger entry cited this
    exact rule code, re-runs the real assess_compliance() verdict against
    the rule's new wording, and creates one alert only where the actual
    outcome changed (e.g. eligible -> needs review). Purely informational,
    like DealAlert (M31) - never blocks or changes the transaction itself,
    preserving the standing no-trade-term-setting/no-enforcement
    invariant already governing the Ledger it reads from.
    """
    __tablename__ = "compliance_rule_change_alerts"

    id = Column(Integer, primary_key=True)
    compliance_rule_id = Column(Integer, ForeignKey("compliance_rules.id"), nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    previous_decision_status = Column(String(50), nullable=False)
    new_decision_status = Column(String(50), nullable=False)
    previous_explanation = Column(String(1000), nullable=True)
    new_explanation = Column(String(1000), nullable=True)
    is_read = Column(Boolean, nullable=False, default=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False)


class Message(Base):
    """
    M31 gap-closure item, 2026-09-25 - the messaging layer for Compliant-
    Communication Gating, the second of M31's remaining pieces. KEVO had
    no messaging/communication feature of any kind before this (confirmed
    by M24's own earlier audit) - this is a deliberately minimal, per-
    transaction thread, not an open inbox or unsolicited-contact system.
    A message can only exist against a real Transaction, and only that
    transaction's buyer or seller can send or read one - the same scoping
    boundary Transaction itself already enforces under M19.

    Sending is gated (see _check_buyer_communication_eligible() in app.py):
    unlike every other KEVO feature, which is deliberately informational-
    only and never blocks anything, this is a named, deliberate exception -
    a message cannot be sent while the transaction's buyer fails a narrow,
    buyer-specific eligibility check (KYC verification + investor
    classification), regardless of which party is trying to send it.
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(String(2000), nullable=False)
    created_at = Column(DateTime, nullable=False)


class LiquidityCommitment(Base):
    """
    M31 gap-closure item, 2026-09-25 - Liquidity Commitment, the fourth of
    M31's remaining pieces (Interest-strength signaling extended into a
    richer, parameterized standing interest). Deliberately pure data
    capture, confirmed with Eze 2026-09-25: a richer BuyerInterest-like
    record (price range, quantity range, expiration, free-text
    conditions) that nothing new matches or acts on automatically. Scoped
    this way on purpose - a version that auto-triggered matching on these
    richer conditions would edge closer to resting-limit-order territory,
    the same class of concern that got M16B's original full scope
    narrowed after dedicated Rule 3b-16 research. This stays as safe as
    plain BuyerInterest: a buyer's own non-binding record, visible only
    through the same kind of scoped read/withdraw pattern BuyerInterest
    already uses, not fed into any new coordination logic.

    Explicitly, per the milestone's own name: NOT a binding offer, NOT an
    order, NOT matched automatically by anything built here.
    """
    __tablename__ = "liquidity_commitments"

    id = Column(Integer, primary_key=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company = Column(String(255), nullable=False)
    asset_type = Column(String(100), nullable=False)
    min_quantity = Column(Integer, nullable=True)
    max_quantity = Column(Integer, nullable=True)
    min_price = Column(Numeric(15, 2), nullable=True)
    max_price = Column(Numeric(15, 2), nullable=True)
    expiration_date = Column(Date, nullable=True)
    conditions = Column(String(1000), nullable=True)
    status = Column(String(50), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False)


class SpeedDiscountOffer(Base):
    """
    M15 gap-closure item, 2026-10-22 - Discount-for-Speed.

    A seller-stated (never KEVO-computed, never KEVO-suggested) offer to
    accept a lower price in exchange for a faster completed sale. This
    respects the same M10/M11 invariant create_transaction already
    enforces in app.py: KEVO's own logic must never set, suggest, or
    default agreed_price or any other trade term. This table only ever
    stores numbers the seller themselves typed in - exactly like
    BuyerInterest.maximum_price or LiquidityCommitment's price range
    store buyer-stated numbers, never KEVO-derived ones. Nothing here
    matches, ranks, recommends, or auto-applies a discount to any
    transaction's agreed_price; a buyer who sees this offer and a seller
    still negotiate and state their own agreed_price at
    POST /transactions, exactly as before this feature existed.

    A seller states at least one of max_discount_percent (e.g. "up to 5%
    off my asking price") or floor_price (an explicit minimum dollar
    amount they'd accept) - both optional so the seller can phrase it
    either way, validated in app.py so at least one is actually set.
    speed_window_days is the seller's own stated "if a sale completes
    within this many days" window - also just stored, never enforced or
    checked by any automatic process.
    """
    __tablename__ = "speed_discount_offers"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    max_discount_percent = Column(Numeric(5, 2), nullable=True)
    floor_price = Column(Numeric(15, 2), nullable=True)
    speed_window_days = Column(Integer, nullable=False)
    notes = Column(String(1000), nullable=True)
    status = Column(String(50), nullable=False, default="active")
    created_at = Column(DateTime, nullable=False)


class LiquidityEventSignal(Base):
    """
    M31 - Liquidity Event Radar (admin-entered MVP), 2026-10-22. Was
    explicitly parked since 2026-09-05 pending its own dedicated research
    pass on information sourcing, confidentiality, and market-abuse/
    insider-information risk (claude/kevo-m31-liquidity-event-radar-
    research.md) - this is that research's resulting design, confirmed
    with Eze via AskUserQuestion 2026-10-22.

    Fixed, non-negotiable scope carried over from the master handoff:
    signals are drawn strictly from events that are already publicly
    disclosed (a closed/announced funding round, an S-1/IPO filing, a
    publicly announced tender offer or M&A transaction) - never a
    predictive or inferred signal about a not-yet-public event. That
    boundary is enforced by event_type's app-level allow-list
    (LIQUIDITY_EVENT_SIGNAL_TYPES in app.py), which deliberately has no
    "rumored"/"expected" option.

    Admin-entered, not a live scraper: no real EDGAR-redistribution ToS
    clearance or third-party data-source credentials exist yet (the
    research flagged both as open items), so an admin records a real
    event with a required source_url and the source's own
    source_disclosed_at timestamp - the same admin-attested pattern
    already used for RofrRequest/SettlementRecord/TenderOfferProgram.

    draft -> published -> retracted is deliberately a real workflow, not
    decoration: SEC v. Texas Gulf Sulphur holds that "technically public"
    isn't the same as "the market has had a reasonable opportunity to
    react," and no source found gives a fixed safe-harbor delay. Rather
    than invent one (the same restraint M25 showed refusing to invent a
    ROFR deadline), Eze confirmed 2026-10-22: no fixed timer - an admin
    reviews each candidate event and makes their own judgment call about
    when it's genuinely digested before publishing it. A signal is only
    ever visible to a non-admin once published_at is set. retracted
    handles the real risk (also flagged in the research) that a filing
    is later amended or turns out inaccurate - it stays in the table for
    audit purposes rather than being deleted.

    Deliberately impersonal: GET /liquidity-event-signals returns the
    exact same published signals to every viewer, never filtered or
    tailored to a specific user's holdings or stated interest. This is
    the concrete design lever the research identified as the strongest
    fit for the Investment Advisers Act's publisher's exclusion (Lowe v.
    SEC) - general, regular, non-personalized circulation of genuinely
    public information, not individualized investment advice.
    """
    __tablename__ = "liquidity_event_signals"

    id = Column(Integer, primary_key=True)
    company = Column(String(255), nullable=False)
    asset_type = Column(String(100), nullable=False)
    event_type = Column(String(50), nullable=False)
    description = Column(String(1000), nullable=False)
    source_url = Column(String(1000), nullable=False)
    source_disclosed_at = Column(DateTime, nullable=False)
    status = Column(String(50), nullable=False, default="draft")
    published_at = Column(DateTime, nullable=True)
    retracted_at = Column(DateTime, nullable=True)
    retraction_notes = Column(String(1000), nullable=True)
    created_by_admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False)


class SpvPool(Base):
    """
    M17B gap-closure item, 2026-10-22 - SPV Fractional Ownership Pools,
    back-office-administrator-only scope.

    M17B's own prior research (claude/kevo-m17b-spv-critical-assessment.md,
    2026-09-12) found every real pooled-SPV platform runs one of three
    ways: (1) inside a registered broker-dealer (EquityZen Securities LLC,
    Forge Securities), (2) through a registered investment adviser under
    narrow no-transaction-fee conditions (AngelList, resting on a 2013 SEC
    no-action letter), or (3) as a pure back-office administrator with no
    sponsor role at all (Sydecar, Carta, Allocations) - the customer bears
    full regulatory responsibility as their own sponsor. KEVO has no
    broker-dealer or investment-adviser registration, so (1) and (2) are
    not available; (3) is. Confirmed with Eze via AskUserQuestion,
    2026-10-22: build (3), not (1)/(2), and not a full re-defer.

    KEVO is never this pool's legal sponsor, general partner, or manager.
    sponsor_name names whoever actually is - the organizer's own entity,
    or a named third-party SPV-formation service - and
    legal_disclaimer_acknowledged must be explicitly set true by the
    organizer before a pool can be created at all. KEVO performs no
    investment decision-making, charges no fee of any kind tied to this
    pool (the AngelList no-action letter's central condition, and the
    simplest way to stay outside it rather than attempt to satisfy it),
    and does not verify that the named sponsor has actually formed or is
    capable of forming the vehicle - that remains the organizer's and
    sponsor's own legal responsibility, exactly like every other
    admin/party-attested record in KEVO (RofrRequest, SettlementRecord,
    SellerFinancingCollateral's "not_reviewed" default).

    minimum_check_size and target_total_amount are organizer-stated,
    never KEVO-computed - the same "KEVO never sets or suggests a
    trade/deal term" invariant as agreed_price (M10/M11) and the ROFR/
    discount offers above.
    """
    __tablename__ = "spv_pools"

    id = Column(Integer, primary_key=True)
    organizer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company = Column(String(255), nullable=False)
    asset_type = Column(String(100), nullable=False)
    target_listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    sponsor_name = Column(String(255), nullable=False)
    sponsor_is_platform_user = Column(Boolean, nullable=False, default=False)
    sponsor_contact_reference = Column(String(500), nullable=True)
    minimum_check_size = Column(Numeric(15, 2), nullable=False)
    target_total_amount = Column(Numeric(15, 2), nullable=True)
    legal_disclaimer_acknowledged = Column(Boolean, nullable=False, default=False)
    status = Column(String(50), nullable=False, default="forming")
    notes = Column(String(1000), nullable=True)
    created_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime, nullable=True)


class SpvPoolCommitment(Base):
    """
    A participant's stated intent to put a specific amount into a given
    SpvPool. Pure data capture, same discipline as LiquidityCommitment
    and BuyerInterest - non-binding, never auto-matched, never fed into
    any coordination or allocation logic. The organizer and the named
    sponsor are the ones who turn these into an actual legal commitment
    outside KEVO; KEVO just keeps the roster.
    """
    __tablename__ = "spv_pool_commitments"

    id = Column(Integer, primary_key=True)
    pool_id = Column(Integer, ForeignKey("spv_pools.id"), nullable=False)
    participant_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    committed_amount = Column(Numeric(15, 2), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False)
    withdrawn_at = Column(DateTime, nullable=True)


class ForwardSaleContract(Base):
    """
    M25B gap-closure item, 2026-10-23 - Forward Sale / Pre-Liquidity-Event
    Contracts, structured-safe scope.

    M25B's own prior research (claude/kevo-m25b-forward-sale-legal-
    research.md, 2026-09-18) found three independent obstacles to the
    originally-scoped "lock in a price today, settle later" contract, not
    just a design gap:

      1. The SEC's 2022 C&DI 101.01 risks reclassifying a forward on
         still-transfer-restricted shares as a security-based swap
         requiring Dodd-Frank registration, avoidable (without an
         issuer waiver KEVO has no way to obtain) by limiting buyers to
         accredited-at-$10M+ "Eligible Contract Participants."
      2. A single fixed price locked in at signing is close to the
         textbook trigger for IRC Section 1259 constructive-sale
         treatment - immediate taxable gain for the seller before any
         real proceeds - avoidable via a variable-prepaid-forward
         structure (a floor/cap price corridor, never one number).
      3. A real and growing number of companies' own governing documents
         prohibit this kind of "deemed transfer" arrangement outright
         (Airbnb's bylaws cited as one real example), and KEVO has no
         per-company governing-document data to confirm whether any
         given issuer permits it.

    Confirmed with Eze via AskUserQuestion, 2026-10-23: build with fixes
    1 and 2 applied (buyer must be an admin-verified Eligible Contract
    Participant - reusing InvestorEligibility's existing self-submit/
    admin-verify flow with classification="eligible_contract_participant",
    rather than inventing a new eligibility system; floor_price/cap_price
    instead of one fixed price). Obstacle 3 has no code fix - it can only
    be flagged, never verified by KEVO - so governing_document_review_
    status starts "not_reviewed" and stays the organizer's/company's own
    legal responsibility, the same descriptive-only discipline already
    used for SellerFinancingCollateral's "not_reviewed" default.

    floor_price/cap_price/prepaid_amount are party-stated, never
    KEVO-computed - the same agreed_price invariant (M10/M11) carried
    through every contract term in KEVO.
    """
    __tablename__ = "forward_sale_contracts"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company = Column(String(255), nullable=False)
    asset_type = Column(String(100), nullable=False)
    floor_price = Column(Numeric(15, 2), nullable=False)
    cap_price = Column(Numeric(15, 2), nullable=False)
    prepaid_amount = Column(Numeric(15, 2), nullable=False)
    trigger_event = Column(String(100), nullable=False)
    seller_attests_no_governing_document_prohibition = Column(Boolean, nullable=False, default=False)
    governing_document_review_status = Column(String(50), nullable=False, default="not_reviewed")
    governing_document_review_notes = Column(String(1000), nullable=True)
    status = Column(String(50), nullable=False, default="proposed")
    final_price = Column(Numeric(15, 2), nullable=True)
    final_quantity = Column(Numeric(15, 4), nullable=True)
    settlement_notes = Column(String(1000), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    settled_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
