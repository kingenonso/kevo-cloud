import bisect
import os
import statistics
from collections import defaultdict
from fastapi import FastAPI, Depends, HTTPException, Request, File, UploadFile
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from pydantic import BaseModel, Field
from datetime import date, timedelta, datetime
from sqlalchemy.orm import Session
import uuid
import bcrypt
import jwt
import hashlib
import httpx
import json
import secrets
import calendar

from database import SessionLocal
from models import Listing as ListingModel
from models import User as UserModel
from models import OwnershipRecord, Transaction, BuyerInterest, InvestorEligibility, ComplianceRule, TransferabilityRule, TransferabilityFact, TransferabilityAssessment, PositionPassport, Evidence, PositionEvent, Offering, OfferingFact, OfferingExemptionRule, OfferingExemptionAssessment, LiquidityPathStep, KYCFact, RofrRequest, SettlementRecord, LoanRequest, OptionFundingReferral, ComplianceDecisionLedger, TenderOfferProgram, TenderOfferElection, DealAlert, PasswordResetToken, WithdrawalConfirmation, AuditLogEntry, SellerFinancingAgreement, SellerFinancingPayment, SellerFinancingReserve, SellerFinancingCollateral
from models import Transaction
from models import DueDiligenceChecklistItem
from models import SecondaryAuctionBid
from models import ComplianceRuleChangeAlert
from models import Message
from models import LiquidityCommitment
import escrow_client
import wallet_client
import email_client
from apscheduler.schedulers.background import BackgroundScheduler
app = FastAPI(title="KEVO API")

# M28 (first slice) - serves the web app's login + dashboard shell as static
# files, same-origin, so no CORS setup is needed. html=True lets
# /app/ resolve to static/index.html automatically.
app.mount("/app", StaticFiles(directory="static", html=True), name="frontend")

# M27 (first slice) - Hash-Chained Compliance Decision Ledger helpers.
# GENESIS_HASH is the fixed starting point of the one global chain -
# standard convention (all zeros) for a hash chain's first link.
GENESIS_HASH = "0" * 64


def _compute_ledger_entry_hash(previous_hash, transaction_id, buyer_id, listing_id,
                                decision_status, explanation, applicable_rule_codes_json,
                                triggered_by, decided_at):
    payload = "|".join([
        previous_hash,
        str(transaction_id),
        str(buyer_id),
        str(listing_id),
        decision_status,
        explanation or "",
        applicable_rule_codes_json,
        triggered_by,
        decided_at.isoformat()
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def log_compliance_decision(transaction, buyer, listing, triggered_by, db):
    """
    M27: snapshot a real assess_compliance() verdict for a real transaction
    at a real lifecycle moment, and append it to the global hash chain.
    Purely informational - never raises, never blocks the caller's action.
    """
    compliance_result = assess_compliance(buyer, listing, db)

    last_entry = db.query(ComplianceDecisionLedger).order_by(
        ComplianceDecisionLedger.id.desc()
    ).first()
    previous_hash = last_entry.entry_hash if last_entry else GENESIS_HASH

    decided_at = datetime.utcnow()
    applicable_rule_codes_json = json.dumps(compliance_result.get("applicable_rule_codes") or [])

    entry_hash = _compute_ledger_entry_hash(
        previous_hash, transaction.id, buyer.id, listing.id,
        compliance_result["status"], compliance_result.get("explanation"),
        applicable_rule_codes_json, triggered_by, decided_at
    )

    entry = ComplianceDecisionLedger(
        transaction_id=transaction.id,
        buyer_id=buyer.id,
        listing_id=listing.id,
        decision_status=compliance_result["status"],
        explanation=compliance_result.get("explanation"),
        applicable_rule_codes=applicable_rule_codes_json,
        triggered_by=triggered_by,
        decided_at=decided_at,
        previous_hash=previous_hash,
        entry_hash=entry_hash
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    phone_number: str
    date_of_birth: date
    role: str = "buyer"
    seller_affiliate_status: str | None = None
    jurisdiction: str
    terms_accepted: bool


class LoginRequest(BaseModel):
    email: str
    password: str


class SetPasswordRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


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

class KYCFactCreate(BaseModel):
    user_id: int
    jurisdiction: str | None = None
    fact_type: str
    fact_value: str
    as_of_date: date | None = None
    evidence_id: int | None = None
    source_reference: str | None = None

class ComplianceRuleCreate(BaseModel):
    buyer_jurisdiction: str | None = None
    issuer_jurisdiction: str | None = None
    asset_type: str | None = None
    investor_classification: str | None = None
    rule_code: str
    description: str
    fact_type: str
    requirement: str
    decision_if_unmet: str
    requires_human_review: bool = True
    active: bool = True
    source_reference: str | None = None

class ComplianceRuleUpdate(BaseModel):
    buyer_jurisdiction: str | None = None
    issuer_jurisdiction: str | None = None
    asset_type: str | None = None
    investor_classification: str | None = None
    rule_code: str | None = None
    description: str | None = None
    fact_type: str | None = None
    fact_validity_days: int | None = None
    requirement: str | None = None
    decision_if_unmet: str | None = None
    requires_human_review: bool | None = None
    active: bool | None = None
    source_reference: str | None = None

# ---------------------------------------------------------------------------
# M13 - Compliance Engine (single-engine remediation, 2026-09-09)
#
# Replaces the former check_compliance() (hardcoded checklist that could
# never actually return "eligible" - every branch terminated in "blocked"
# or "review") and evaluate_compliance_rules() (a real data-driven rule
# matcher against ComplianceRule that was never combined with a verdict).
# Mirrors assess_transferability()'s structure and precedence on purpose:
# blocked > needs_evidence > review > eligible_pending_review. See the
# M13 architecture review (2026-09-09) for the full design rationale.
#
# Per that review: no ComplianceRule content is seeded here. Real rules
# require a dedicated jurisdiction-by-jurisdiction regulatory research
# pass with cited sources first, the same discipline
# seed_transferability_rules.py already applied for M14.
# ---------------------------------------------------------------------------

def _resolve_compliance_fact(fact_type, buyer, listing, db):
    """
    Returns (normalized_value, evidenced, as_of_date). Extends M13's
    original two-value contract with a third: the date the fact was
    established, when the underlying record has one. as_of_date is
    None for fact types with no natural "as of" date - only
    eligibility_verified currently returns a real one, sourced from
    InvestorEligibility.effective_date, so a rule can check whether a
    classification has gone stale (fact_validity_days on ComplianceRule).
    Deliberately reuses real, already-collected data rather than a
    separate fact table: two of these fact_types
    (issuer_reporting_status, issuer_current_information_available)
    read the same Listing columns M14 already reads, and
    seller_affiliate_status reads the same User column - independently,
    not coupled to M14's engine. A recorded-but-unverified
    OwnershipRecord/InvestorEligibility row is treated the same as a
    missing one.
    """
    if fact_type == "ownership_verified":
        ownership = db.query(OwnershipRecord).filter(
            OwnershipRecord.listing_id == listing.id,
            OwnershipRecord.seller_id == listing.seller_id,
            OwnershipRecord.verification_status == "verified"
        ).first()
        if ownership is None:
            return None, False, None
        return "verified", True, None

    if fact_type == "acquisition_date_present":
        ownership = db.query(OwnershipRecord).filter(
            OwnershipRecord.listing_id == listing.id,
            OwnershipRecord.seller_id == listing.seller_id,
            OwnershipRecord.verification_status == "verified"
        ).first()
        if ownership is None or ownership.acquisition_date is None:
            return None, False, None
        return "present", True, None

    if fact_type == "eligibility_verified":
        eligibility = db.query(InvestorEligibility).filter(
            InvestorEligibility.buyer_id == buyer.id,
            InvestorEligibility.status == "verified"
        ).first()
        if eligibility is None:
            return None, False, None
        return "verified", True, eligibility.effective_date

    if fact_type == "issuer_reporting_status":
        if listing.issuer_reporting_status is None:
            return None, False, None
        return listing.issuer_reporting_status.strip().lower(), True, None

    if fact_type == "issuer_current_information_available":
        if listing.issuer_current_information_available is None:
            return None, False, None
        value = "available" if listing.issuer_current_information_available else "not_available"
        return value, True, None

    if fact_type == "seller_affiliate_status":
        seller = db.query(UserModel).filter(UserModel.id == listing.seller_id).first()
        if seller is None or seller.seller_affiliate_status is None:
            return None, False, None
        return seller.seller_affiliate_status.strip().lower(), True, None

    return None, False, None


def find_applicable_rules(buyer, listing, db):
    """
    Scopes ComplianceRule rows by buyer_jurisdiction / issuer_jurisdiction
    / asset_type only (None on a rule = wildcard, matches anything).
    investor_classification is deliberately NOT used as a scoping filter
    here - a rule that names a required classification is always
    returned once the other three dimensions match, so assess_compliance()
    can see it and explicitly evaluate whether the buyer's actual
    classification satisfies it (met / wrong classification / not yet
    classified), instead of the rule silently disappearing for a buyer
    who doesn't already carry that exact classification.
    """
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

        applicable_rules.append(rule)

    return applicable_rules


def _check_investor_classification(rule, buyer, db):
    """
    Evaluates whether the buyer's recorded investor classification
    satisfies a rule's investor_classification requirement. Returns one
    of:
      "not_applicable"   - rule.investor_classification is blank, this
                            rule doesn't require any particular
                            classification.
      "missing_evidence" - buyer has no verified InvestorEligibility row
                            yet, or their certification has gone stale
                            (see fact_validity_days below).
      "met"               - buyer's verified classification matches what
                            the rule requires.
      "blocked" / "review" - buyer's verified classification does NOT
                            match what the rule requires; which of the
                            two reuses the rule's own decision_if_unmet,
                            same as every other unmet-fact outcome in
                            this engine.

    Also applies fact_validity_days here: if the rule sets it, a verified
    classification whose InvestorEligibility.effective_date is further
    back than fact_validity_days is treated as stale - same outcome as
    never being verified at all, not a hard block. This is what makes a
    rule like Australia's 6-month sophisticated-investor certificate
    (AU-SOPH-001) actually expire instead of being verified-forever.
    """
    if rule.investor_classification is None:
        return "not_applicable"

    eligibility = db.query(InvestorEligibility).filter(
        InvestorEligibility.buyer_id == buyer.id,
        InvestorEligibility.status == "verified"
    ).first()

    if eligibility is None:
        return "missing_evidence"

    if rule.fact_validity_days is not None:
        if eligibility.effective_date is None:
            return "missing_evidence"
        expires_on = eligibility.effective_date + timedelta(days=rule.fact_validity_days)
        if date.today() > expires_on:
            return "missing_evidence"

    if eligibility.classification.strip().lower() == rule.investor_classification.strip().lower():
        return "met"

    return "blocked" if rule.decision_if_unmet == "blocked" else "review"


def _check_buyer_communication_eligible(buyer, listing, db):
    """
    M31 gap-closure item, 2026-09-25 - the gate behind Compliant-
    Communication Gating. Deliberately narrower than assess_compliance():
    only considers facts about the BUYER that bear on whether it is
    legal to communicate with them about this specific offering - KYC
    verification and investor classification. Ignores ownership
    verification, transferability, and every other listing/seller-side
    fact assess_compliance() also checks, since those have nothing to do
    with whether contacting this buyer is permitted (confirmed with Eze
    2026-09-25 rather than assumed, since reusing the full status would
    have blocked a seller from messaging about their OWN unresolved
    ownership record).

    This is the one deliberate exception to KEVO's standing "compliance
    never gates anything" posture (see M27's Ledger, M17's Deal Health
    Score/Risk Radar, M27B's Liquidity Friction Indicator - all
    explicitly informational-only). Messaging is the one place KEVO
    actually blocks an action on a live compliance fact, because the
    underlying concern here is solicitation, not deal administration.

    Returns (eligible: bool, reason: str | None).
    """
    if buyer.kyc_status != "verified":
        return False, "buyer KYC is not verified"

    applicable_rules = find_applicable_rules(buyer, listing, db)

    for rule in applicable_rules:
        outcome = _check_investor_classification(rule, buyer, db)
        if outcome in ("missing_evidence", "blocked", "review"):
            return False, (
                f"investor classification requirement not met for rule "
                f"{rule.rule_code} (requires: {rule.investor_classification})"
            )

    return True, None


def assess_compliance(buyer, listing, db):
    """
    Single M13 compliance verdict. Status meanings:

      blocked                 - a hard platform gate failed (KYC
                                 unverified, listing not marked
                                 transferable), a seeded rule's
                                 requirement is unmet with
                                 decision_if_unmet="blocked", or the
                                 buyer's verified investor classification
                                 does not match what a rule requires
                                 (decision_if_unmet="blocked").
      needs_evidence           - a required fact (jurisdiction, a rule's
                                 fact_type, or a rule's required investor
                                 classification) is missing, not yet
                                 verified, or has gone stale past its
                                 fact_validity_days window.
      review                   - no active rules are seeded for this
                                 buyer/issuer jurisdiction + asset_type
                                 combination, a seeded rule's requirement
                                 is unmet with decision_if_unmet="review",
                                 or the buyer's classification mismatches
                                 a rule with decision_if_unmet="review".
      eligible_pending_review  - every hard gate and every applicable
                                 seeded rule (including classification
                                 requirements) is currently satisfied.
                                 Not a legal opinion - final legal/
                                 compliance sign-off is still required.
    """
    if buyer.kyc_status != "verified":
        return {
            "status": "blocked",
            "explanation": "Buyer KYC is not verified.",
            "applicable_rule_codes": []
        }

    if not listing.is_transferable:
        return {
            "status": "blocked",
            "explanation": "Listing is not confirmed transferable.",
            "applicable_rule_codes": []
        }

    if buyer.jurisdiction is None:
        return {
            "status": "needs_evidence",
            "explanation": (
                "Buyer jurisdiction is not on file - no jurisdiction-"
                "specific compliance rules can be evaluated until it is "
                "recorded."
            ),
            "applicable_rule_codes": []
        }

    if listing.issuer_jurisdiction is None:
        return {
            "status": "needs_evidence",
            "explanation": (
                "Issuer jurisdiction is not on file - no jurisdiction-"
                "specific compliance rules can be evaluated until it is "
                "recorded."
            ),
            "applicable_rule_codes": []
        }

    applicable_rules = find_applicable_rules(buyer, listing, db)

    if not applicable_rules:
        return {
            "status": "review",
            "explanation": (
                "No compliance rules are yet on file for this buyer "
                "jurisdiction / issuer jurisdiction / asset type "
                "combination - this combination hasn't been legally "
                "researched/seeded into KEVO's rule set yet. Requires "
                "direct legal review before any match can be treated as "
                "eligible."
            ),
            "applicable_rule_codes": []
        }

    severity = {"blocked": 3, "missing_evidence": 2, "review": 1, "met": 0, "not_applicable": 0}

    missing_evidence_rules = []
    blocked_rules = []
    review_rules = []
    met_rules = []

    for rule in applicable_rules:
        value, evidenced, as_of_date = _resolve_compliance_fact(rule.fact_type, buyer, listing, db)

        if rule.fact_validity_days is not None and evidenced:
            if as_of_date is None:
                evidenced = False
            else:
                expires_on = as_of_date + timedelta(days=rule.fact_validity_days)
                if date.today() > expires_on:
                    evidenced = False

        if not evidenced:
            primary_outcome = "missing_evidence"
            primary_reason = f"{rule.fact_type} not yet evidenced or expired"
        elif value == rule.requirement.strip().lower():
            primary_outcome = "met"
            primary_reason = None
        elif rule.decision_if_unmet == "blocked":
            primary_outcome = "blocked"
            primary_reason = f"{rule.requirement} not met"
        else:
            primary_outcome = "review"
            primary_reason = f"{rule.requirement} not met, requires legal judgment"

        classification_outcome = _check_investor_classification(rule, buyer, db)

        if classification_outcome == "not_applicable":
            classification_reason = None
        elif classification_outcome == "met":
            classification_reason = None
        elif classification_outcome == "missing_evidence":
            classification_reason = (
                f"investor classification not yet verified or expired "
                f"(requires: {rule.investor_classification})"
            )
        else:
            classification_reason = (
                f"investor classification does not match required "
                f"'{rule.investor_classification}'"
            )

        outcomes = [(primary_outcome, primary_reason)]
        if classification_outcome != "not_applicable":
            outcomes.append((classification_outcome, classification_reason))

        worst_outcome = max(outcomes, key=lambda pair: severity[pair[0]])[0]
        rule_reasons = [r for (_, r) in outcomes if r]

        if worst_outcome == "blocked":
            blocked_rules.append((rule, rule_reasons))
        elif worst_outcome == "missing_evidence":
            missing_evidence_rules.append((rule, rule_reasons))
        elif worst_outcome == "review":
            review_rules.append((rule, rule_reasons))
        else:
            met_rules.append((rule, rule_reasons))

    rule_codes = [r.rule_code for r in applicable_rules]

    if blocked_rules:
        reasons = "; ".join(
            f"{rule.rule_code}: {'; '.join(rule_reasons)} "
            f"(source: {rule.source_reference or 'n/a'})"
            for rule, rule_reasons in blocked_rules
        )
        return {
            "status": "blocked",
            "explanation": f"Blocked by: {reasons}",
            "applicable_rule_codes": rule_codes
        }

    if missing_evidence_rules:
        missing = ", ".join(
            f"{'; '.join(rule_reasons)} ({rule.rule_code})"
            for rule, rule_reasons in missing_evidence_rules
        )
        return {
            "status": "needs_evidence",
            "explanation": (
                f"Cannot complete assessment - the following facts are "
                f"missing, not yet verified, or have expired: {missing}."
            ),
            "applicable_rule_codes": rule_codes
        }

    if review_rules:
        reasons = "; ".join(
            f"{rule.rule_code}: {'; '.join(rule_reasons)} "
            f"(source: {rule.source_reference or 'n/a'})"
            for rule, rule_reasons in review_rules
        )
        return {
            "status": "review",
            "explanation": f"Requires human/legal review: {reasons}",
            "applicable_rule_codes": rule_codes
        }

    citations = "; ".join(
        f"{rule.rule_code} (source: {rule.source_reference or 'n/a'})" for rule, _ in met_rules
    )
    return {
        "status": "eligible_pending_review",
        "explanation": (
            f"All {len(met_rules)} applicable compliance requirement(s) "
            f"are currently met: {citations}. This is KEVO's own rule "
            "evaluation, not a legal opinion - final legal/compliance "
            "sign-off is still required before this match can proceed."
        ),
        "applicable_rule_codes": rule_codes
    }


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

        if rule.expected_fact_value is not None and fact.fact_value != rule.expected_fact_value:
            statuses.append(rule.decision_if_unmet)
            reasons.append(
                "Fact '" + rule.fact_type + "' for rule " + rule.rule_code + " has value '" + fact.fact_value +
                "' but requires '" + rule.expected_fact_value + "'"
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


# ---------------------------------------------------------------------------
# M18 (first slice, 2026-09-12) - Authentication
# Passwords are hashed with bcrypt (one-way, never stored or logged in plain
# text). Sessions are stateless JSON Web Tokens (JWT), signed with a real
# secret key generated for this project (SECRET_KEY in .env, never
# committed). A token proves who is calling without KEVO needing to store a
# session anywhere. This first slice protects the two endpoints the M10/M11
# exposure investigation found open to any caller (GET /listings/{listing_id},
# GET /users) - the rest of the API is deliberately left open for now and
# rolled out in follow-up passes, per Eze's explicit scope choice, so this
# stays a small, verifiable slice rather than one large, high-risk change
# across every existing endpoint and test file.
# ---------------------------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


def hash_password(plain_password):
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password, hashed_password):
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id):
    now = datetime.utcnow()
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "iat": now, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def log_audit_event(db, actor_user_id, action, target_type=None, target_id=None, detail=None):
    """
    Full-gap-closure pass (Batch B, group 3 item 8), 2026-09-24 - adds a
    row to the pending session without committing it itself, so callers
    fold the audit entry into whatever commit their own endpoint already
    makes, rather than a second round-trip.
    """
    entry = AuditLogEntry(
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        created_at=datetime.utcnow()
    )
    db.add(entry)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"}
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        issued_at = payload.get("iat")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(UserModel).filter(UserModel.id == int(user_id)).first()
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="This account has been deactivated",
            headers={"WWW-Authenticate": "Bearer"}
        )

    if user.tokens_valid_since is not None:
        if issued_at is None or datetime.utcfromtimestamp(issued_at) < user.tokens_valid_since:
            raise HTTPException(
                status_code=401,
                detail="Token has been revoked. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"}
            )

    return user


@app.post("/login")
@limiter.limit("5/minute")
def login(request: Request, credentials: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(
        UserModel.email == credentials.email
    ).first()

    if user is None or user.hashed_password is None:
        log_audit_event(db, None, "login_failed_unknown_email", detail=credentials.email)
        db.commit()
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password"
        )

    if not user.is_active:
        log_audit_event(db, user.id, "login_blocked_deactivated")
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="This account has been deactivated"
        )

    if user.locked_until is not None and user.locked_until > datetime.utcnow():
        log_audit_event(db, user.id, "login_blocked_lockout")
        db.commit()
        raise HTTPException(
            status_code=423,
            detail="Account temporarily locked due to repeated failed login attempts. Try again later."
        )

    if not verify_password(credentials.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            user.failed_login_attempts = 0
        log_audit_event(db, user.id, "login_failed_wrong_password")
        db.commit()
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password"
        )

    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    access_token = create_access_token(user.id)

    log_audit_event(db, user.id, "login_success")
    db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


@app.delete("/users/{user_id}")
def deactivate_user(
    user_id: int,
    reason: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Batch B item 5/13 - "make sure the user-account-delete endpoint
    doesn't actually delete the account - set it inactive with a reason
    instead." There was no account-delete endpoint of any kind before
    this - this is the first one, and it never issues a real DELETE
    against the row. A deactivated account can no longer log in
    (checked in /login) and any token it's already holding stops
    working immediately (checked in get_current_user, and its sessions
    are revoked the same way /users/me/revoke-tokens does it).
    """
    target = db.query(UserModel).filter(UserModel.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    is_admin = current_user.account_type == "admin"
    if not is_admin and current_user.id != target.id:
        raise HTTPException(
            status_code=403,
            detail="You can only deactivate your own account"
        )

    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required to deactivate an account")

    if not target.is_active:
        raise HTTPException(status_code=400, detail="This account is already deactivated")

    target.is_active = False
    target.deactivated_at = datetime.utcnow()
    target.deactivation_reason = reason
    target.tokens_valid_since = datetime.utcnow().replace(microsecond=0)

    log_audit_event(
        db, current_user.id, "account_deactivated",
        target_type="user", target_id=target.id, detail=reason
    )
    db.commit()
    db.refresh(target)

    return {
        "message": "Account deactivated",
        "user": {
            "id": target.id,
            "is_active": target.is_active,
            "deactivated_at": target.deactivated_at.isoformat(),
            "deactivation_reason": target.deactivation_reason
        }
    }


@app.post("/users/me/revoke-tokens")
def revoke_my_tokens(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Full-gap-closure pass (Batch B, group 3 item 8), 2026-09-24 - real
    "log out everywhere": any token issued before this moment is
    rejected on its next use, including the token used to make this
    very call (this request was already authenticated before the
    revocation point was set).
    """
    current_user.tokens_valid_since = datetime.utcnow().replace(microsecond=0)
    log_audit_event(db, current_user.id, "tokens_revoked", target_type="user", target_id=current_user.id)
    db.commit()

    return {"message": "All tokens issued before this moment have been revoked. Please log in again."}


@app.get("/audit-log")
def get_audit_log(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Full-gap-closure pass (Batch B, group 3 item 8), 2026-09-24 - admin-only
    read of the curated security/compliance audit trail, newest first.
    """
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can view the audit log")

    entries = db.query(AuditLogEntry).order_by(AuditLogEntry.created_at.desc()).all()

    return [
        {
            "id": e.id,
            "actor_user_id": e.actor_user_id,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "detail": e.detail,
            "created_at": e.created_at.isoformat()
        }
        for e in entries
    ]


@app.post("/users/{user_id}/set-password")
def set_password(
    user_id: int,
    request: SetPasswordRequest,
    db: Session = Depends(get_db)
):
    user = db.query(UserModel).filter(UserModel.id == user_id).first()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.hashed_password is not None:
        raise HTTPException(
            status_code=400,
            detail="Password already set for this user"
        )

    user.hashed_password = hash_password(request.password)
    db.commit()

    return {"message": "Password set successfully"}


@app.put("/change-password")
def change_password(
    request: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.hashed_password is None:
        raise HTTPException(
            status_code=400,
            detail="No password set yet for this account. Use the set-password endpoint instead."
        )

    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect"
        )

    current_user.hashed_password = hash_password(request.new_password)
    current_user.tokens_valid_since = datetime.utcnow().replace(microsecond=0)
    log_audit_event(db, current_user.id, "password_changed", target_type="user", target_id=current_user.id)
    db.commit()

    return {"message": "Password changed successfully"}


@app.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Full-gap-closure pass (Batch B, group 3 item 15), 2026-09-24 - always
    returns the same generic message whether or not the email exists, to
    avoid leaking account existence. Deliberately does not catch
    RuntimeError from email_client.send_email() - if email isn't
    configured yet, this fails loudly (500) rather than pretending to
    have sent an email it didn't send.
    """
    generic_response = {"message": "If an account with that email exists, a password reset link has been sent."}

    user = db.query(UserModel).filter(UserModel.email == request.email).first()
    if user is None:
        return generic_response

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.utcnow()

    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        used_at=None
    )
    db.add(reset_token)
    db.commit()

    reset_link = f"https://kevo.example/reset-password?token={raw_token}"
    email_client.send_email(
        user.email,
        "Reset your KEVO password",
        f"""Click here to reset your password: {reset_link}

This link expires in 30 minutes and can only be used once. If you didn't request this, you can ignore this email."""
    )

    return generic_response


@app.post("/reset-password")
def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """
    Full-gap-closure pass (Batch B, group 3 item 15), 2026-09-24 - hashes
    the provided raw token and looks up the match by hash (never stores
    or compares the raw token), rejects if already used or expired, then
    updates the password and marks the token used in the same commit.
    """
    token_hash = hashlib.sha256(request.token.encode()).hexdigest()
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).first()

    if reset_token is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if reset_token.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if reset_token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = db.query(UserModel).filter(UserModel.id == reset_token.user_id).first()
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.hashed_password = hash_password(request.new_password)
    user.tokens_valid_since = datetime.utcnow().replace(microsecond=0)
    reset_token.used_at = datetime.utcnow()
    log_audit_event(db, user.id, "password_reset_completed", target_type="user", target_id=user.id)
    db.commit()

    return {"message": "Password reset successfully"}


@app.get("/compliance-rules/matches/{buyer_id}/{listing_id}")
def get_applicable_compliance_rules(
    buyer_id: int,
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    buyer = db.query(UserModel).filter(
        UserModel.id == buyer_id
    ).first()

    if buyer is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer not found"
        )

    if current_user.account_type != "admin" and current_user.id != buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own compliance rule matches"
        )

    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    result = assess_compliance(buyer, listing, db)

    return {
        "buyer_id": buyer.id,
        "listing_id": listing.id,
        "status": result["status"],
        "explanation": result["explanation"],
        "applicable_rule_codes": result["applicable_rule_codes"]
    }


@app.get("/me/eligibility-check/{listing_id}")
def check_my_eligibility(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    M31 gap-closure item, 2026-09-25 - Eligibility Pre-Check, the first of
    M31's four remaining pieces. A friendlier, self-only wrapper around the
    real GET /compliance-rules/matches/{buyer_id}/{listing_id} engine
    (fixed the same day to stop leaking other buyers' compliance verdicts)
    - a buyer checks whether they'd currently pass compliance on a real
    listing before expressing interest or negotiating, without needing to
    know their own buyer_id. Always self-scoped; there is no way to check
    another buyer's eligibility through this endpoint. Reuses
    assess_compliance() directly - no new logic, no new table.
    """
    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    result = assess_compliance(current_user, listing, db)

    return {
        "buyer_id": current_user.id,
        "listing_id": listing.id,
        "status": result["status"],
        "explanation": result["explanation"],
        "applicable_rule_codes": result["applicable_rule_codes"]
    }


@app.get("/transferability/listing/{listing_id}")
def get_transferability_assessment(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
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
    }

@app.get("/transferability/listing/{listing_id}/applicable-rules")
def get_applicable_transferability_rules(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    rules = find_applicable_transferability_rules(listing, db)

    return {
        "listing_id": listing.id,
        "applicable_rules": [
            {
                "id": r.id,
                "rule_code": r.rule_code,
                "requirement": r.requirement,
                "decision_if_unmet": r.decision_if_unmet,
                "source_reference": r.source_reference
            }
            for r in rules
        ]
    }

@app.get("/transferability/matrix")
def get_transferability_matrix(
    asset_type: str = "Private Shares",
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
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
MIN_SIGNUP_AGE_YEARS = 18


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

    if not user.terms_accepted:
        raise HTTPException(
            status_code=400,
            detail="You must accept the Terms & Conditions and Privacy Policy to create an account"
        )

    if not user.phone_number.strip():
        raise HTTPException(status_code=400, detail="Phone number is required")

    if not user.jurisdiction.strip():
        raise HTTPException(status_code=400, detail="Jurisdiction is required")

    today = date.today()
    age_years = today.year - user.date_of_birth.year - (
        (today.month, today.day) < (user.date_of_birth.month, user.date_of_birth.day)
    )
    if age_years < MIN_SIGNUP_AGE_YEARS:
        raise HTTPException(
            status_code=400,
            detail=f"You must be at least {MIN_SIGNUP_AGE_YEARS} years old to create a KEVO account"
        )

    new_user = UserModel(
        name=user.name,
        email=user.email,
        hashed_password=hash_password(user.password),
        role=user.role,
        seller_affiliate_status=user.seller_affiliate_status,
        jurisdiction=user.jurisdiction,
        phone_number=user.phone_number,
        date_of_birth=user.date_of_birth,
        terms_accepted=True,
        terms_accepted_at=datetime.utcnow(),
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
            "seller_affiliate_status": new_user.seller_affiliate_status,
            "jurisdiction": new_user.jurisdiction,
            "phone_number": new_user.phone_number,
            "date_of_birth": str(new_user.date_of_birth) if new_user.date_of_birth else None,
            "terms_accepted": new_user.terms_accepted
        }
    }


@app.get("/users")
def get_users(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    users = db.query(UserModel).all()

    return [
        {
            "id": user.id,
            "role": user.role
        }
        for user in users
    ]


@app.get("/me")
def get_my_profile(
    current_user: UserModel = Depends(get_current_user)
):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "kyc_status": current_user.kyc_status,
        "jurisdiction": current_user.jurisdiction,
        "account_type": current_user.account_type
    }


class WalletDepositRequest(BaseModel):
    amount: float
    currency: str = "USD"
    idempotency_key: str


class WalletWithdrawRequest(BaseModel):
    amount: float
    currency: str = "USD"
    bank_account_id: int
    idempotency_key: str


class ConfirmWithdrawalRequest(BaseModel):
    token: str


class BankAccountRequest(BaseModel):
    account_holder_name: str
    bank_name: str
    account_number: str


# Withdrawals at or above this amount require step-up authentication (an
# emailed confirmation link) before they're processed - spec Section 15.
# Easy constant to change; not yet configurable per-wallet.
STEP_UP_WITHDRAWAL_THRESHOLD = 1000.00


@app.get("/me/funds")
def get_my_funds(
    current_user: UserModel = Depends(get_current_user)
):
    try:
        return wallet_client.get_wallet(current_user.id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Wallet service unavailable: {e}")


@app.post("/me/funds/deposit")
def deposit_to_my_wallet(
    request: WalletDepositRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    log_audit_event(db, current_user.id, "wallet_deposit_initiated", target_type="wallet", target_id=current_user.id,
                     detail=f"amount={request.amount} currency={request.currency}")
    try:
        result = wallet_client.deposit(current_user.id, request.amount, request.currency, request.idempotency_key)
    except RuntimeError as e:
        log_audit_event(db, current_user.id, "wallet_deposit_failed", target_type="wallet", target_id=current_user.id,
                         detail=str(e))
        raise HTTPException(status_code=502, detail=f"Wallet service unavailable: {e}")

    if result.get("status") == "COMPLETED":
        log_audit_event(db, current_user.id, "wallet_deposit_completed", target_type="wallet", target_id=current_user.id,
                         detail=f"amount={request.amount} currency={request.currency}")
    else:
        log_audit_event(db, current_user.id, "wallet_deposit_failed", target_type="wallet", target_id=current_user.id,
                         detail=result.get("failureReason") or "unknown failure")
        raise HTTPException(status_code=400, detail=result.get("failureReason") or "Deposit failed")

    return result


@app.post("/me/funds/withdraw")
def withdraw_from_my_wallet(
    request: WalletWithdrawRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    log_audit_event(db, current_user.id, "wallet_withdrawal_requested", target_type="wallet", target_id=current_user.id,
                     detail=f"amount={request.amount} currency={request.currency}")

    if request.amount >= STEP_UP_WITHDRAWAL_THRESHOLD:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        now = datetime.utcnow()

        confirmation = WithdrawalConfirmation(
            user_id=current_user.id,
            token_hash=token_hash,
            amount=request.amount,
            currency=request.currency,
            bank_account_id=request.bank_account_id,
            idempotency_key=request.idempotency_key,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
            used_at=None
        )
        db.add(confirmation)
        log_audit_event(db, current_user.id, "wallet_withdrawal_confirmation_sent", target_type="wallet", target_id=current_user.id,
                         detail=f"amount={request.amount} currency={request.currency}")
        db.commit()

        confirm_link = f"https://kevo.example/confirm-withdrawal?token={raw_token}"
        try:
            email_client.send_email(
                current_user.email,
                "Confirm your KEVO withdrawal",
                f"""You requested a withdrawal of {request.amount} {request.currency} from your KEVO wallet.

Click here to confirm: {confirm_link}

This link expires in 15 minutes and can only be used once. If you didn't request this, please secure your account immediately and contact support."""
            )
        except RuntimeError as e:
            log_audit_event(db, current_user.id, "wallet_withdrawal_confirmation_email_failed", target_type="wallet", target_id=current_user.id,
                             detail=str(e))
            raise HTTPException(status_code=502, detail=f"Could not send confirmation email: {e}")

        return {
            "status": "CONFIRMATION_REQUIRED",
            "message": "This withdrawal is above the confirmation threshold. Check your email to confirm it.",
            "expires_in_minutes": 15
        }

    try:
        result = wallet_client.withdraw(
            current_user.id, request.amount, request.currency,
            request.bank_account_id, request.idempotency_key
        )
    except RuntimeError as e:
        log_audit_event(db, current_user.id, "wallet_withdrawal_failed", target_type="wallet", target_id=current_user.id,
                         detail=str(e))
        raise HTTPException(status_code=502, detail=f"Wallet service unavailable: {e}")

    if result.get("status") == "COMPLETED":
        log_audit_event(db, current_user.id, "wallet_withdrawal_completed", target_type="wallet", target_id=current_user.id,
                         detail=f"amount={request.amount} currency={request.currency}")
    else:
        log_audit_event(db, current_user.id, "wallet_withdrawal_failed", target_type="wallet", target_id=current_user.id,
                         detail=result.get("failureReason") or "unknown failure")
        raise HTTPException(status_code=400, detail=result.get("failureReason") or "Withdrawal failed")

    return result


@app.post("/me/funds/withdraw/confirm")
def confirm_my_withdrawal(
    request: ConfirmWithdrawalRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    token_hash = hashlib.sha256(request.token.encode()).hexdigest()
    confirmation = db.query(WithdrawalConfirmation).filter(WithdrawalConfirmation.token_hash == token_hash).first()

    if confirmation is None:
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation token")

    if confirmation.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation token")

    if confirmation.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation token")

    if confirmation.user_id != current_user.id:
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation token")

    try:
        result = wallet_client.withdraw(
            current_user.id, float(confirmation.amount), confirmation.currency,
            confirmation.bank_account_id, confirmation.idempotency_key
        )
    except RuntimeError as e:
        log_audit_event(db, current_user.id, "wallet_withdrawal_failed", target_type="wallet", target_id=current_user.id,
                         detail=str(e))
        raise HTTPException(status_code=502, detail=f"Wallet service unavailable: {e}")

    confirmation.used_at = datetime.utcnow()

    if result.get("status") == "COMPLETED":
        log_audit_event(db, current_user.id, "wallet_withdrawal_completed", target_type="wallet", target_id=current_user.id,
                         detail=f"amount={confirmation.amount} currency={confirmation.currency} (confirmed)")
        db.commit()
    else:
        log_audit_event(db, current_user.id, "wallet_withdrawal_failed", target_type="wallet", target_id=current_user.id,
                         detail=result.get("failureReason") or "unknown failure")
        db.commit()
        raise HTTPException(status_code=400, detail=result.get("failureReason") or "Withdrawal failed")

    return result


@app.post("/me/bank-accounts")
def add_my_bank_account(
    request: BankAccountRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    log_audit_event(db, current_user.id, "bank_account_add_initiated", target_type="wallet", target_id=current_user.id,
                     detail=f"bank_name={request.bank_name}")
    try:
        result = wallet_client.add_bank_account(
            current_user.id, request.account_holder_name, request.bank_name, request.account_number
        )
    except RuntimeError as e:
        log_audit_event(db, current_user.id, "bank_account_add_failed", target_type="wallet", target_id=current_user.id,
                         detail=str(e))
        raise HTTPException(status_code=502, detail=f"Wallet service unavailable: {e}")

    log_audit_event(db, current_user.id, "bank_account_added", target_type="wallet", target_id=current_user.id,
                     detail=f"bank_account_id={result.get('id')} bank_name={request.bank_name}")
    return result


@app.get("/me/bank-accounts")
def list_my_bank_accounts(
    current_user: UserModel = Depends(get_current_user)
):
    try:
        return wallet_client.list_bank_accounts(current_user.id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Wallet service unavailable: {e}")


@app.post("/me/bank-accounts/{bank_account_id}/verify")
def verify_my_bank_account(
    bank_account_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    try:
        result = wallet_client.verify_bank_account(current_user.id, bank_account_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Wallet service unavailable: {e}")

    log_audit_event(db, current_user.id, "bank_account_verified", target_type="wallet", target_id=current_user.id,
                     detail=f"bank_account_id={bank_account_id}")
    return result


@app.post("/me/bank-accounts/{bank_account_id}/disable")
def disable_my_bank_account(
    bank_account_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    try:
        result = wallet_client.disable_bank_account(current_user.id, bank_account_id)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Wallet service unavailable: {e}")

    log_audit_event(db, current_user.id, "bank_account_disabled", target_type="wallet", target_id=current_user.id,
                     detail=f"bank_account_id={bank_account_id}")
    return result


@app.put("/users/{user_id}/kyc-status")
def update_kyc_status(
    user_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin can update KYC status"
        )

    user = db.query(UserModel).filter(
        UserModel.id == user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if status not in ["verified", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Status must be verified or rejected"
        )

    old_status = user.kyc_status
    user.kyc_status = status

    log_audit_event(db, current_user.id, "kyc_status_changed", target_type="user", target_id=user.id, detail=f"{old_status} -> {status}")
    db.commit()
    db.refresh(user)

    return {
        "message": "KYC status updated",
        "user": {
            "id": user.id,
            "role": user.role,
            "kyc_status": user.kyc_status
        }
    }


@app.post("/ownership")
def create_ownership(
    ownership: OwnershipCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.id != ownership.seller_id:
        raise HTTPException(
            status_code=403,
            detail="You can only create ownership records for yourself"
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
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    # INVARIANT (2026-09-09): agreed_price MUST remain a value the caller
    # supplies, reflecting terms two humans already agreed to off-platform.
    # KEVO's own logic must never set, suggest, derive, or default this
    # value from a listing's asking_price, a buyer interest's
    # maximum_price, a demand-heatmap/curve figure, or any other
    # KEVO-computed number. Do not add a default, a suggestion, or an
    # auto-fill for agreed_price here.
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

    buyer = db.query(UserModel).filter(
        UserModel.id == transaction.buyer_id
    ).first()

    if buyer is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer not found"
        )
    if buyer.seller_financing_blocked:
        raise HTTPException(
            status_code=403,
            detail="This buyer's account is restricted due to an unresolved seller financing default."
        )

    if current_user.id not in (buyer.id, seller.id):
        raise HTTPException(
            status_code=403,
            detail="You must be a party to this transaction to create it"
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
    committed_transactions = db.query(Transaction).filter(
        Transaction.listing_id == transaction.listing_id,
        Transaction.status.in_(["accepted", "settlement_pending", "completed"])
    ).all()
    committed_quantity = sum(t.quantity for t in committed_transactions)

    if transaction.quantity + committed_quantity > listing.quantity:
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
        status="interested",
        settlement_currency="USD"
    )

    db.add(new_transaction)
    db.commit()
    db.refresh(new_transaction)

    log_compliance_decision(new_transaction, buyer, listing, "transaction_created", db)

    return {
        "message": "Transaction created",
        "transaction": {
            "id": new_transaction.id,
            "listing_id": new_transaction.listing_id,
            "buyer_id": new_transaction.buyer_id,
            "seller_id": new_transaction.seller_id,
            "quantity": new_transaction.quantity,
            "agreed_price": new_transaction.agreed_price,
            "status": new_transaction.status,
            "settlement_currency": new_transaction.settlement_currency
        }
    }


@app.get("/transactions")
def get_transactions(db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    if current_user.account_type == "admin":
        transactions = db.query(Transaction).all()
    else:
        transactions = db.query(Transaction).filter(
            (Transaction.buyer_id == current_user.id) | (Transaction.seller_id == current_user.id)
        ).all()

    return [
        {
            "id": t.id,
            "listing_id": t.listing_id,
            "buyer_id": t.buyer_id,
            "seller_id": t.seller_id,
            "quantity": t.quantity,
            "agreed_price": t.agreed_price,
            "status": t.status,
            "settlement_currency": t.settlement_currency
        }
        for t in transactions
    ]


@app.get("/transactions/{transaction_id}")
def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )

    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(
            status_code=403,
            detail="You are not a party to this transaction"
        )

    return {
        "transaction": {
            "id": transaction.id,
            "listing_id": transaction.listing_id,
            "buyer_id": transaction.buyer_id,
            "seller_id": transaction.seller_id,
            "quantity": transaction.quantity,
            "agreed_price": transaction.agreed_price,
            "status": transaction.status,
            "settlement_currency": transaction.settlement_currency
        }
    }      


class TransactionCostEstimateRequest(BaseModel):
    transaction_id: int | None = None
    headline_valuation: float | None = Field(default=None, ge=0)
    legal_fee: float = Field(default=0, ge=0)
    platform_fee: float = Field(default=0, ge=0)
    settlement_fee: float = Field(default=0, ge=0)
    custody_fee: float = Field(default=0, ge=0)
    fx_fee: float = Field(default=0, ge=0)
    transfer_fee: float = Field(default=0, ge=0)
    taxes_other: float = Field(default=0, ge=0)


@app.post("/transaction-cost-estimate")
def estimate_transaction_cost(
    request: TransactionCostEstimateRequest,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Full-gap-closure pass (Batch B, group 3 item 9), 2026-09-24 - a pure
    arithmetic estimator: headline valuation minus every user-entered
    friction cost equals estimated net proceeds. Deliberately does not
    assume or hardcode a KEVO platform fee percentage - the project's own
    prior research (kevo-bd-partner-economics-research.md) found that
    whether KEVO can lawfully charge a transaction-contingent fee at all
    is still an open, legally-constrained question under FINRA Rule 2040
    depending on final licensing structure, and no real rate has been
    decided anywhere in this project. Every friction category here
    (including "platform fee") is therefore a value the caller supplies
    themselves - this endpoint does no fee-setting of its own, only the
    subtraction. When tied to a real transaction_id, surfaces that
    transaction's settlement_currency (M26C) in the response so the
    estimate is labeled with the currency it actually settles in - it
    does not perform any FX conversion itself, consistent with M26C's
    decision that KEVO does not handle cross-currency conversion.
    """
    currency = "USD"

    if request.transaction_id is not None:
        transaction = db.query(Transaction).filter(
            Transaction.id == request.transaction_id
        ).first()

        if transaction is None:
            raise HTTPException(status_code=404, detail="Transaction not found")

        if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
            raise HTTPException(status_code=403, detail="You are not a party to this transaction")

        currency = transaction.settlement_currency

        if request.headline_valuation is not None:
            headline_valuation = request.headline_valuation
        else:
            headline_valuation = float(transaction.quantity) * float(transaction.agreed_price)
    else:
        if request.headline_valuation is None:
            raise HTTPException(
                status_code=400,
                detail="headline_valuation is required when transaction_id is not provided"
            )
        headline_valuation = request.headline_valuation

    breakdown = {
        "legal_fee": request.legal_fee,
        "platform_fee": request.platform_fee,
        "settlement_fee": request.settlement_fee,
        "custody_fee": request.custody_fee,
        "fx_fee": request.fx_fee,
        "transfer_fee": request.transfer_fee,
        "taxes_other": request.taxes_other,
    }

    total_friction = sum(breakdown.values())
    net_proceeds = headline_valuation - total_friction

    return {
        "transaction_id": request.transaction_id,
        "currency": currency,
        "headline_valuation": headline_valuation,
        "breakdown": breakdown,
        "total_friction": total_friction,
        "net_proceeds": net_proceeds
    }


@app.put("/ownership/{ownership_id}/verify")
def verify_ownership(
    ownership_id: int,
    status: str,
    verification_reference: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin can verify ownership records"
        )

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
            "listing_id": ownership.listing_id,
            "seller_id": ownership.seller_id,
            "company": ownership.company,
            "asset_type": ownership.asset_type,
            "quantity": ownership.quantity,
            "verification_status": ownership.verification_status,
            "verification_reference": ownership.verification_reference
        }
    }


@app.get("/ownership-records")
def get_ownership_records(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        return db.query(OwnershipRecord).all()
    return db.query(OwnershipRecord).filter(OwnershipRecord.seller_id == current_user.id).all()


@app.post("/listings")
def create_listing(
    listing: ListingCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.id != listing.seller_id:
        raise HTTPException(
            status_code=403,
            detail="You can only create listings for yourself"
        )

    # Seller Financing Protection System (2026-09-24) - transfer-block hook.
    # Only enforced when the parties themselves opted into
    # restricts_transfer_until_paid on the SellerFinancingAgreement that
    # made this user the buyer of this exact company/asset_type - KEVO
    # never invents a universal resale restriction, it only enforces the
    # term the parties actually agreed to.
    blocking_agreement = (
        db.query(SellerFinancingAgreement)
        .join(Transaction, Transaction.id == SellerFinancingAgreement.transaction_id)
        .join(ListingModel, ListingModel.id == Transaction.listing_id)
        .filter(
            Transaction.buyer_id == current_user.id,
            SellerFinancingAgreement.status == "active",
            SellerFinancingAgreement.restricts_transfer_until_paid == True,
            ListingModel.company == listing.company,
            ListingModel.asset_type == listing.asset_type,
        )
        .first()
    )
    if blocking_agreement is not None:
        raise HTTPException(
            status_code=403,
            detail="This position can't be relisted until seller financing agreement #{} is fully paid or resolved (you agreed to this restriction when the agreement was created).".format(blocking_agreement.id)
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

    # M31 (2026-09-21) - Smart Deal Alerts: reuse find_matches()'s exact
    # same non-discretionary criteria (company, asset_type, price,
    # quantity) to notify any buyer whose standing, active BuyerInterest
    # already matches this brand-new listing, so they don't have to keep
    # re-checking manually. Flat, chronological, never scored or ranked.
    matching_interests = db.query(BuyerInterest).filter(
        BuyerInterest.company == new_listing.company,
        BuyerInterest.asset_type == new_listing.asset_type,
        BuyerInterest.status == "active",
        BuyerInterest.maximum_price >= new_listing.asking_price,
        BuyerInterest.desired_quantity <= new_listing.quantity
    ).all()
    for interest in matching_interests:
        db.add(DealAlert(
            buyer_interest_id=interest.id,
            listing_id=new_listing.id,
            buyer_id=interest.buyer_id,
            created_at=datetime.utcnow()
        ))
    if matching_interests:
        db.commit()

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
def get_listings(db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    listings = db.query(ListingModel).all()

    return [
        {
            "id": listing.id,
            "seller_id": listing.seller_id,
            "company": listing.company,
            "asset_type": listing.asset_type,
            "quantity": listing.quantity,
            "asking_price": float(listing.asking_price),
            "issuer_reporting_status": listing.issuer_reporting_status,
            "issuer_current_information_available": listing.issuer_current_information_available,
            "issuer_jurisdiction": listing.issuer_jurisdiction,
            "is_transferable": listing.is_transferable
        }
        for listing in listings
    ]


@app.get("/listings/{listing_id}")
def get_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
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
            "asking_price": float(listing.asking_price),
            "issuer_reporting_status": listing.issuer_reporting_status,
            "issuer_current_information_available": listing.issuer_current_information_available,
            "issuer_jurisdiction": listing.issuer_jurisdiction,
            "is_transferable": listing.is_transferable
        },
        "seller": {
            "id": seller.id,
            "role": seller.role
        }
    }
@app.put("/listings/{listing_id}")
def update_listing(
    listing_id: int,
    listing_data: ListingCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    if current_user.id != listing.seller_id:
        raise HTTPException(
            status_code=403,
            detail="You can only modify your own listings"
        )

    if listing_data.seller_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You cannot reassign a listing to another user"
        )

    listing.seller_id = listing_data.seller_id
    listing.company = listing_data.company
    listing.asset_type = listing_data.asset_type
    listing.quantity = listing_data.quantity
    listing.asking_price = listing_data.asking_price
    listing.issuer_reporting_status = listing_data.issuer_reporting_status
    listing.issuer_current_information_available = listing_data.issuer_current_information_available
    listing.issuer_jurisdiction = listing_data.issuer_jurisdiction
    listing.is_transferable = listing_data.is_transferable if listing_data.is_transferable is not None else False

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
            "asking_price": float(listing.asking_price),
            "issuer_reporting_status": listing.issuer_reporting_status,
            "issuer_current_information_available": listing.issuer_current_information_available,
            "issuer_jurisdiction": listing.issuer_jurisdiction,
            "is_transferable": listing.is_transferable
        }
    }


@app.delete("/listings/{listing_id}")
def delete_listing(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    if current_user.id != listing.seller_id:
        raise HTTPException(
            status_code=403,
            detail="You can only delete your own listings"
        )

    db.delete(listing)
    db.commit()

    return {
        "message": "Listing deleted",
        "listing_id": listing_id
    }

@app.patch("/transactions/{transaction_id}/status")
def update_transaction_status(
    transaction_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )

    is_admin = current_user.account_type == "admin"
    is_buyer = current_user.id == transaction.buyer_id
    is_seller = current_user.id == transaction.seller_id

    if not (is_admin or is_buyer or is_seller):
        raise HTTPException(
            status_code=403,
            detail="You are not a party to this transaction"
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

    # Lifecycle permission: accepting or rejecting is the seller's call
    # (responding to a stated buyer interest); cancelling stays open to
    # either party. Deliberately minimal for M19 - full negotiation
    # mechanics belong to the not-yet-built M25.
    seller_only_transitions = {"accepted", "rejected"}
    if status in seller_only_transitions and not (is_seller or is_admin):
        raise HTTPException(
            status_code=403,
            detail="Only the seller can accept or reject a transaction"
        )

    if status == "accepted":
        listing = db.query(ListingModel).filter(
            ListingModel.id == transaction.listing_id
        ).with_for_update().first()

        if listing is not None:
            committed_transactions = db.query(Transaction).filter(
                Transaction.listing_id == transaction.listing_id,
                Transaction.status.in_(["accepted", "settlement_pending", "completed"])
            ).all()
            committed_quantity = sum(t.quantity for t in committed_transactions)

            if transaction.quantity + committed_quantity > listing.quantity:
                raise HTTPException(
                    status_code=400,
                    detail="Not enough quantity available - already committed to other accepted transactions on this listing"
                )

        # M32 - lock the buyer's demo wallet funds for this transaction. If this
        # fails (insufficient funds, or the wallet service is unreachable), the
        # accept action itself must fail too - a transaction can never be marked
        # accepted while the buyer's committed funds aren't actually locked.
        lock_amount = float(transaction.quantity) * float(transaction.agreed_price)
        try:
            lock_result = wallet_client.lock_funds(
                transaction.buyer_id, lock_amount, transaction.settlement_currency,
                transaction.id, f"lock-tx-{transaction.id}"
            )
        except RuntimeError as e:
            log_audit_event(db, current_user.id, "wallet_lock_failed", target_type="transaction", target_id=transaction.id,
                             detail=str(e))
            db.commit()
            raise HTTPException(status_code=502, detail=f"Could not lock buyer funds: {e}")
        if lock_result.get("status") != "ACTIVE":
            log_audit_event(db, current_user.id, "wallet_lock_failed", target_type="transaction", target_id=transaction.id,
                             detail=lock_result.get("failureReason") or "unknown failure")
            db.commit()
            raise HTTPException(status_code=400, detail=lock_result.get("failureReason") or "Could not lock buyer funds")
        log_audit_event(db, current_user.id, "wallet_lock_completed", target_type="transaction", target_id=transaction.id,
                         detail=f"amount={lock_amount} currency={transaction.settlement_currency}")

    # M32 - a deal falling through after funds were already locked (accepted or
    # settlement_pending) must release them back to available. This uses the OLD
    # status (transaction.status, not yet overwritten below) to know a lock exists.
    if status == "cancelled" and transaction.status in ("accepted", "settlement_pending"):
        try:
            wallet_client.release_lock(transaction.buyer_id, transaction.id)
            log_audit_event(db, current_user.id, "wallet_release_completed", target_type="transaction", target_id=transaction.id)
        except RuntimeError as e:
            log_audit_event(db, current_user.id, "wallet_release_failed", target_type="transaction", target_id=transaction.id,
                             detail=str(e))
            db.commit()
            raise HTTPException(status_code=502, detail=f"Could not release buyer funds: {e}")

    transaction.status = status

    db.commit()
    db.refresh(transaction)

    ledger_buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
    ledger_listing = db.query(ListingModel).filter(ListingModel.id == transaction.listing_id).first()
    if ledger_buyer is not None and ledger_listing is not None:
        log_compliance_decision(transaction, ledger_buyer, ledger_listing, f"status_changed_to_{status}", db)

    return {
        "message": "Transaction status updated",
        "transaction": {
            "id": transaction.id,
            "listing_id": transaction.listing_id,
            "buyer_id": transaction.buyer_id,
            "seller_id": transaction.seller_id,
            "quantity": transaction.quantity,
            "agreed_price": transaction.agreed_price,
            "status": transaction.status,
            "settlement_currency": transaction.settlement_currency
        }
    }    

@app.post("/buyer-interests")
def create_buyer_interest(
    interest: BuyerInterestCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.id != interest.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only create buyer interests for yourself"
        )
    if current_user.seller_financing_blocked:
        raise HTTPException(
            status_code=403,
            detail="Your account is restricted due to an unresolved seller financing default. An admin must resolve it before you can express new interest."
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


@app.get("/buyer-interests")
def get_buyer_interests(db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    if current_user.account_type == "admin":
        interests = db.query(BuyerInterest).all()
    else:
        interests = db.query(BuyerInterest).filter(
            BuyerInterest.buyer_id == current_user.id
        ).all()

    return [
        {
            "id": i.id,
            "buyer_id": i.buyer_id,
            "company": i.company,
            "asset_type": i.asset_type,
            "desired_quantity": i.desired_quantity,
            "maximum_price": float(i.maximum_price),
            "status": i.status
        }
        for i in interests
    ]


@app.get("/buyer-interests/{interest_id}")
def get_buyer_interest(
    interest_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    interest = db.query(BuyerInterest).filter(
        BuyerInterest.id == interest_id
    ).first()

    if interest is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer interest not found"
        )

    if current_user.account_type != "admin" and current_user.id != interest.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own buyer interests"
        )

    return {
        "buyer_interest": {
            "id": interest.id,
            "buyer_id": interest.buyer_id,
            "company": interest.company,
            "asset_type": interest.asset_type,
            "desired_quantity": interest.desired_quantity,
            "maximum_price": float(interest.maximum_price),
            "status": interest.status
        }
    }    
@app.post("/buyer-interests/{interest_id}/withdraw")
def withdraw_buyer_interest(
    interest_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    interest = db.query(BuyerInterest).filter(
        BuyerInterest.id == interest_id
    ).first()

    if interest is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer interest not found"
        )

    if current_user.id != interest.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only withdraw your own buyer interests"
        )

    interest.status = "withdrawn"
    db.commit()
    db.refresh(interest)

    return {
        "message": "Buyer interest withdrawn",
        "buyer_interest": {
            "id": interest.id,
            "buyer_id": interest.buyer_id,
            "company": interest.company,
            "asset_type": interest.asset_type,
            "desired_quantity": interest.desired_quantity,
            "maximum_price": float(interest.maximum_price),
            "status": interest.status
        }
    }


@app.post("/investor-eligibility")
def create_investor_eligibility(
    eligibility: InvestorEligibilityCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    buyer = db.query(UserModel).filter(
        UserModel.id == eligibility.buyer_id
    ).first()

    if buyer is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer not found"
        )

    is_admin = current_user.account_type == "admin"

    if not is_admin and current_user.id != eligibility.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only submit eligibility records for yourself"
        )

    if not is_admin and eligibility.status == "verified":
        raise HTTPException(
            status_code=403,
            detail="Only an admin can mark investor eligibility as verified"
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


@app.get("/investor-eligibility")
def get_investor_eligibility_records(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        records = db.query(InvestorEligibility).all()
    else:
        records = db.query(InvestorEligibility).filter(
            InvestorEligibility.buyer_id == current_user.id
        ).all()

    return [
        {
            "id": r.id,
            "buyer_id": r.buyer_id,
            "investor_type": r.investor_type,
            "classification": r.classification,
            "status": r.status,
            "verification_method": r.verification_method,
            "evidence_reference": r.evidence_reference,
            "effective_date": r.effective_date,
            "review_date": r.review_date,
            "jurisdiction": r.jurisdiction
        }
        for r in records
    ]


@app.get("/investor-eligibility/{eligibility_id}")
def get_investor_eligibility_record(
    eligibility_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    record = db.query(InvestorEligibility).filter(
        InvestorEligibility.id == eligibility_id
    ).first()

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Investor eligibility record not found"
        )

    if current_user.account_type != "admin" and current_user.id != record.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own investor eligibility records"
        )

    return {
        "investor_eligibility": {
            "id": record.id,
            "buyer_id": record.buyer_id,
            "investor_type": record.investor_type,
            "classification": record.classification,
            "status": record.status,
            "verification_method": record.verification_method,
            "evidence_reference": record.evidence_reference,
            "effective_date": record.effective_date,
            "review_date": record.review_date,
            "jurisdiction": record.jurisdiction
        }
    }


@app.put("/investor-eligibility/{eligibility_id}/verify")
def verify_investor_eligibility(
    eligibility_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin can verify investor eligibility records"
        )

    record = db.query(InvestorEligibility).filter(
        InvestorEligibility.id == eligibility_id
    ).first()

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Investor eligibility record not found"
        )

    if status not in ["verified", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Status must be verified or rejected"
        )

    record.status = status

    db.commit()
    db.refresh(record)

    return {
        "message": "Investor eligibility verification updated",
        "investor_eligibility": {
            "id": record.id,
            "buyer_id": record.buyer_id,
            "investor_type": record.investor_type,
            "classification": record.classification,
            "status": record.status,
            "verification_method": record.verification_method,
            "evidence_reference": record.evidence_reference,
            "effective_date": record.effective_date,
            "review_date": record.review_date,
            "jurisdiction": record.jurisdiction
        }
    }


class EvidenceCreate(BaseModel):
    user_id: int
    listing_id: int | None = None
    transaction_id: int | None = None
    ownership_record_id: int | None = None
    evidence_type: str
    description: str
    file_reference: str | None = None
    file_hash: str | None = None
    source_reference: str | None = None


@app.post("/evidence")
def create_evidence(
    evidence: EvidenceCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    user = db.query(UserModel).filter(
        UserModel.id == evidence.user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    is_admin = current_user.account_type == "admin"

    if not is_admin and current_user.id != evidence.user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only submit evidence for yourself"
        )

    if evidence.file_reference and not evidence.file_hash:
        raise HTTPException(
            status_code=400,
            detail="file_hash is required when file_reference is provided"
        )

    if evidence.listing_id is not None:
        listing = db.query(ListingModel).filter(ListingModel.id == evidence.listing_id).first()
        if listing is None:
            raise HTTPException(status_code=404, detail="Listing not found")

    if evidence.transaction_id is not None:
        transaction = db.query(Transaction).filter(Transaction.id == evidence.transaction_id).first()
        if transaction is None:
            raise HTTPException(status_code=404, detail="Transaction not found")

    if evidence.ownership_record_id is not None:
        ownership_record = db.query(OwnershipRecord).filter(OwnershipRecord.id == evidence.ownership_record_id).first()
        if ownership_record is None:
            raise HTTPException(status_code=404, detail="Ownership record not found")

    new_evidence = Evidence(
        user_id=evidence.user_id,
        listing_id=evidence.listing_id,
        transaction_id=evidence.transaction_id,
        ownership_record_id=evidence.ownership_record_id,
        evidence_type=evidence.evidence_type,
        description=evidence.description,
        file_reference=evidence.file_reference,
        file_hash=evidence.file_hash,
        source_reference=evidence.source_reference
    )

    db.add(new_evidence)
    db.commit()
    db.refresh(new_evidence)

    return {
        "message": "Evidence created",
        "evidence": {
            "id": new_evidence.id,
            "user_id": new_evidence.user_id,
            "listing_id": new_evidence.listing_id,
            "transaction_id": new_evidence.transaction_id,
            "ownership_record_id": new_evidence.ownership_record_id,
            "evidence_type": new_evidence.evidence_type,
            "description": new_evidence.description,
            "file_reference": new_evidence.file_reference,
            "file_hash": new_evidence.file_hash,
            "verification_status": new_evidence.verification_status,
            "source_reference": new_evidence.source_reference
        }
    }


@app.put("/evidence/{evidence_id}/verify")
def verify_evidence(
    evidence_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin can verify evidence"
        )

    evidence = db.query(Evidence).filter(
        Evidence.id == evidence_id
    ).first()

    if evidence is None:
        raise HTTPException(
            status_code=404,
            detail="Evidence not found"
        )

    if status not in ["verified", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Status must be verified or rejected"
        )

    evidence.verification_status = status

    log_audit_event(db, current_user.id, "evidence_" + status, target_type="evidence", target_id=evidence.id)
    db.commit()
    db.refresh(evidence)

    return {
        "message": "Evidence verification updated",
        "evidence": {
            "id": evidence.id,
            "user_id": evidence.user_id,
            "listing_id": evidence.listing_id,
            "transaction_id": evidence.transaction_id,
            "ownership_record_id": evidence.ownership_record_id,
            "evidence_type": evidence.evidence_type,
            "description": evidence.description,
            "file_reference": evidence.file_reference,
            "file_hash": evidence.file_hash,
            "verification_status": evidence.verification_status,
            "source_reference": evidence.source_reference
        }
    }


@app.get("/evidence")
def get_evidence_records(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        records = db.query(Evidence).all()
    else:
        records = db.query(Evidence).filter(
            Evidence.user_id == current_user.id
        ).all()

    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "listing_id": r.listing_id,
            "transaction_id": r.transaction_id,
            "ownership_record_id": r.ownership_record_id,
            "evidence_type": r.evidence_type,
            "description": r.description,
            "file_reference": r.file_reference,
            "file_hash": r.file_hash,
            "verification_status": r.verification_status,
            "source_reference": r.source_reference
        }
        for r in records
    ]


@app.get("/evidence/{evidence_id}")
def get_evidence_record(
    evidence_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    record = db.query(Evidence).filter(
        Evidence.id == evidence_id
    ).first()

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Evidence not found"
        )

    if current_user.account_type != "admin" and current_user.id != record.user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own evidence"
        )

    return {
        "evidence": {
            "id": record.id,
            "user_id": record.user_id,
            "listing_id": record.listing_id,
            "transaction_id": record.transaction_id,
            "ownership_record_id": record.ownership_record_id,
            "evidence_type": record.evidence_type,
            "description": record.description,
            "file_reference": record.file_reference,
            "file_hash": record.file_hash,
            "verification_status": record.verification_status,
            "source_reference": record.source_reference
        }
    }


# ---------------------------------------------------------------------------
# Full-gap-closure pass (Batch B, group 3 item 7), 2026-09-24 - M23's
# file_reference/file_hash were caller-typed strings the platform never
# verified: a client could claim any string as the "hash" of a file it
# never actually sent. These two endpoints replace that trust with a real
# local-disk upload: the server reads the actual bytes, computes the real
# SHA-256 hash itself, writes the file under UPLOAD_DIR, and only then
# updates file_reference (to this file's own download URL) and file_hash
# (the real computed hash) on the Evidence row - superseding whatever was
# passed to POST /evidence originally, if anything.
# ---------------------------------------------------------------------------

FILE_VALIDATOR_URL = "http://127.0.0.1:8090"
UPLOAD_DIR = "uploads/evidence"
MAX_EVIDENCE_UPLOAD_BYTES = 20 * 1024 * 1024


@app.post("/evidence/{evidence_id}/upload-file")
async def upload_evidence_file(
    evidence_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()

    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")

    is_admin = current_user.account_type == "admin"
    if not is_admin and current_user.id != evidence.user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only upload a file to your own evidence"
        )

    if evidence.verification_status == "verified":
        raise HTTPException(
            status_code=400,
            detail="Cannot replace the file on evidence that has already been verified"
        )

    contents = await file.read()

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if len(contents) > MAX_EVIDENCE_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds the 20MB upload limit")

    # Defense-in-depth (file-upload-security item 7/10): never trust the
    # client's Content-Type or filename extension. Every upload goes to the
    # kevo-file-validator Rust service, which sniffs the real file type from
    # its magic bytes, re-encodes images to strip embedded payloads, scans
    # PDFs for active-content markers, and returns a server-generated safe
    # filename. We only ever store what THAT service hands back.
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            validator_resp = await client.post(
                f"{FILE_VALIDATOR_URL}/validate-upload",
                files={"file": (file.filename or "upload", contents, file.content_type or "application/octet-stream")},
            )

            if validator_resp.status_code != 200:
                try:
                    detail = validator_resp.json().get("error", "file failed validation")
                except ValueError:
                    detail = "file failed validation"
                raise HTTPException(status_code=400, detail=detail)

            validated = validator_resp.json()
            safe_filename = validated["safe_filename"]
            safe_ext = "." + safe_filename.rsplit(".", 1)[-1]

            fetch_resp = await client.get(f"{FILE_VALIDATOR_URL}/uploads/{safe_filename}")
            if fetch_resp.status_code != 200:
                raise HTTPException(status_code=503, detail="Could not retrieve the validated file - upload rejected")
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="File validation service is unavailable - upload rejected (fail closed)")

    safe_contents = fetch_resp.content
    file_hash = hashlib.sha256(safe_contents).hexdigest()

    evidence_dir = os.path.join(UPLOAD_DIR, str(evidence_id))
    os.makedirs(evidence_dir, exist_ok=True)
    stored_path = os.path.join(evidence_dir, file_hash + safe_ext)

    with open(stored_path, "wb") as out_file:
        out_file.write(safe_contents)

    evidence.file_reference = "/evidence/" + str(evidence_id) + "/file"
    evidence.file_hash = file_hash
    db.commit()
    db.refresh(evidence)

    return {
        "message": "File uploaded",
        "evidence": {
            "id": evidence.id,
            "user_id": evidence.user_id,
            "listing_id": evidence.listing_id,
            "transaction_id": evidence.transaction_id,
            "ownership_record_id": evidence.ownership_record_id,
            "evidence_type": evidence.evidence_type,
            "description": evidence.description,
            "file_reference": evidence.file_reference,
            "file_hash": evidence.file_hash,
            "verification_status": evidence.verification_status,
            "source_reference": evidence.source_reference
        }
    }


@app.get("/evidence/{evidence_id}/file")
def download_evidence_file(
    evidence_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()

    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")

    if current_user.account_type != "admin" and current_user.id != evidence.user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own evidence"
        )

    if not evidence.file_hash:
        raise HTTPException(status_code=404, detail="No file has been uploaded for this evidence")

    evidence_dir = os.path.join(UPLOAD_DIR, str(evidence_id))
    stored_files = os.listdir(evidence_dir) if os.path.isdir(evidence_dir) else []
    matching = [f for f in stored_files if f.startswith(evidence.file_hash)]

    if not matching:
        raise HTTPException(status_code=404, detail="No file has been uploaded for this evidence")

    stored_path = os.path.join(evidence_dir, matching[0])
    return FileResponse(stored_path, filename=matching[0])


@app.post("/kyc-facts")
def create_kyc_fact(
    fact: KYCFactCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    user = db.query(UserModel).filter(
        UserModel.id == fact.user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    is_admin = current_user.account_type == "admin"

    if not is_admin and current_user.id != fact.user_id:
        raise HTTPException(
            status_code=403,
            detail="You can only submit KYC facts for yourself"
        )

    new_fact = KYCFact(
        user_id=fact.user_id,
        jurisdiction=fact.jurisdiction,
        fact_type=fact.fact_type,
        fact_value=fact.fact_value,
        as_of_date=fact.as_of_date,
        evidence_id=fact.evidence_id,
        source_reference=fact.source_reference
    )

    db.add(new_fact)
    db.commit()
    db.refresh(new_fact)

    return {
        "message": "KYC fact created",
        "kyc_fact": {
            "id": new_fact.id,
            "user_id": new_fact.user_id,
            "jurisdiction": new_fact.jurisdiction,
            "fact_type": new_fact.fact_type,
            "fact_value": new_fact.fact_value,
            "as_of_date": new_fact.as_of_date,
            "verification_status": new_fact.verification_status,
            "evidence_id": new_fact.evidence_id,
            "source_reference": new_fact.source_reference
        }
    }


@app.get("/kyc-facts/user/{user_id}")
def get_kyc_facts_for_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.id != user_id and current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="You can only view your own KYC facts"
        )

    user = db.query(UserModel).filter(
        UserModel.id == user_id
    ).first()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    facts = db.query(KYCFact).filter(
        KYCFact.user_id == user_id
    ).all()

    return {
        "user_id": user_id,
        "kyc_status": user.kyc_status,
        "kyc_facts": [
            {
                "id": f.id,
                "jurisdiction": f.jurisdiction,
                "fact_type": f.fact_type,
                "fact_value": f.fact_value,
                "as_of_date": str(f.as_of_date) if f.as_of_date else None,
                "verification_status": f.verification_status,
                "source_reference": f.source_reference,
                "superseded_by_id": f.superseded_by_id
            }
            for f in facts
        ]
    }


@app.put("/kyc-facts/{fact_id}/verify")
def verify_kyc_fact(
    fact_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin can verify KYC facts"
        )

    fact = db.query(KYCFact).filter(
        KYCFact.id == fact_id
    ).first()

    if fact is None:
        raise HTTPException(
            status_code=404,
            detail="KYC fact not found"
        )

    if status not in ["verified", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Status must be verified or rejected"
        )

    fact.verification_status = status

    db.commit()
    db.refresh(fact)

    return {
        "message": "KYC fact verification updated",
        "kyc_fact": {
            "id": fact.id,
            "user_id": fact.user_id,
            "jurisdiction": fact.jurisdiction,
            "fact_type": fact.fact_type,
            "fact_value": fact.fact_value,
            "as_of_date": fact.as_of_date,
            "verification_status": fact.verification_status,
            "evidence_id": fact.evidence_id,
            "source_reference": fact.source_reference
        }
    }


@app.post("/compliance-rules")
def create_compliance_rule(
    rule: ComplianceRuleCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin can create compliance rules"
        )

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
        fact_type=rule.fact_type,
        requirement=rule.requirement,
        decision_if_unmet=rule.decision_if_unmet,
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
            "fact_type": new_rule.fact_type,
            "requirement": new_rule.requirement,
            "decision_if_unmet": new_rule.decision_if_unmet,
            "requires_human_review": new_rule.requires_human_review,
            "active": new_rule.active,
            "source_reference": new_rule.source_reference
        }
    }
@app.get("/compliance-rules")
def get_compliance_rules(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
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
            "fact_type": rule.fact_type,
            "requirement": rule.requirement,
            "decision_if_unmet": rule.decision_if_unmet,
            "requires_human_review": rule.requires_human_review,
            "active": rule.active,
            "source_reference": rule.source_reference
        }
        for rule in rules
    ]

@app.put("/compliance-rules/{rule_id}")
def update_compliance_rule(
    rule_id: int,
    update: ComplianceRuleUpdate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only an admin can update compliance rules"
        )

    rule = db.query(ComplianceRule).filter(ComplianceRule.id == rule_id).first()

    if rule is None:
        raise HTTPException(
            status_code=404,
            detail="Compliance rule not found"
        )

    update_data = update.dict(exclude_unset=True)

    if "rule_code" in update_data and update_data["rule_code"] != rule.rule_code:
        existing_rule = db.query(ComplianceRule).filter(
            ComplianceRule.rule_code == update_data["rule_code"],
            ComplianceRule.id != rule_id
        ).first()
        if existing_rule is not None:
            raise HTTPException(
                status_code=400,
                detail="Rule code already exists"
            )

    for field, value in update_data.items():
        setattr(rule, field, value)

    log_audit_event(db, current_user.id, "compliance_rule_updated", target_type="compliance_rule", target_id=rule.id, detail=", ".join(update_data.keys()))
    db.commit()
    db.refresh(rule)

    _trigger_compliance_rule_change_alerts(rule, db)

    return {
        "message": "Compliance rule updated",
        "compliance_rule": {
            "id": rule.id,
            "buyer_jurisdiction": rule.buyer_jurisdiction,
            "issuer_jurisdiction": rule.issuer_jurisdiction,
            "asset_type": rule.asset_type,
            "investor_classification": rule.investor_classification,
            "rule_code": rule.rule_code,
            "description": rule.description,
            "fact_type": rule.fact_type,
            "fact_validity_days": rule.fact_validity_days,
            "requirement": rule.requirement,
            "decision_if_unmet": rule.decision_if_unmet,
            "requires_human_review": rule.requires_human_review,
            "active": rule.active,
            "source_reference": rule.source_reference
        }
    }


@app.get("/buyer-interests/{interest_id}/matches")
def find_matches(
    interest_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    interest = db.query(BuyerInterest).filter(
        BuyerInterest.id == interest_id
    ).first()

    if interest is None:
        raise HTTPException(
            status_code=404,
            detail="Buyer interest not found"
        )

    if current_user.account_type != "admin" and current_user.id != interest.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view matches for your own buyer interest"
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
        compliance = assess_compliance(buyer, listing, db)

        compliance_results.append({
            "listing_id": listing.id,
            "seller_id": listing.seller_id,
            "company": listing.company,
            "asset_type": listing.asset_type,
            "quantity": listing.quantity,
            "asking_price": float(listing.asking_price),
            "compliance_status": compliance["status"],
            "compliance_explanation": compliance["explanation"],
            "compliance_applicable_rule_codes": compliance["applicable_rule_codes"],
            "match_status": compliance["status"]
        })
    return {
        "buyer_interest_id": interest.id,
        "matches_found": len(matches),
        "matches": compliance_results
    }    

@app.get("/deal-alerts")
def list_deal_alerts(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        alerts = db.query(DealAlert).order_by(DealAlert.created_at.desc()).all()
    else:
        alerts = db.query(DealAlert).filter(
            DealAlert.buyer_id == current_user.id
        ).order_by(DealAlert.created_at.desc()).all()

    return {
        "alerts": [
            {
                "id": a.id,
                "buyer_interest_id": a.buyer_interest_id,
                "listing_id": a.listing_id,
                "buyer_id": a.buyer_id,
                "is_read": a.is_read,
                "read_at": a.read_at.isoformat() if a.read_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None
            }
            for a in alerts
        ]
    }


@app.get("/deal-alerts/{alert_id}")
def get_deal_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    alert = db.query(DealAlert).filter(DealAlert.id == alert_id).first()

    if alert is None:
        raise HTTPException(status_code=404, detail="Deal alert not found")

    if current_user.account_type != "admin" and current_user.id != alert.buyer_id:
        raise HTTPException(status_code=403, detail="You can only view your own deal alerts")

    return {
        "id": alert.id,
        "buyer_interest_id": alert.buyer_interest_id,
        "listing_id": alert.listing_id,
        "buyer_id": alert.buyer_id,
        "is_read": alert.is_read,
        "read_at": alert.read_at.isoformat() if alert.read_at else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None
    }


@app.put("/deal-alerts/{alert_id}/mark-read")
def mark_deal_alert_read(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    alert = db.query(DealAlert).filter(DealAlert.id == alert_id).first()

    if alert is None:
        raise HTTPException(status_code=404, detail="Deal alert not found")

    if current_user.id != alert.buyer_id:
        raise HTTPException(status_code=403, detail="You can only mark your own deal alerts as read")

    alert.is_read = True
    alert.read_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)

    return {
        "id": alert.id,
        "is_read": alert.is_read,
        "read_at": alert.read_at.isoformat() if alert.read_at else None
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
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
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
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
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


def evaluate_reg_s(offering, db):
    if offering.jurisdiction != "United States":
        return {
            "exemption_code": "US-REG-S",
            "status": "needs_evidence",
            "reasons": [
                "Regulation S category determination for non-US issuers is not yet modeled in KEVO \u2014 only the Category 3 (US-organized issuer) pathway is currently evaluated"
            ]
        }

    reasons = []
    blocking = False
    needs_evidence = False
    conflict = False

    reg_s_facts = [
        ("offshore_transaction_confirmed", "Offshore transaction status (Rule 902(h)) not yet verified", "Sale has not been confirmed as an offshore transaction under Rule 902(h)"),
        ("no_directed_selling_efforts_in_us", "Absence of directed selling efforts in the US not yet verified", "Directed selling efforts in the US were found, which disqualifies Regulation S"),
        ("reg_s_purchaser_certification_documented", "Purchaser non-US-person certification not yet verified", "Category 3 equity requires documented purchaser certification of non-US-person status"),
        ("reg_s_transfer_legend_applied", "Transfer legend on the securities not yet verified", "Category 3 for a domestic issuer requires a transfer legend restricting resale into the US")
    ]

    for fact_type, evidence_reason, blocking_reason in reg_s_facts:
        state, value = get_offering_fact_status(offering.id, fact_type, db)
        if state == "conflict":
            conflict = True
            reasons.append("Conflicting verified facts for " + fact_type)
        elif state in ("missing", "pending"):
            needs_evidence = True
            reasons.append(evidence_reason)
        elif value != "true":
            blocking = True
            reasons.append(blocking_reason)

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
            "All checked facts for Regulation S (Category 3, US-organized issuer) are present and verified \u2014 this is not a legal conclusion, human/legal review is still required"
        )

    return {"exemption_code": "US-REG-S", "status": status, "reasons": reasons}


def evaluate_offering_exemptions(offering, db):
    return [
        evaluate_506b(offering, db),
        evaluate_506c(offering, db),
        evaluate_regcf(offering, db),
        evaluate_reg_a_tier1(offering, db),
        evaluate_reg_a_tier2(offering, db),
        evaluate_reg_s(offering, db)
    ]


@app.get("/offering-exemptions/{offering_id}")
def get_offering_exemptions(
    offering_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
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
    }



def build_liquidity_path(listing, db, transaction_id=None):
    steps = []

    ownership_record = db.query(OwnershipRecord).filter(
        OwnershipRecord.listing_id == listing.id
    ).first()

    if ownership_record is None:
        steps.append({
            "step_type": "OWNERSHIP_VERIFICATION",
            "sequence_position": 1,
            "required": True,
            "complete": False,
            "evidence_reference_type": None,
            "evidence_reference_id": None,
            "responsible_party": "holder",
            "completion_trigger": "Holder submits ownership evidence and KEVO verifies it",
            "determinability": "known_incomplete",
            "reasons": "No ownership record on file for this listing",
            "source_milestone": "M4/M5"
        })
    else:
        ownership_complete = ownership_record.verification_status == "verified"
        steps.append({
            "step_type": "OWNERSHIP_VERIFICATION",
            "sequence_position": 1,
            "required": True,
            "complete": ownership_complete,
            "evidence_reference_type": "OwnershipRecord",
            "evidence_reference_id": ownership_record.id,
            "responsible_party": "kevo",
            "completion_trigger": "KEVO marks the ownership record's verification_status as 'verified'",
            "determinability": "known_complete" if ownership_complete else "known_incomplete",
            "reasons": "Ownership record verification_status is '" + ownership_record.verification_status + "'",
            "source_milestone": "M4/M5"
        })

    transferability_result = evaluate_transferability(listing, db)
    transferability_status = transferability_result["status"]
    transferability_complete = transferability_status == "eligible_pending_review"

    if transferability_status == "conflict" or transferability_status == "review":
        transferability_determinability = "cannot_determine"
    elif transferability_complete:
        transferability_determinability = "known_complete"
    else:
        transferability_determinability = "known_incomplete"

    steps.append({
        "step_type": "TRANSFERABILITY_CLEARANCE",
        "sequence_position": 2,
        "required": True,
        "complete": transferability_complete,
        "evidence_reference_type": "TransferabilityFact",
        "evidence_reference_id": None,
        "responsible_party": "kevo",
        "completion_trigger": "All applicable transferability facts become verified and consistent",
        "determinability": transferability_determinability,
        "reasons": "; ".join(transferability_result["reasons"]),
        "source_milestone": "M14"
    })

    evidence_query = db.query(Evidence).filter(
        Evidence.listing_id == listing.id
    )
    evidence_verified_count = evidence_query.filter(
        Evidence.verification_status == "verified"
    ).count()
    evidence_pending_count = evidence_query.filter(
        Evidence.verification_status != "verified"
    ).count()

    steps.append({
        "step_type": "DOCUMENTATION_COMPLETE",
        "sequence_position": 3,
        "required": None,
        "complete": False,
        "evidence_reference_type": "Evidence",
        "evidence_reference_id": None,
        "responsible_party": "holder",
        "completion_trigger": "KEVO builds a per-jurisdiction required-document registry (not yet built) and every required document is verified",
        "determinability": "required_but_unverified",
        "reasons": str(evidence_verified_count) + " verified and " + str(evidence_pending_count) + " pending evidence record(s) on file — KEVO cannot yet confirm this is the complete required set, no per-jurisdiction required-document registry exists yet",
        "source_milestone": "M23 first slice built (Evidence CRUD); per-jurisdiction required-document registry not yet built"
    })

    applicable_rules = find_applicable_transferability_rules(listing, db)
    rofr_rule = None
    for rule in applicable_rules:
        if rule.rule_code == "ZA-COMPANIES-S8-ROFR-CONSENT":
            rofr_rule = rule

    if rofr_rule is None:
        steps.append({
            "step_type": "ISSUER_APPROVAL_ROFR",
            "sequence_position": 4,
            "required": None,
            "complete": False,
            "evidence_reference_type": None,
            "evidence_reference_id": None,
            "responsible_party": "issuer",
            "completion_trigger": "M25 builds real ROFR/consent detection for this listing's jurisdiction",
            "determinability": "cannot_determine",
            "reasons": "No ROFR/consent rule is currently encoded for this listing's jurisdiction and asset type — this does not mean no ROFR applies, only that KEVO cannot yet tell",
            "source_milestone": "M25 (not yet built)"
        })
    else:
        rofr_facts = db.query(TransferabilityFact).filter(
            TransferabilityFact.listing_id == listing.id,
            TransferabilityFact.fact_type == rofr_rule.fact_type,
            TransferabilityFact.superseded_by_id.is_(None)
        ).all()
        rofr_verified_facts = [f for f in rofr_facts if f.verification_status == "verified"]

        if rofr_verified_facts:
            rofr_fact = rofr_verified_facts[0]
            steps.append({
                "step_type": "ISSUER_APPROVAL_ROFR",
                "sequence_position": 4,
                "required": True,
                "complete": True,
                "evidence_reference_type": "TransferabilityFact",
                "evidence_reference_id": rofr_fact.id,
                "responsible_party": "issuer",
                "completion_trigger": "Already resolved by a verified fact",
                "determinability": "known_complete",
                "reasons": "Verified fact on file for rule " + rofr_rule.rule_code,
                "source_milestone": "M14"
            })
        else:
            steps.append({
                "step_type": "ISSUER_APPROVAL_ROFR",
                "sequence_position": 4,
                "required": True,
                "complete": False,
                "evidence_reference_type": "TransferabilityRule",
                "evidence_reference_id": rofr_rule.id,
                "responsible_party": "issuer",
                "completion_trigger": "Issuer/company secretary confirms ROFR waiver or consent, and KEVO verifies the fact",
                "determinability": "required_but_unverified",
                "reasons": "Rule " + rofr_rule.rule_code + " applies but no verified fact is on file yet",
                "source_milestone": "M14"
            })

    if transaction_id is not None:
        transaction = db.query(Transaction).filter(
            Transaction.id == transaction_id,
            Transaction.listing_id == listing.id
        ).first()
    else:
        transaction = db.query(Transaction).filter(
            Transaction.listing_id == listing.id
        ).order_by(Transaction.id.desc()).first()

    if transaction is None:
        steps.append({
            "step_type": "BUYER_ELIGIBILITY_COMPLIANCE",
            "sequence_position": 5,
            "required": True,
            "complete": False,
            "evidence_reference_type": None,
            "evidence_reference_id": None,
            "responsible_party": "buyer",
            "completion_trigger": "A candidate buyer is identified and passes KEVO's compliance rule evaluation",
            "determinability": "required_but_unverified",
            "reasons": "No candidate buyer identified yet for this listing — compliance rules (M13) are ready to evaluate one as soon as a buyer exists",
            "source_milestone": "M13"
        })
    else:
        candidate_buyer = db.query(UserModel).filter(
            UserModel.id == transaction.buyer_id
        ).first()

        compliance_result = assess_compliance(candidate_buyer, listing, db)
        compliance_status = compliance_result["status"]
        compliance_complete = compliance_status == "eligible_pending_review"

        if compliance_status == "review":
            compliance_determinability = "cannot_determine"
        elif compliance_complete:
            compliance_determinability = "known_complete"
        else:
            compliance_determinability = "known_incomplete"

        steps.append({
            "step_type": "BUYER_ELIGIBILITY_COMPLIANCE",
            "sequence_position": 5,
            "required": True,
            "complete": compliance_complete,
            "evidence_reference_type": "Transaction",
            "evidence_reference_id": transaction.id,
            "responsible_party": "buyer",
            "completion_trigger": "Candidate buyer passes KEVO's compliance rule evaluation (M13)",
            "determinability": compliance_determinability,
            "reasons": "Buyer " + str(candidate_buyer.id) + " compliance status: " + compliance_status + " - " + compliance_result["explanation"],
            "source_milestone": "M13"
        })

    interest_match_count = db.query(BuyerInterest).filter(
        BuyerInterest.company == listing.company,
        BuyerInterest.asset_type == listing.asset_type,
        BuyerInterest.status == "active",
        BuyerInterest.maximum_price >= listing.asking_price,
        BuyerInterest.desired_quantity <= listing.quantity
    ).count()

    matching_complete = interest_match_count > 0

    steps.append({
        "step_type": "BUYER_MATCHING",
        "sequence_position": 6,
        "required": True,
        "complete": matching_complete,
        "evidence_reference_type": "BuyerInterest",
        "evidence_reference_id": None,
        "responsible_party": "kevo",
        "completion_trigger": "At least one buyer interest matching this listing's terms exists",
        "determinability": "known_complete" if matching_complete else "known_incomplete",
        "reasons": str(interest_match_count) + " buyer interest(s) currently match this listing's company, asset type, price, and quantity",
        "source_milestone": "M9-M11"
    })

    if transaction is not None and transaction.status in ("accepted", "settlement_pending", "completed"):
        steps.append({
            "step_type": "NEGOTIATION_PRICE_AGREEMENT",
            "sequence_position": 7,
            "required": True,
            "complete": True,
            "evidence_reference_type": "Transaction",
            "evidence_reference_id": transaction.id,
            "responsible_party": "holder",
            "completion_trigger": "Already resolved by an existing transaction record",
            "determinability": "known_complete",
            "reasons": "Transaction " + str(transaction.id) + " has status '" + transaction.status + "' with an agreed price of " + str(transaction.agreed_price),
            "source_milestone": "Transaction table (built); M25 added ROFR consent only, negotiation workflow unbuilt"
        })
    elif transaction is not None:
        steps.append({
            "step_type": "NEGOTIATION_PRICE_AGREEMENT",
            "sequence_position": 7,
            "required": True,
            "complete": False,
            "evidence_reference_type": "Transaction",
            "evidence_reference_id": transaction.id,
            "responsible_party": "holder",
            "completion_trigger": "Holder and buyer agree a price, recorded as a Transaction",
            "determinability": "known_incomplete",
            "reasons": "Transaction " + str(transaction.id) + "'s current status is '" + transaction.status + "' — this does not represent an agreed price",
            "source_milestone": "Transaction table (built); M25 added ROFR consent only, negotiation workflow unbuilt"
        })
    else:
        steps.append({
            "step_type": "NEGOTIATION_PRICE_AGREEMENT",
            "sequence_position": 7,
            "required": True,
            "complete": False,
            "evidence_reference_type": None,
            "evidence_reference_id": None,
            "responsible_party": "holder",
            "completion_trigger": "Holder and buyer agree a price, recorded as a Transaction",
            "determinability": "known_incomplete",
            "reasons": "No transaction record exists for this listing yet — no negotiation has taken place",
            "source_milestone": "Transaction table (built); M25 added ROFR consent only, negotiation workflow unbuilt"
        })

    settlement_record = None
    if transaction is not None:
        settlement_record = db.query(SettlementRecord).filter(
            SettlementRecord.transaction_id == transaction.id
        ).first()

    if settlement_record is not None and settlement_record.funds_received and settlement_record.shares_confirmed_transferable:
        settlement_complete = True
        settlement_determinability = "known_complete"
        settlement_reasons = "Settlement record " + str(settlement_record.id) + " confirms both funds received and shares confirmed transferable"
    elif settlement_record is not None:
        settlement_complete = False
        settlement_determinability = "known_incomplete"
        settlement_reasons = "Settlement record " + str(settlement_record.id) + " exists with status '" + settlement_record.status + "' but funds and/or shares confirmation is still incomplete"
    elif transaction is not None:
        settlement_complete = False
        settlement_determinability = "known_incomplete"
        settlement_reasons = "Transaction " + str(transaction.id) + " exists but settlement tracking has not begun yet (no SettlementRecord created)"
    else:
        settlement_complete = False
        settlement_determinability = "cannot_determine"
        settlement_reasons = "No transaction exists for this listing yet, so settlement cannot begin"

    steps.append({
        "step_type": "SETTLEMENT",
        "sequence_position": 8,
        "required": True,
        "complete": settlement_complete,
        "evidence_reference_type": "SettlementRecord" if settlement_record is not None else None,
        "evidence_reference_id": settlement_record.id if settlement_record is not None else None,
        "responsible_party": "third_party",
        "completion_trigger": "Admin confirms (on the licensed escrow provider's behalf) that funds have been received and shares are confirmed transferable",
        "determinability": settlement_determinability,
        "reasons": settlement_reasons,
        "source_milestone": "M26 first slice (settlement status tracking, orchestration-only; KEVO never holds funds itself)"
    })

    if settlement_record is not None and settlement_record.funds_released:
        cash_release_complete = True
        cash_release_determinability = "known_complete"
        cash_release_reasons = "Settlement record " + str(settlement_record.id) + " confirms funds have been released"
    elif settlement_record is not None:
        cash_release_complete = False
        cash_release_determinability = "known_incomplete"
        cash_release_reasons = "Settlement record " + str(settlement_record.id) + " exists but funds have not been released yet"
    elif transaction is not None:
        cash_release_complete = False
        cash_release_determinability = "known_incomplete"
        cash_release_reasons = "Transaction " + str(transaction.id) + " exists but settlement tracking has not begun yet (no SettlementRecord created)"
    else:
        cash_release_complete = False
        cash_release_determinability = "cannot_determine"
        cash_release_reasons = "No transaction exists for this listing yet, so settlement cannot begin"

    steps.append({
        "step_type": "CASH_RELEASE",
        "sequence_position": 9,
        "required": True,
        "complete": cash_release_complete,
        "evidence_reference_type": "SettlementRecord" if settlement_record is not None else None,
        "evidence_reference_id": settlement_record.id if settlement_record is not None else None,
        "responsible_party": "third_party",
        "completion_trigger": "Admin confirms (on the licensed escrow provider's behalf) that funds have been released",
        "determinability": cash_release_determinability,
        "reasons": cash_release_reasons,
        "source_milestone": "M26 first slice (settlement status tracking, orchestration-only; KEVO never holds funds itself)"
    })

    return {
        "ownership_record_id": ownership_record.id if ownership_record else None,
        "steps": steps
    }


@app.get("/liquidity-path/listing/{listing_id}")
def get_liquidity_path(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    result = build_liquidity_path(listing, db)
    ownership_record_id = result["ownership_record_id"]
    run_id = uuid.uuid4().hex
    computed_at = date.today()

    saved_steps = []
    previous_step_id = None

    for step in result["steps"]:
        row = LiquidityPathStep(
            listing_id=listing.id,
            ownership_record_id=ownership_record_id,
            transaction_id=None,
            run_id=run_id,
            computed_at=computed_at,
            step_type=step["step_type"],
            sequence_position=step["sequence_position"],
            required=step["required"],
            complete=step["complete"],
            evidence_reference_type=step["evidence_reference_type"],
            evidence_reference_id=step["evidence_reference_id"],
            responsible_party=step["responsible_party"],
            blocking_step_id=previous_step_id,
            completion_trigger=step["completion_trigger"],
            determinability=step["determinability"],
            reasons=step["reasons"],
            source_milestone=step["source_milestone"]
        )
        db.add(row)
        db.flush()
        previous_step_id = row.id
        saved_steps.append(row)

    db.commit()

    complete_count = sum(1 for s in saved_steps if s.complete)
    cannot_determine_count = sum(1 for s in saved_steps if s.determinability == "cannot_determine")

    return {
        "listing_id": listing.id,
        "run_id": run_id,
        "computed_at": computed_at,
        "summary": str(complete_count) + " of " + str(len(saved_steps)) + " steps confirmed complete; " + str(cannot_determine_count) + " step(s) cannot currently be determined",
        "steps": [
            {
                "id": s.id,
                "step_type": s.step_type,
                "sequence_position": s.sequence_position,
                "required": s.required,
                "complete": s.complete,
                "evidence_reference_type": s.evidence_reference_type,
                "evidence_reference_id": s.evidence_reference_id,
                "responsible_party": s.responsible_party,
                "blocking_step_id": s.blocking_step_id,
                "completion_trigger": s.completion_trigger,
                "determinability": s.determinability,
                "reasons": s.reasons,
                "source_milestone": s.source_milestone
            }
            for s in saved_steps
        ]
    }


# ---------------------------------------------------------------------------
# M17 (first slice) — Transaction-scoped Liquidity Roadmap
# Reuses build_liquidity_path() exactly as M15 does, just scoped to one
# specific transaction (a deal) instead of always using the listing's
# latest transaction. No new step-evaluation logic - same engine, just a
# different caller, per the original M15/M17 design note.
# ---------------------------------------------------------------------------

@app.get("/liquidity-path/transaction/{transaction_id}")
def get_liquidity_path_for_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )

    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(
            status_code=403,
            detail="You are not a party to this transaction"
        )

    listing = db.query(ListingModel).filter(
        ListingModel.id == transaction.listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found for this transaction"
        )

    result = build_liquidity_path(listing, db, transaction_id=transaction.id)
    ownership_record_id = result["ownership_record_id"]
    run_id = uuid.uuid4().hex
    computed_at = date.today()

    saved_steps = []
    previous_step_id = None

    for step in result["steps"]:
        row = LiquidityPathStep(
            listing_id=listing.id,
            ownership_record_id=ownership_record_id,
            transaction_id=transaction.id,
            run_id=run_id,
            computed_at=computed_at,
            step_type=step["step_type"],
            sequence_position=step["sequence_position"],
            required=step["required"],
            complete=step["complete"],
            evidence_reference_type=step["evidence_reference_type"],
            evidence_reference_id=step["evidence_reference_id"],
            responsible_party=step["responsible_party"],
            blocking_step_id=previous_step_id,
            completion_trigger=step["completion_trigger"],
            determinability=step["determinability"],
            reasons=step["reasons"],
            source_milestone=step["source_milestone"]
        )
        db.add(row)
        db.flush()
        previous_step_id = row.id
        saved_steps.append(row)

    db.commit()

    complete_count = sum(1 for s in saved_steps if s.complete)
    cannot_determine_count = sum(1 for s in saved_steps if s.determinability == "cannot_determine")

    return {
        "transaction_id": transaction.id,
        "listing_id": listing.id,
        "run_id": run_id,
        "computed_at": computed_at,
        "summary": str(complete_count) + " of " + str(len(saved_steps)) + " steps confirmed complete; " + str(cannot_determine_count) + " step(s) cannot currently be determined",
        "steps": [
            {
                "id": s.id,
                "step_type": s.step_type,
                "sequence_position": s.sequence_position,
                "required": s.required,
                "complete": s.complete,
                "evidence_reference_type": s.evidence_reference_type,
                "evidence_reference_id": s.evidence_reference_id,
                "responsible_party": s.responsible_party,
                "blocking_step_id": s.blocking_step_id,
                "completion_trigger": s.completion_trigger,
                "determinability": s.determinability,
                "reasons": s.reasons,
                "source_milestone": s.source_milestone
            }
            for s in saved_steps
        ]
    }


# ---------------------------------------------------------------------------
# M15/M16 Part 4 audit (2026-09-12) - Portfolio Liquidity
# Extends M15's build_liquidity_path() across a seller's entire portfolio of
# listings - no new step-evaluation logic, same engine, just a different
# caller (same "presenter, not reimplementation" pattern as M17's Liquidity
# Roadmap above). Confirmed via real-database audit that this does NOT
# depend on transaction/settlement history the way Discount-for-Speed and
# the general price-range engine do (both remain deferred) - it only needs
# a seller who holds more than one listing, which the real data already
# has. Live-computed, nothing persisted, same posture as Deal Health Score
# and Risk Radar below (a portfolio dashboard viewed repeatedly should not
# multiply audit-trail rows the way the single-listing GET intentionally
# does).
# ---------------------------------------------------------------------------

def build_portfolio_liquidity(seller_id, db):
    listings = db.query(ListingModel).filter(
        ListingModel.seller_id == seller_id
    ).all()

    listing_results = []
    next_blocking_step_counts = {}
    listings_fully_complete = 0

    for listing in listings:
        result = build_liquidity_path(listing, db)
        steps = result["steps"]

        complete_count = sum(1 for s in steps if s["complete"])
        cannot_determine_count = sum(1 for s in steps if s["determinability"] == "cannot_determine")

        next_blocker = None
        for step in sorted(steps, key=lambda s: s["sequence_position"]):
            if step["required"] and not step["complete"]:
                next_blocker = step
                break

        if next_blocker is None:
            listings_fully_complete += 1
        else:
            step_type = next_blocker["step_type"]
            next_blocking_step_counts[step_type] = next_blocking_step_counts.get(step_type, 0) + 1

        listing_results.append({
            "listing_id": listing.id,
            "company": listing.company,
            "asset_type": listing.asset_type,
            "summary": str(complete_count) + " of " + str(len(steps)) + " steps confirmed complete; " + str(cannot_determine_count) + " step(s) cannot currently be determined",
            "complete_count": complete_count,
            "total_steps": len(steps),
            "cannot_determine_count": cannot_determine_count,
            "steps": steps
        })

    return {
        "seller_id": seller_id,
        "listing_count": len(listings),
        "listings_fully_complete": listings_fully_complete,
        "next_blocking_step_counts": next_blocking_step_counts,
        "listings": listing_results
    }


@app.get("/portfolio-liquidity/seller/{seller_id}")
def get_portfolio_liquidity(
    seller_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    seller = db.query(UserModel).filter(UserModel.id == seller_id).first()

    if seller is None:
        raise HTTPException(
            status_code=404,
            detail="Seller not found"
        )

    return build_portfolio_liquidity(seller_id, db)


# ---------------------------------------------------------------------------
# M17 (second slice) — Deal Health Score
# A breakdown-only readout across six real, already-built sources. No
# invented weighting, no composite number - a dimension either has a real
# status or is honestly marked "cannot_determine". Nothing is persisted;
# recomputed live on every call, same pattern as assess_compliance() and
# evaluate_transferability().
# ---------------------------------------------------------------------------

def build_deal_health(transaction, db):
    dimensions = []

    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
    listing = db.query(ListingModel).filter(ListingModel.id == transaction.listing_id).first()

    # 1. Compliance - real assess_compliance() verdict
    compliance_result = assess_compliance(buyer, listing, db)
    dimensions.append({
        "dimension": "compliance",
        "determinable": True,
        "status": compliance_result["status"],
        "reason": compliance_result["explanation"]
    })

    # 2. Buyer readiness - the buyer's real KYC status
    dimensions.append({
        "dimension": "buyer_readiness",
        "determinable": True,
        "status": buyer.kyc_status,
        "reason": "Buyer's real KYC status on file is '" + str(buyer.kyc_status) + "'"
    })

    # 3. Ownership - real verification status of ownership record(s) for this listing
    ownership_records = db.query(OwnershipRecord).filter(
        OwnershipRecord.listing_id == listing.id
    ).all()

    if len(ownership_records) == 0:
        dimensions.append({
            "dimension": "ownership",
            "determinable": False,
            "status": "cannot_determine",
            "reason": "No ownership record on file for this listing"
        })
    else:
        unverified = [r for r in ownership_records if r.verification_status != "verified"]
        if len(unverified) > 0:
            dimensions.append({
                "dimension": "ownership",
                "determinable": True,
                "status": "pending",
                "reason": str(len(unverified)) + " of " + str(len(ownership_records)) + " ownership record(s) for this listing are not yet verified"
            })
        else:
            dimensions.append({
                "dimension": "ownership",
                "determinable": True,
                "status": "verified",
                "reason": "All " + str(len(ownership_records)) + " ownership record(s) for this listing are verified"
            })

    # 4. Settlement readiness - the transaction's own real status
    settlement_map = {
        "completed": "ready",
        "settlement_pending": "in_progress",
        "accepted": "in_progress",
        "interested": "not_yet_committed",
        "rejected": "not_ready",
        "cancelled": "not_ready"
    }
    settlement_status = settlement_map.get(transaction.status, "cannot_determine")
    dimensions.append({
        "dimension": "settlement_readiness",
        "determinable": True,
        "status": settlement_status,
        "reason": "Transaction's real status is '" + str(transaction.status) + "'"
    })

    # 5. Regulatory uncertainty - live transferability evaluation for this listing
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
        })

    # 6. Documentation - real evidence rows tied to this transaction
    evidence_rows = db.query(Evidence).filter(
        Evidence.transaction_id == transaction.id
    ).all()

    if len(evidence_rows) == 0:
        dimensions.append({
            "dimension": "documentation",
            "determinable": False,
            "status": "cannot_determine",
            "reason": "No evidence has been collected for this transaction yet"
        })
    else:
        unverified_evidence = [e for e in evidence_rows if e.verification_status != "verified"]
        if len(unverified_evidence) > 0:
            dimensions.append({
                "dimension": "documentation",
                "determinable": True,
                "status": "pending",
                "reason": str(len(unverified_evidence)) + " of " + str(len(evidence_rows)) + " evidence record(s) are not yet verified"
            })
        else:
            dimensions.append({
                "dimension": "documentation",
                "determinable": True,
                "status": "verified",
                "reason": "All " + str(len(evidence_rows)) + " evidence record(s) are verified"
            })

    determinable_dimensions = [d for d in dimensions if d["determinable"]]
    cannot_determine_dimensions = [d for d in dimensions if not d["determinable"]]

    healthy_statuses = {"eligible_pending_review", "eligible", "verified", "ready", "in_progress"}
    healthy_count = sum(1 for d in determinable_dimensions if d["status"] in healthy_statuses)

    risk_priority = {
        "blocked": 0,
        "conflict": 0,
        "not_ready": 1,
        "needs_evidence": 2,
        "pending": 2,
        "not_started": 2,
        "review": 3,
        "not_yet_committed": 3,
    }

    unhealthy_determinable = [d for d in determinable_dimensions if d["status"] not in healthy_statuses]

    if len(unhealthy_determinable) > 0:
        main_risk_dim = min(unhealthy_determinable, key=lambda d: risk_priority.get(d["status"], 5))
    else:
        main_risk_dim = None

    summary = str(healthy_count) + " of " + str(len(determinable_dimensions)) + " determinable dimension(s) look healthy"
    if len(cannot_determine_dimensions) > 0:
        summary += "; " + str(len(cannot_determine_dimensions)) + " dimension(s) cannot currently be determined"

    return {
        "dimensions": dimensions,
        "summary": summary,
        "main_risk": {
            "dimension": main_risk_dim["dimension"],
            "status": main_risk_dim["status"],
            "reason": main_risk_dim["reason"]
        } if main_risk_dim is not None else None
    }


@app.get("/deal-health/transaction/{transaction_id}")
def get_deal_health(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(
            status_code=403,
            detail="You are not a party to this transaction"
        )

    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()

    if buyer is None:
        raise HTTPException(status_code=404, detail="Buyer not found for this transaction")

    listing = db.query(ListingModel).filter(
        ListingModel.id == transaction.listing_id
    ).first()

    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found for this transaction")

    result = build_deal_health(transaction, db)

    return {
        "transaction_id": transaction.id,
        "listing_id": listing.id,
        "summary": result["summary"],
        "main_risk": result["main_risk"],
        "dimensions": result["dimensions"]
    }


# ---------------------------------------------------------------------------
# M17 (third slice) — Transaction Risk Radar
# Four real, binary risk flags - each either fires on a real condition in
# the data or it doesn't. No invented severity weighting, no invented
# percentage thresholds. Nothing is persisted; recomputed live on every
# call, same pattern as build_deal_health() and assess_compliance().
# ---------------------------------------------------------------------------

def build_risk_radar(transaction, db):
    flags = []

    seller = db.query(UserModel).filter(UserModel.id == transaction.seller_id).first()
    listing = db.query(ListingModel).filter(ListingModel.id == transaction.listing_id).first()

    # 1. Seller affiliate status
    affiliate_status = seller.seller_affiliate_status
    if affiliate_status is None:
        flags.append({
            "flag_type": "seller_affiliate_status",
            "status": "flagged",
            "reason": "Seller's affiliate status has not been recorded - potential Rule 144 restriction exposure is unknown."
        })
    elif affiliate_status == "non_affiliate":
        flags.append({
            "flag_type": "seller_affiliate_status",
            "status": "clear",
            "reason": "Seller's affiliate status on file is 'non_affiliate' - no additional resale restriction exposure flagged."
        })
    else:
        flags.append({
            "flag_type": "seller_affiliate_status",
            "status": "flagged",
            "reason": "Seller's affiliate status on file is '" + str(affiliate_status) + "' - affiliate sellers may face additional resale volume/manner restrictions (Rule 144) that have not yet been evaluated."
        })

    # 2. Conflicting transferability facts (live evaluation)
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
        })

    # 3. Competing active transactions on the same listing
    competing_transactions = db.query(Transaction).filter(
        Transaction.listing_id == listing.id,
        Transaction.id != transaction.id,
        Transaction.status.in_(["interested", "accepted", "settlement_pending"])
    ).all()

    if len(competing_transactions) > 0:
        flags.append({
            "flag_type": "competing_active_transactions",
            "status": "flagged",
            "reason": str(len(competing_transactions)) + " other active transaction(s) exist on this same listing and may compete for the same quantity."
        })
    else:
        flags.append({
            "flag_type": "competing_active_transactions",
            "status": "clear",
            "reason": "No other active transactions exist on this listing."
        })

    # 4. Forecasted-but-not-yet-eligible timing (live evaluation)
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
        })

    flagged_count = sum(1 for f in flags if f["status"] == "flagged")
    summary = str(flagged_count) + " of " + str(len(flags)) + " risk flag(s) triggered for this transaction"

    return {
        "flags": flags,
        "summary": summary
    }


@app.get("/risk-radar/transaction/{transaction_id}")
def get_risk_radar(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(
            status_code=403,
            detail="You are not a party to this transaction"
        )

    seller = db.query(UserModel).filter(UserModel.id == transaction.seller_id).first()

    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found for this transaction")

    listing = db.query(ListingModel).filter(
        ListingModel.id == transaction.listing_id
    ).first()

    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found for this transaction")

    result = build_risk_radar(transaction, db)

    return {
        "transaction_id": transaction.id,
        "listing_id": listing.id,
        "summary": result["summary"],
        "flags": result["flags"]
    }


# ---------------------------------------------------------------------------
# Liquidity Friction Indicator (first slice)
# Not a price, valuation, or discount estimate - KEVO still has no real
# transaction volume to back one (unchanged since the M16 critical
# assessment). Packages what M14 (Transferability Engine) and M15
# (Liquidity Path Engine) already know about a specific listing into an
# explained illiquidity-friction readout. No competitor researched
# (Hiive, Forge, Caplight, NPM) structures legal/procedural friction into
# pricing at the position level - this data already exists in KEVO, built
# for compliance reasons, never packaged as a market-facing signal before.
# Nothing persisted; recomputed live on every call, same pattern as
# build_deal_health() and build_risk_radar().
# ---------------------------------------------------------------------------

def build_liquidity_friction_profile(listing, db):
    transferability_result = evaluate_transferability(listing, db)
    path_result = build_liquidity_path(listing, db)
    steps = path_result["steps"]

    breakdown = {
        "known_complete": 0,
        "known_incomplete": 0,
        "required_but_unverified": 0,
        "cannot_determine": 0
    }
    for step in steps:
        determinability = step["determinability"]
        if determinability in breakdown:
            breakdown[determinability] += 1

    rofr_step = None
    for step in steps:
        if step["step_type"] == "ISSUER_APPROVAL_ROFR":
            rofr_step = step

    main_constraint = None
    main_constraint_reason = None

    if transferability_result["status"] == "blocked":
        main_constraint = "legal_transferability"
        main_constraint_reason = "; ".join(transferability_result["reasons"])
    elif rofr_step is not None and rofr_step["determinability"] in ("required_but_unverified", "known_incomplete"):
        main_constraint = "rofr_consent"
        main_constraint_reason = rofr_step["reasons"]
    elif transferability_result["status"] in ("needs_evidence", "review", "conflict"):
        main_constraint = "legal_transferability"
        main_constraint_reason = "; ".join(transferability_result["reasons"])
    else:
        unresolved_steps = [
            s for s in steps
            if s["determinability"] in ("known_incomplete", "required_but_unverified")
        ]
        if unresolved_steps:
            unresolved_steps.sort(key=lambda s: s["sequence_position"])
            main_constraint = unresolved_steps[0]["step_type"]
            main_constraint_reason = unresolved_steps[0]["reasons"]

    summary = (
        str(breakdown["known_complete"]) + " of " + str(len(steps)) +
        " liquidity-path steps confirmed complete; " +
        str(breakdown["required_but_unverified"]) + " required but unverified; " +
        str(breakdown["known_incomplete"]) + " known incomplete; " +
        str(breakdown["cannot_determine"]) + " cannot currently be determined"
    )

    return {
        "summary": summary,
        "steps_breakdown": breakdown,
        "main_constraint": main_constraint,
        "main_constraint_reason": main_constraint_reason,
        "transferability": {
            "status": transferability_result["status"],
            "explanation": "; ".join(transferability_result["reasons"]),
            "path_to_eligibility": transferability_result["path_to_eligibility"],
            "forecast_date": transferability_result["forecast_date"]
        },
        "rofr": {
            "determinability": rofr_step["determinability"] if rofr_step else "cannot_determine",
            "complete": rofr_step["complete"] if rofr_step else False,
            "reasons": rofr_step["reasons"] if rofr_step else "ROFR step not available"
        },
        "steps": steps,
        "disclaimer": "This is not a price, valuation, or discount estimate. It describes how much legal and procedural friction currently stands between this listing and a completed sale, based on KEVO's own transferability and liquidity-path data. Recomputed fresh on every request, not a stored quote."
    }


@app.get("/liquidity-friction/listing/{listing_id}")
def get_liquidity_friction(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    listing = db.query(ListingModel).filter(
        ListingModel.id == listing_id
    ).first()

    if listing is None:
        raise HTTPException(
            status_code=404,
            detail="Listing not found"
        )

    result = build_liquidity_friction_profile(listing, db)

    return {
        "listing_id": listing.id,
        "summary": result["summary"],
        "steps_breakdown": result["steps_breakdown"],
        "main_constraint": result["main_constraint"],
        "main_constraint_reason": result["main_constraint_reason"],
        "transferability": result["transferability"],
        "rofr": result["rofr"],
        "steps": result["steps"],
        "disclaimer": result["disclaimer"]
    }


# ---------------------------------------------------------------------------
# M24 (first slice) — KEVO Deal Room
# A read-only aggregator over data that already exists elsewhere in the
# API - participants, the live compliance verdict, ownership status,
# evidence documents linked to this specific transaction (M23), and the
# M17 trio (Deal Health Score, Risk Radar, Liquidity Roadmap) - presented
# as one authorized view instead of five separate calls. No new tables,
# nothing persisted here (the roadmap piece calls build_liquidity_path()
# directly rather than the archiving /liquidity-path/transaction/{id}
# endpoint, so this call has no side effects, same as deal-health and
# risk-radar). Messages, negotiation, ROFR workflow, approvals,
# settlement, and audit trail are explicitly out of scope for this slice
# - each is its own future milestone (M25/M26/M27) with no real
# implementation yet to aggregate.
# ---------------------------------------------------------------------------

@app.get("/deal-room/transaction/{transaction_id}")
def get_deal_room(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(
            status_code=403,
            detail="You are not a party to this transaction"
        )

    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
    seller = db.query(UserModel).filter(UserModel.id == transaction.seller_id).first()

    if buyer is None or seller is None:
        raise HTTPException(status_code=404, detail="Buyer or seller not found for this transaction")

    listing = db.query(ListingModel).filter(
        ListingModel.id == transaction.listing_id
    ).first()

    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found for this transaction")

    compliance_result = assess_compliance(buyer, listing, db)

    ownership_records = db.query(OwnershipRecord).filter(
        OwnershipRecord.listing_id == listing.id
    ).all()
    ownership_summary = {
        "records_on_file": len(ownership_records),
        "all_verified": len(ownership_records) > 0 and all(
            r.verification_status == "verified" for r in ownership_records
        )
    }

    evidence_rows = db.query(Evidence).filter(
        Evidence.transaction_id == transaction.id
    ).all()
    documents = [
        {
            "id": e.id,
            "evidence_type": e.evidence_type,
            "description": e.description,
            "verification_status": e.verification_status,
            "file_reference": e.file_reference,
            "file_hash": e.file_hash
        }
        for e in evidence_rows
    ]

    deal_health = build_deal_health(transaction, db)
    risk_radar = build_risk_radar(transaction, db)
    liquidity_path = build_liquidity_path(listing, db, transaction_id=transaction.id)

    return {
        "transaction": {
            "id": transaction.id,
            "listing_id": transaction.listing_id,
            "quantity": transaction.quantity,
            "agreed_price": transaction.agreed_price,
            "status": transaction.status,
            "settlement_currency": transaction.settlement_currency
        },
        "participants": {
            "buyer": {"id": buyer.id, "role": buyer.role},
            "seller": {"id": seller.id, "role": seller.role}
        },
        "compliance": {
            "status": compliance_result["status"],
            "explanation": compliance_result["explanation"]
        },
        "ownership": ownership_summary,
        "documents": documents,
        "deal_health": {
            "summary": deal_health["summary"],
            "main_risk": deal_health["main_risk"],
            "dimensions": deal_health["dimensions"]
        },
        "risk_radar": {
            "summary": risk_radar["summary"],
            "flags": risk_radar["flags"]
        },
        "liquidity_roadmap": {
            "steps": liquidity_path["steps"]
        }
    }


# ---------------------------------------------------------------------------
# M25 (first slice) -- Right of First Refusal (ROFR): consent request + response log
#
# Deliberately NOT deadline-driven: no jurisdiction has a real, sourced ROFR
# response-window on file. TransferabilityRule.hold_period_days means
# something different (days held before sale is legally permitted, not days
# to respond to a ROFR notice) and is empty for the one real ROFR rule that
# exists (ZA-COMPANIES-S8-ROFR-CONSENT). Also deliberately avoids an
# auto-triggered countdown -- the specific mechanism flagged as
# patent-adjacent in claude/kevo-m25-rofr-patent-claim-analysis.md
# (Nasdaq Private Market US 12,572,980).
#
# KEVO has no "issuer" or "existing shareholder" user concept yet, so this
# follows the same self-submit/admin-verify pattern already used for
# Evidence, KYCFact, and OwnershipRecord: the seller (who actually needs the
# consent) submits the request; only an admin records the real-world
# response.
# ---------------------------------------------------------------------------

class RofrRequestCreate(BaseModel):
    transaction_id: int
    transferability_rule_id: int
    source_reference: str | None = None


@app.post("/rofr-requests")
def create_rofr_request(
    payload: RofrRequestCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(Transaction.id == payload.transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if current_user.account_type != "admin" and current_user.id != transaction.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller or an admin can submit a ROFR request for this transaction")
    rule = db.query(TransferabilityRule).filter(TransferabilityRule.id == payload.transferability_rule_id).first()
    if rule is None:
        raise HTTPException(status_code=404, detail="Transferability rule not found")
    listing = db.query(ListingModel).filter(ListingModel.id == transaction.listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found for this transaction")
    applicable_rules = find_applicable_transferability_rules(listing, db)
    if rule.id not in [r.id for r in applicable_rules]:
        raise HTTPException(status_code=400, detail="This transferability rule does not apply to this transaction's listing")
    response_due_date = None
    if rule.rofr_response_window_days is not None:
        response_due_date = date.today() + timedelta(days=rule.rofr_response_window_days)
    rofr_request = RofrRequest(
        transaction_id=transaction.id,
        transferability_rule_id=rule.id,
        status="pending",
        source_reference=payload.source_reference,
        response_due_date=response_due_date
    )
    db.add(rofr_request)
    db.commit()
    db.refresh(rofr_request)
    return rofr_request


@app.put("/rofr-requests/{rofr_request_id}/respond")
def respond_to_rofr_request(
    rofr_request_id: int,
    status: str,
    response_notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can record a ROFR response")
    rofr_request = db.query(RofrRequest).filter(RofrRequest.id == rofr_request_id).first()
    if rofr_request is None:
        raise HTTPException(status_code=404, detail="ROFR request not found")
    if status not in ("approved", "waived", "exercised"):
        raise HTTPException(status_code=400, detail="status must be one of: approved, waived, exercised")
    rofr_request.status = status
    rofr_request.response_notes = response_notes
    rofr_request.responded_at = datetime.utcnow()
    db.commit()
    db.refresh(rofr_request)
    return rofr_request


@app.get("/rofr-requests")
def get_rofr_requests(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        return db.query(RofrRequest).all()
    own_transaction_ids = [
        t.id for t in db.query(Transaction).filter(
            (Transaction.buyer_id == current_user.id) | (Transaction.seller_id == current_user.id)
        ).all()
    ]
    return db.query(RofrRequest).filter(RofrRequest.transaction_id.in_(own_transaction_ids)).all()


@app.get("/rofr-requests/{rofr_request_id}")
def get_rofr_request(
    rofr_request_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    rofr_request = db.query(RofrRequest).filter(RofrRequest.id == rofr_request_id).first()
    if rofr_request is None:
        raise HTTPException(status_code=404, detail="ROFR request not found")
    transaction = db.query(Transaction).filter(Transaction.id == rofr_request.transaction_id).first()
    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(status_code=403, detail="You are not a party to this transaction")
    return rofr_request


# ---------------------------------------------------------------------------
# M26 (first slice) -- Settlement status tracking, orchestration-only
#
# KEVO never holds client funds or acts as custodian -- that would create
# real money-transmitter and (per the California DFPI Escrow Law example
# already researched, see claude/kevo-automation-first-features-assessment.md)
# potentially state escrow-licensing exposure. This tracks the real-world
# confirmations a licensed escrow/bank provider would report once KEVO
# integrates with one -- it does not move money itself.
#
# Every field is admin-recorded, because until a real provider integration
# exists, these are facts only KEVO's own team can attest to -- a buyer or
# seller can never self-declare "funds received." Release is deliberately
# sequential, not atomic: funds can only be released once both conditions
# (funds received AND shares confirmed transferable) are independently
# confirmed true. True delivery-versus-payment is M26E's scope, built on
# top of this table, not this first slice's.
# ---------------------------------------------------------------------------

@app.post("/settlement-records")
def create_settlement_record(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can begin settlement tracking for a transaction")
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.status != "accepted":
        raise HTTPException(status_code=400, detail="Transaction must be in 'accepted' status to begin settlement")

    existing = db.query(SettlementRecord).filter(SettlementRecord.transaction_id == transaction_id).first()
    settlement_record = None
    if existing is not None:
        if existing.status == "escrow_creation_unconfirmed":
            raise HTTPException(
                status_code=409,
                detail="A previous attempt to create this settlement's escrow transaction did not confirm "
                       "success. An admin must resolve it via PUT /settlement-records/{id}/resolve-unconfirmed-creation "
                       "before retrying, to avoid creating a duplicate transaction on Escrow.com."
            )
        if existing.status != "escrow_creation_abandoned":
            raise HTTPException(status_code=400, detail="A settlement record already exists for this transaction")
        # Previously marked abandoned by an admin who confirmed directly with
        # Escrow.com that no transaction was actually created - safe to reuse
        # this row for a fresh attempt (transaction_id is unique, so we
        # update in place rather than inserting a second row).
        settlement_record = existing

    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
    seller = db.query(UserModel).filter(UserModel.id == transaction.seller_id).first()
    if buyer is None or seller is None:
        raise HTTPException(status_code=400, detail="Transaction is missing a buyer or seller account")

    try:
        escrow_txn = escrow_client.create_transaction(
            buyer_email=buyer.email,
            seller_email=seller.email,
            amount=float(transaction.agreed_price),
            currency=transaction.settlement_currency,
            description=f"KEVO transaction #{transaction.id}"
        )
    except Exception as exc:
        # We can't tell whether Escrow.com actually created the transaction
        # before this failure (e.g. a timeout waiting on their response), so
        # this is never just an error we forget about. A persistent record
        # is kept so a blind retry can't create a duplicate transaction on
        # Escrow.com; an admin must manually verify and resolve it.
        if settlement_record is None:
            settlement_record = SettlementRecord(transaction_id=transaction_id)
            db.add(settlement_record)
        settlement_record.status = "escrow_creation_unconfirmed"
        settlement_record.escrow_provider_reference = None
        settlement_record.notes = (
            f"Escrow.com transaction creation did not confirm success: {exc}. "
            "An admin must verify directly with Escrow.com whether a transaction "
            "was actually created before this can be retried."
        )
        db.commit()
        raise HTTPException(
            status_code=502,
            detail="Could not confirm the escrow transaction was created - this settlement now needs manual "
                   "admin reconciliation (see notes) before it can be retried"
        )

    # Escrow.com may not yet allow KEVO to auto-agree on a party's behalf
    # (a partner permission that has to be individually granted). When
    # that happens, this does not block settlement - it falls back to
    # capturing that party's own one-click agree link from Escrow.com so
    # the deal can still proceed. Once the permission is granted, this
    # fallback simply stops being needed.
    unagreed_emails = []
    for party_email in (buyer.email, seller.email):
        try:
            escrow_client.agree_as_customer(escrow_txn["id"], party_email)
        except Exception:
            unagreed_emails.append(party_email)
    notes_text = None
    if unagreed_emails:
        try:
            refreshed = escrow_client.get_transaction(escrow_txn["id"])
            links = [
                f"{party.get('customer')}: {party.get('next_step')}"
                for party in refreshed.get("parties", [])
                if party.get("customer") in unagreed_emails and party.get("next_step")
            ]
        except Exception:
            links = []
        if links:
            notes_text = "Awaiting manual agreement on Escrow.com - " + " | ".join(links)
        else:
            notes_text = "Awaiting manual agreement on Escrow.com for: " + ", ".join(unagreed_emails)

    if settlement_record is None:
        settlement_record = SettlementRecord(transaction_id=transaction_id)
        db.add(settlement_record)
    settlement_record.status = "pending"
    settlement_record.escrow_provider_reference = str(escrow_txn["id"])
    settlement_record.notes = notes_text
    transaction.status = "settlement_pending"
    db.commit()
    db.refresh(settlement_record)
    return settlement_record


@app.put("/settlement-records/{settlement_record_id}/resolve-unconfirmed-creation")
def resolve_unconfirmed_escrow_creation(
    settlement_record_id: int,
    escrow_provider_reference: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can resolve an unconfirmed escrow creation")
    settlement_record = db.query(SettlementRecord).filter(SettlementRecord.id == settlement_record_id).first()
    if settlement_record is None:
        raise HTTPException(status_code=404, detail="Settlement record not found")
    if settlement_record.status != "escrow_creation_unconfirmed":
        raise HTTPException(status_code=400, detail="This settlement record is not in an unconfirmed state")

    if escrow_provider_reference:
        # Admin checked Escrow.com directly and confirmed the transaction
        # WAS actually created - attach the real reference and let this
        # settlement proceed through the normal flow.
        settlement_record.escrow_provider_reference = escrow_provider_reference
        settlement_record.status = "pending"
        settlement_record.notes = (settlement_record.notes or "") + " | Resolved: confirmed created on Escrow.com."
        transaction = db.query(Transaction).filter(Transaction.id == settlement_record.transaction_id).first()
        if transaction is not None:
            transaction.status = "settlement_pending"
    else:
        # Admin checked Escrow.com directly and confirmed NO transaction was
        # actually created - safe to retry. The record is never deleted
        # (audit trail preserved); it's marked abandoned so a fresh
        # POST /settlement-records can reuse it cleanly.
        settlement_record.status = "escrow_creation_abandoned"
        settlement_record.notes = (settlement_record.notes or "") + " | Resolved: confirmed NOT created on Escrow.com, safe to retry."

    db.commit()
    db.refresh(settlement_record)
    return settlement_record


def _maybe_start_escrow_release_countdown(settlement_record, db):
    """
    M26E - once both funds_received and shares_confirmed_transferable are
    true, tell Escrow.com the item has been shipped and received. That
    starts their inspection-period countdown, which auto-releases funds
    to the seller once it lapses - KEVO cannot trigger that final release
    directly (Escrow.com restricts it to the buyer's own login), so this
    countdown is what stands in for an instant release.
    """
    if not (settlement_record.funds_received and settlement_record.shares_confirmed_transferable):
        return
    if settlement_record.escrow_release_initiated:
        return
    if not settlement_record.escrow_provider_reference:
        return
    transaction = db.query(Transaction).filter(Transaction.id == settlement_record.transaction_id).first()
    if transaction is None:
        return
    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
    seller = db.query(UserModel).filter(UserModel.id == transaction.seller_id).first()
    if buyer is None or seller is None:
        return
    escrow_client.mark_shipped(settlement_record.escrow_provider_reference, seller.email)
    escrow_client.mark_received(settlement_record.escrow_provider_reference, buyer.email)
    settlement_record.escrow_release_initiated = True
    db.commit()


@app.put("/settlement-records/{settlement_record_id}/confirm-funds-received")
def confirm_funds_received(
    settlement_record_id: int,
    escrow_provider_reference: str | None = None,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can confirm funds received")
    settlement_record = db.query(SettlementRecord).filter(SettlementRecord.id == settlement_record_id).first()
    if settlement_record is None:
        raise HTTPException(status_code=404, detail="Settlement record not found")
    settlement_record.funds_received = True
    settlement_record.funds_received_at = datetime.utcnow()
    if escrow_provider_reference is not None:
        settlement_record.escrow_provider_reference = escrow_provider_reference
    if notes is not None:
        settlement_record.notes = notes
    if settlement_record.status == "pending":
        settlement_record.status = "in_progress"
    db.commit()
    _maybe_start_escrow_release_countdown(settlement_record, db)
    db.refresh(settlement_record)
    return settlement_record


@app.put("/settlement-records/{settlement_record_id}/confirm-shares-transferable")
def confirm_shares_transferable(
    settlement_record_id: int,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can confirm shares are transferable")
    settlement_record = db.query(SettlementRecord).filter(SettlementRecord.id == settlement_record_id).first()
    if settlement_record is None:
        raise HTTPException(status_code=404, detail="Settlement record not found")
    settlement_record.shares_confirmed_transferable = True
    settlement_record.shares_confirmed_transferable_at = datetime.utcnow()
    if notes is not None:
        settlement_record.notes = notes
    if settlement_record.status == "pending":
        settlement_record.status = "in_progress"
    db.commit()
    _maybe_start_escrow_release_countdown(settlement_record, db)
    db.refresh(settlement_record)
    return settlement_record


def _capture_wallet_funds_for_transaction(transaction, db):
    """
    M32 - mirrors a completed real-money settlement into the demo wallet
    system, so a transaction's buyer/seller see matching activity in
    their KEVO Funds. This is a fictional-money mirror, not the real
    settlement - real money already moved through Escrow.com by the time
    this runs, so a failure here is logged but never blocks or reverses
    the real settlement that already happened. Safe to call more than
    once for the same transaction (the wallet service's capture endpoint
    is idempotent on its own).
    """
    if transaction is None:
        return
    amount = float(transaction.quantity) * float(transaction.agreed_price)
    try:
        wallet_client.capture_lock(transaction.buyer_id, transaction.id, transaction.seller_id)
        log_audit_event(db, None, "wallet_capture_completed", target_type="transaction", target_id=transaction.id,
                         detail=f"amount={amount} currency={transaction.settlement_currency}")
        db.commit()
    except RuntimeError as e:
        log_audit_event(db, None, "wallet_capture_failed", target_type="transaction", target_id=transaction.id,
                         detail=str(e))
        db.commit()


@app.put("/settlement-records/{settlement_record_id}/release-funds")
def release_settlement_funds(
    settlement_record_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can release settlement funds")
    settlement_record = db.query(SettlementRecord).filter(SettlementRecord.id == settlement_record_id).first()
    if settlement_record is None:
        raise HTTPException(status_code=404, detail="Settlement record not found")
    if not (settlement_record.funds_received and settlement_record.shares_confirmed_transferable):
        raise HTTPException(
            status_code=400,
            detail="Cannot release funds until both funds_received and shares_confirmed_transferable are confirmed"
        )
    # M26E - KEVO cannot force a release directly (Escrow.com restricts
    # that action to the buyer's own login), so this checks whether
    # Escrow.com has actually disbursed funds yet rather than marking it
    # released on request. The normal path is the /webhooks/escrow
    # endpoint flipping this automatically once the release countdown
    # lapses; this endpoint is a manual way to sync KEVO with reality.
    if settlement_record.escrow_provider_reference:
        escrow_txn = escrow_client.get_transaction(settlement_record.escrow_provider_reference)
        disbursed = any(
            schedule_entry.get("status", {}).get("disbursed_to_beneficiary")
            for item in escrow_txn.get("items", [])
            for schedule_entry in item.get("schedule", [])
        )
        if not disbursed:
            raise HTTPException(
                status_code=400,
                detail="Escrow.com has not disbursed funds yet - the release countdown is still in progress"
            )
    settlement_record.funds_released = True
    settlement_record.funds_released_at = datetime.utcnow()
    settlement_record.status = "completed"
    transaction = db.query(Transaction).filter(Transaction.id == settlement_record.transaction_id).first()
    if transaction is not None and transaction.status == "settlement_pending":
        transaction.status = "completed"
    db.commit()
    db.refresh(settlement_record)
    if transaction is not None and transaction.status == "completed":
        _capture_wallet_funds_for_transaction(transaction, db)
    return settlement_record


@app.post("/webhooks/escrow")
def escrow_webhook(payload: dict, db: Session = Depends(get_db)):
    """
    M26E - Escrow.com calls this directly, so there is no KEVO login to
    check. Per Escrow.com's own guidance, the webhook body is never
    trusted on its own: this re-fetches the real transaction from
    Escrow.com and acts on what it actually shows, not on the payload's
    claims - a forged POST to this URL can't flip anything by itself.
    """
    transaction_id = payload.get("transaction_id")
    if transaction_id is None:
        raise HTTPException(status_code=400, detail="Missing transaction_id")
    settlement_record = db.query(SettlementRecord).filter(
        SettlementRecord.escrow_provider_reference == str(transaction_id)
    ).first()
    if settlement_record is None:
        return {"status": "ignored", "reason": "no matching settlement record"}
    try:
        escrow_txn = escrow_client.get_transaction(transaction_id)
    except Exception:
        return {"status": "ignored", "reason": "could not verify transaction with Escrow.com"}
    payment_received = any(
        schedule_entry.get("status", {}).get("payment_received")
        for item in escrow_txn.get("items", [])
        for schedule_entry in item.get("schedule", [])
    )
    disbursed = any(
        schedule_entry.get("status", {}).get("disbursed_to_beneficiary")
        for item in escrow_txn.get("items", [])
        for schedule_entry in item.get("schedule", [])
    )
    if payment_received and not settlement_record.funds_received:
        settlement_record.funds_received = True
        settlement_record.funds_received_at = datetime.utcnow()
        if settlement_record.status == "pending":
            settlement_record.status = "in_progress"
        db.commit()
        _maybe_start_escrow_release_countdown(settlement_record, db)
    if disbursed and not settlement_record.funds_released:
        settlement_record.funds_released = True
        settlement_record.funds_released_at = datetime.utcnow()
        settlement_record.status = "completed"
        transaction = db.query(Transaction).filter(Transaction.id == settlement_record.transaction_id).first()
        if transaction is not None and transaction.status == "settlement_pending":
            transaction.status = "completed"
        db.commit()
        if transaction is not None and transaction.status == "completed":
            _capture_wallet_funds_for_transaction(transaction, db)
    db.refresh(settlement_record)
    return {"status": "ok"}


@app.get("/settlement-records")
def get_settlement_records(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        return db.query(SettlementRecord).all()
    own_transaction_ids = [
        t.id for t in db.query(Transaction).filter(
            (Transaction.buyer_id == current_user.id) | (Transaction.seller_id == current_user.id)
        ).all()
    ]
    return db.query(SettlementRecord).filter(SettlementRecord.transaction_id.in_(own_transaction_ids)).all()


@app.get("/settlement-records/{settlement_record_id}")
def get_settlement_record(
    settlement_record_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    settlement_record = db.query(SettlementRecord).filter(SettlementRecord.id == settlement_record_id).first()
    if settlement_record is None:
        raise HTTPException(status_code=404, detail="Settlement record not found")
    transaction = db.query(Transaction).filter(Transaction.id == settlement_record.transaction_id).first()
    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(status_code=403, detail="You are not a party to this transaction")
    return settlement_record


# ---------------------------------------------------------------------------
# M26B — Share-Backed Lending Marketplace (first slice: broker/matcher only)
# KEVO never originates a loan, never funds one, and never takes or holds
# collateral. It tracks a holder's request to borrow against verified shares
# through to a real, licensed external lender. Matching and closing are
# admin-recorded, mirroring M26's settlement-tracking pattern.
# ---------------------------------------------------------------------------

@app.post("/loan-requests")
def create_loan_request(
    ownership_record_id: int,
    requested_amount: float,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    ownership_record = db.query(OwnershipRecord).filter(OwnershipRecord.id == ownership_record_id).first()
    if ownership_record is None:
        raise HTTPException(status_code=404, detail="Ownership record not found")
    if ownership_record.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only request a loan against your own ownership record")
    if ownership_record.verification_status != "verified":
        raise HTTPException(status_code=400, detail="Ownership record must be verified before it can back a loan request")
    if requested_amount <= 0:
        raise HTTPException(status_code=400, detail="Requested amount must be greater than zero")
    loan_request = LoanRequest(
        holder_id=current_user.id,
        ownership_record_id=ownership_record_id,
        requested_amount=requested_amount,
        status="requested",
        notes=notes
    )
    db.add(loan_request)
    db.commit()
    db.refresh(loan_request)
    return loan_request


@app.put("/loan-requests/{loan_request_id}/withdraw")
def withdraw_loan_request(
    loan_request_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    loan_request = db.query(LoanRequest).filter(LoanRequest.id == loan_request_id).first()
    if loan_request is None:
        raise HTTPException(status_code=404, detail="Loan request not found")
    if loan_request.holder_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only withdraw your own loan request")
    if loan_request.status != "requested":
        raise HTTPException(status_code=400, detail="Only a loan request still in 'requested' status can be withdrawn")
    loan_request.status = "withdrawn"
    db.commit()
    db.refresh(loan_request)
    return loan_request


@app.put("/loan-requests/{loan_request_id}/match")
def match_loan_request(
    loan_request_id: int,
    external_lender_name: str,
    external_lender_reference: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can record a match to a real external lender")
    loan_request = db.query(LoanRequest).filter(LoanRequest.id == loan_request_id).first()
    if loan_request is None:
        raise HTTPException(status_code=404, detail="Loan request not found")
    if loan_request.status != "requested":
        raise HTTPException(status_code=400, detail="Only a loan request still in 'requested' status can be matched")
    loan_request.external_lender_name = external_lender_name
    loan_request.external_lender_reference = external_lender_reference
    loan_request.matched_at = datetime.utcnow()
    loan_request.status = "matched"
    db.commit()
    db.refresh(loan_request)
    return loan_request


@app.put("/loan-requests/{loan_request_id}/decline")
def decline_loan_request(
    loan_request_id: int,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can decline a loan request")
    loan_request = db.query(LoanRequest).filter(LoanRequest.id == loan_request_id).first()
    if loan_request is None:
        raise HTTPException(status_code=404, detail="Loan request not found")
    if loan_request.status != "requested":
        raise HTTPException(status_code=400, detail="Only a loan request still in 'requested' status can be declined")
    loan_request.status = "declined"
    if notes is not None:
        loan_request.notes = notes
    db.commit()
    db.refresh(loan_request)
    return loan_request


@app.put("/loan-requests/{loan_request_id}/close")
def close_loan_request(
    loan_request_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can close a loan request")
    loan_request = db.query(LoanRequest).filter(LoanRequest.id == loan_request_id).first()
    if loan_request is None:
        raise HTTPException(status_code=404, detail="Loan request not found")
    if loan_request.status != "matched":
        raise HTTPException(status_code=400, detail="Only a matched loan request can be closed")
    loan_request.status = "closed"
    loan_request.closed_at = datetime.utcnow()
    db.commit()
    db.refresh(loan_request)
    return loan_request


@app.get("/loan-requests")
def get_loan_requests(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        loan_requests = db.query(LoanRequest).all()
    else:
        loan_requests = db.query(LoanRequest).filter(LoanRequest.holder_id == current_user.id).all()
    return loan_requests


@app.get("/loan-requests/{loan_request_id}")
def get_loan_request(
    loan_request_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    loan_request = db.query(LoanRequest).filter(LoanRequest.id == loan_request_id).first()
    if loan_request is None:
        raise HTTPException(status_code=404, detail="Loan request not found")
    if current_user.account_type != "admin" and loan_request.holder_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this loan request")
    return loan_request


# ---------------------------------------------------------------------------
# M26D — Option Exercise Funding (first slice: referral/tracking only)
# Research found this is NOT a lighter version of M26B: real providers use
# a prepaid variable forward contract (the same instrument class that got
# M25B parked) and comply with securities law via their own registered
# broker-dealer subsidiary. KEVO builds none of that here - this only
# tracks that a holder asked for a referral and was pointed at a named,
# real, already-licensed external provider. KEVO originates nothing,
# structures nothing, and holds no interest in the outcome.
# ---------------------------------------------------------------------------

@app.post("/option-funding-referrals")
def create_option_funding_referral(
    company: str,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    referral = OptionFundingReferral(
        holder_id=current_user.id,
        company=company,
        notes=notes,
        status="requested"
    )
    db.add(referral)
    db.commit()
    db.refresh(referral)
    return referral


@app.put("/option-funding-referrals/{referral_id}/withdraw")
def withdraw_option_funding_referral(
    referral_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    referral = db.query(OptionFundingReferral).filter(OptionFundingReferral.id == referral_id).first()
    if referral is None:
        raise HTTPException(status_code=404, detail="Option funding referral not found")
    if referral.holder_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only withdraw your own referral request")
    if referral.status != "requested":
        raise HTTPException(status_code=400, detail="Only a referral request still in 'requested' status can be withdrawn")
    referral.status = "withdrawn"
    db.commit()
    db.refresh(referral)
    return referral


@app.put("/option-funding-referrals/{referral_id}/refer")
def refer_option_funding_referral(
    referral_id: int,
    referred_provider_name: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can record a referral to a real external provider")
    referral = db.query(OptionFundingReferral).filter(OptionFundingReferral.id == referral_id).first()
    if referral is None:
        raise HTTPException(status_code=404, detail="Option funding referral not found")
    if referral.status != "requested":
        raise HTTPException(status_code=400, detail="Only a referral request still in 'requested' status can be referred")
    referral.referred_provider_name = referred_provider_name
    referral.referred_at = datetime.utcnow()
    referral.status = "referred"
    db.commit()
    db.refresh(referral)
    return referral


@app.put("/option-funding-referrals/{referral_id}/decline")
def decline_option_funding_referral(
    referral_id: int,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can decline a referral request")
    referral = db.query(OptionFundingReferral).filter(OptionFundingReferral.id == referral_id).first()
    if referral is None:
        raise HTTPException(status_code=404, detail="Option funding referral not found")
    if referral.status != "requested":
        raise HTTPException(status_code=400, detail="Only a referral request still in 'requested' status can be declined")
    referral.status = "declined"
    if notes is not None:
        referral.notes = notes
    db.commit()
    db.refresh(referral)
    return referral


@app.put("/option-funding-referrals/{referral_id}/close")
def close_option_funding_referral(
    referral_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can close a referral")
    referral = db.query(OptionFundingReferral).filter(OptionFundingReferral.id == referral_id).first()
    if referral is None:
        raise HTTPException(status_code=404, detail="Option funding referral not found")
    if referral.status != "referred":
        raise HTTPException(status_code=400, detail="Only a referred request can be closed")
    referral.status = "closed"
    referral.closed_at = datetime.utcnow()
    db.commit()
    db.refresh(referral)
    return referral


@app.get("/option-funding-referrals")
def get_option_funding_referrals(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        referrals = db.query(OptionFundingReferral).all()
    else:
        referrals = db.query(OptionFundingReferral).filter(OptionFundingReferral.holder_id == current_user.id).all()
    return referrals


@app.get("/option-funding-referrals/{referral_id}")
def get_option_funding_referral(
    referral_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    referral = db.query(OptionFundingReferral).filter(OptionFundingReferral.id == referral_id).first()
    if referral is None:
        raise HTTPException(status_code=404, detail="Option funding referral not found")
    if current_user.account_type != "admin" and referral.holder_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this referral")
    return referral


# ---------------------------------------------------------------------------
@app.get("/compliance-ledger/transaction/{transaction_id}")
def get_compliance_ledger_for_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    is_admin = current_user.account_type == "admin"
    is_party = current_user.id in (transaction.buyer_id, transaction.seller_id)
    if not (is_admin or is_party):
        raise HTTPException(status_code=403, detail="You do not have access to this transaction's compliance ledger")

    entries = db.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.transaction_id == transaction_id
    ).order_by(ComplianceDecisionLedger.id.asc()).all()

    result = []
    for entry in entries:
        recomputed = _compute_ledger_entry_hash(
            entry.previous_hash, entry.transaction_id, entry.buyer_id, entry.listing_id,
            entry.decision_status, entry.explanation, entry.applicable_rule_codes,
            entry.triggered_by, entry.decided_at
        )
        result.append({
            "id": entry.id,
            "transaction_id": entry.transaction_id,
            "buyer_id": entry.buyer_id,
            "listing_id": entry.listing_id,
            "decision_status": entry.decision_status,
            "explanation": entry.explanation,
            "applicable_rule_codes": json.loads(entry.applicable_rule_codes),
            "triggered_by": entry.triggered_by,
            "decided_at": entry.decided_at,
            "previous_hash": entry.previous_hash,
            "entry_hash": entry.entry_hash,
            "hash_valid": recomputed == entry.entry_hash
        })
    return result


@app.get("/compliance-ledger/verify")
def verify_compliance_ledger(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can verify the full compliance decision ledger")

    entries = db.query(ComplianceDecisionLedger).order_by(ComplianceDecisionLedger.id.asc()).all()

    expected_previous_hash = GENESIS_HASH
    first_invalid_entry_id = None

    for entry in entries:
        if entry.previous_hash != expected_previous_hash:
            first_invalid_entry_id = entry.id
            break
        recomputed = _compute_ledger_entry_hash(
            entry.previous_hash, entry.transaction_id, entry.buyer_id, entry.listing_id,
            entry.decision_status, entry.explanation, entry.applicable_rule_codes,
            entry.triggered_by, entry.decided_at
        )
        if recomputed != entry.entry_hash:
            first_invalid_entry_id = entry.id
            break
        expected_previous_hash = entry.entry_hash

    return {
        "valid": first_invalid_entry_id is None,
        "total_entries": len(entries),
        "first_invalid_entry_id": first_invalid_entry_id
    }


@app.get("/compliance-ledger/{entry_id}")
def get_compliance_ledger_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    entry = db.query(ComplianceDecisionLedger).filter(ComplianceDecisionLedger.id == entry_id).first()
    if entry is None:
        raise HTTPException(status_code=404, detail="Compliance ledger entry not found")

    transaction = db.query(Transaction).filter(Transaction.id == entry.transaction_id).first()
    is_admin = current_user.account_type == "admin"
    is_party = transaction is not None and current_user.id in (transaction.buyer_id, transaction.seller_id)
    if not (is_admin or is_party):
        raise HTTPException(status_code=403, detail="You do not have access to this compliance ledger entry")

    recomputed = _compute_ledger_entry_hash(
        entry.previous_hash, entry.transaction_id, entry.buyer_id, entry.listing_id,
        entry.decision_status, entry.explanation, entry.applicable_rule_codes,
        entry.triggered_by, entry.decided_at
    )
    return {
        "id": entry.id,
        "transaction_id": entry.transaction_id,
        "buyer_id": entry.buyer_id,
        "listing_id": entry.listing_id,
        "decision_status": entry.decision_status,
        "explanation": entry.explanation,
        "applicable_rule_codes": json.loads(entry.applicable_rule_codes),
        "triggered_by": entry.triggered_by,
        "decided_at": entry.decided_at,
        "previous_hash": entry.previous_hash,
        "entry_hash": entry.entry_hash,
        "hash_valid": recomputed == entry.entry_hash
    }


# M16 — Demand Heatmap / Blind Demand Curve
# Pure, read-only aggregation over BuyerInterest data KEVO already has.
# No price synthesis of any kind — every value returned is a count or a
# quantity, never a computed price. Nothing is persisted; recomputed live
# on every call.
# ---------------------------------------------------------------------------

MIN_DISTINCT_BUYERS = 5


def _price_band_boundaries(prices, max_bands=10):
    unique_sorted = sorted(set(prices))

    if len(unique_sorted) <= 1:
        return []

    n = min(max_bands, len(unique_sorted))

    if n < 2:
        return []

    cut_points = statistics.quantiles(unique_sorted, n=n, method="inclusive")

    return sorted(set(round(c, 2) for c in cut_points))


def _price_band_index(price, boundaries):
    return bisect.bisect_right(boundaries, round(float(price), 2))


def _price_band_range(band_index, boundaries, min_price, max_price):
    low = float(min_price) if band_index == 0 else boundaries[band_index - 1]
    high = float(max_price) if band_index == len(boundaries) else boundaries[band_index]
    return low, high


def build_demand_heatmap(company, asset_type, db):
    interests = db.query(BuyerInterest).filter(
        BuyerInterest.company == company,
        BuyerInterest.asset_type == asset_type,
        BuyerInterest.status == "active"
    ).all()

    distinct_buyers_total = {interest.buyer_id for interest in interests}

    if len(distinct_buyers_total) < MIN_DISTINCT_BUYERS:
        return {
            "status": "insufficient_data",
            "company": company,
            "asset_type": asset_type,
            "message": (
                f"Fewer than {MIN_DISTINCT_BUYERS} distinct buyers have "
                "stated active interest in this company/asset type — "
                "insufficient data to display without risking "
                "re-identification."
            )
        }

    buyer_jurisdictions = {
        user.id: (user.jurisdiction or "unknown")
        for user in db.query(UserModel).filter(
            UserModel.id.in_(distinct_buyers_total)
        ).all()
    }

    prices = [float(interest.maximum_price) for interest in interests]
    boundaries = _price_band_boundaries(prices)
    min_price, max_price = min(prices), max(prices)
    num_bands = len(boundaries) + 1

    raw = defaultdict(lambda: defaultdict(lambda: {"buyers": set(), "quantity": 0}))

    for interest in interests:
        band = _price_band_index(interest.maximum_price, boundaries)
        jurisdiction = buyer_jurisdictions.get(interest.buyer_id, "unknown")
        cell = raw[band][jurisdiction]
        cell["buyers"].add(interest.buyer_id)
        cell["quantity"] += interest.desired_quantity

    cells = []
    pending_buyers = set()
    pending_quantity = 0
    pending_start_band = None

    for band in range(num_bands):
        jurisdiction_cells = raw.get(band, {})

        thin_buyers = set()
        thin_quantity = 0

        for jurisdiction, cell in jurisdiction_cells.items():
            if len(cell["buyers"]) >= MIN_DISTINCT_BUYERS:
                low, high = _price_band_range(band, boundaries, min_price, max_price)
                cells.append({
                    "price_band_low": low,
                    "price_band_high": high,
                    "jurisdiction": jurisdiction,
                    "buyer_count": len(cell["buyers"]),
                    "total_desired_quantity": cell["quantity"]
                })
            else:
                thin_buyers |= cell["buyers"]
                thin_quantity += cell["quantity"]

        if thin_buyers:
            if pending_start_band is None:
                pending_start_band = band
            pending_buyers |= thin_buyers
            pending_quantity += thin_quantity

        if len(pending_buyers) >= MIN_DISTINCT_BUYERS:
            low, _ = _price_band_range(pending_start_band, boundaries, min_price, max_price)
            _, high = _price_band_range(band, boundaries, min_price, max_price)
            cells.append({
                "price_band_low": low,
                "price_band_high": high,
                "jurisdiction": None,
                "buyer_count": len(pending_buyers),
                "total_desired_quantity": pending_quantity
            })
            pending_buyers = set()
            pending_quantity = 0
            pending_start_band = None

    cells.sort(key=lambda c: (c["price_band_low"], c["jurisdiction"] or ""))

    return {
        "status": "ok",
        "company": company,
        "asset_type": asset_type,
        "cells": cells
    }


def build_demand_curve(company, asset_type, db):
    interests = db.query(BuyerInterest).filter(
        BuyerInterest.company == company,
        BuyerInterest.asset_type == asset_type,
        BuyerInterest.status == "active"
    ).all()

    distinct_buyers_total = {interest.buyer_id for interest in interests}

    if len(distinct_buyers_total) < MIN_DISTINCT_BUYERS:
        return {
            "status": "insufficient_data",
            "company": company,
            "asset_type": asset_type,
            "message": (
                f"Fewer than {MIN_DISTINCT_BUYERS} distinct buyers have "
                "stated active interest in this company/asset type — "
                "insufficient data to display without risking "
                "re-identification."
            )
        }

    by_price = defaultdict(list)

    for interest in interests:
        by_price[round(float(interest.maximum_price), 2)].append(interest)

    prices_desc = sorted(by_price.keys(), reverse=True)

    points = []
    cumulative_quantity = 0
    pending_buyers = set()
    pending_quantity = 0
    price = None

    for price in prices_desc:
        group = by_price[price]
        group_buyers = {i.buyer_id for i in group}
        group_quantity = sum(i.desired_quantity for i in group)

        cumulative_quantity += group_quantity
        pending_buyers |= group_buyers
        pending_quantity += group_quantity

        if len(pending_buyers) >= MIN_DISTINCT_BUYERS:
            points.append({
                "price_at_or_above": price,
                "cumulative_quantity": cumulative_quantity,
                "distinct_buyers_in_step": len(pending_buyers)
            })
            pending_buyers = set()
            pending_quantity = 0

    if pending_buyers:
        points[-1]["price_at_or_above"] = price
        points[-1]["distinct_buyers_in_step"] += len(pending_buyers)
        points[-1]["cumulative_quantity"] = cumulative_quantity

    return {
        "status": "ok",
        "company": company,
        "asset_type": asset_type,
        "points": points
    }


@app.get("/demand-heatmap")
def get_demand_heatmap(
    company: str,
    asset_type: str,
    db: Session = Depends(get_db)
):
    return build_demand_heatmap(company, asset_type, db)


@app.get("/demand-curve")
def get_demand_curve(
    company: str,
    asset_type: str,
    db: Session = Depends(get_db)
):
    return build_demand_curve(company, asset_type, db)


# ---------------------------------------------------------------------------
# M16B (narrowed, 2026-09-11/12) - Aggregate Demand/Supply Indicator
# Full multi-party transaction coordination (KEVO's own logic deciding which
# buyers combine with which sellers) was NOT built - see
# claude/kevo-m16b-liquidity-aggregation-critical-assessment.md. Every real
# comparable platform's multi-party matching function sits inside a
# registered broker-dealer/ATS; this stays on the same safe, aggregate-only
# footing already used by the Demand Heatmap above instead. Pure quantity
# arithmetic on live data - no specific buyer or seller is ever named to the
# other side, no allocation is ever decided, nothing is persisted.
# ---------------------------------------------------------------------------

def build_liquidity_aggregation(company, asset_type, db):
    interests = db.query(BuyerInterest).filter(
        BuyerInterest.company == company,
        BuyerInterest.asset_type == asset_type,
        BuyerInterest.status == "active"
    ).all()

    listings = db.query(ListingModel).filter(
        ListingModel.company == company,
        ListingModel.asset_type == asset_type,
        ListingModel.is_transferable == True,
        ListingModel.seller_id.isnot(None)
    ).all()

    distinct_buyers = {interest.buyer_id for interest in interests}
    distinct_sellers = {listing.seller_id for listing in listings}

    if len(distinct_buyers) < MIN_DISTINCT_BUYERS or len(distinct_sellers) < MIN_DISTINCT_BUYERS:
        return {
            "status": "insufficient_data",
            "company": company,
            "asset_type": asset_type,
            "message": (
                f"Fewer than {MIN_DISTINCT_BUYERS} distinct buyers and/or "
                f"fewer than {MIN_DISTINCT_BUYERS} distinct sellers have "
                "active interest/listings in this company/asset type - "
                "insufficient data to display without risking "
                "re-identification."
            )
        }

    total_desired_quantity = sum(interest.desired_quantity for interest in interests)
    total_available_quantity = sum(listing.quantity for listing in listings)

    if total_available_quantity >= total_desired_quantity:
        aggregate_status = "supply_may_cover_demand"
        reason = (
            "Aggregate active listed supply (" + str(total_available_quantity) +
            ") meets or exceeds aggregate active buyer demand (" +
            str(total_desired_quantity) + ") for this company and asset type. "
            "This is a quantity comparison only - it does not check price "
            "compatibility, ownership verification, transferability, or "
            "compliance for any specific pairing, and it does not identify "
            "or connect any specific buyer to any specific seller."
        )
    else:
        aggregate_status = "insufficient_supply"
        reason = (
            "Aggregate active listed supply (" + str(total_available_quantity) +
            ") is less than aggregate active buyer demand (" +
            str(total_desired_quantity) + ") for this company and asset type."
        )

    return {
        "status": "ok",
        "company": company,
        "asset_type": asset_type,
        "active_buyer_count": len(distinct_buyers),
        "total_desired_quantity": total_desired_quantity,
        "active_seller_count": len(distinct_sellers),
        "total_available_quantity": total_available_quantity,
        "aggregate_status": aggregate_status,
        "reason": reason
    }


@app.get("/liquidity-aggregation")
def get_liquidity_aggregation(
    company: str,
    asset_type: str,
    db: Session = Depends(get_db)
):
    return build_liquidity_aggregation(company, asset_type, db)


# ---------------------------------------------------------------------------
# M30B — Company-Sponsored Tender Offer Program (first slice)
# KEVO has no "company"/"issuer" login-capable actor (confirmed by direct
# audit, 2026-09-20) and building one was confirmed out of scope. Follows
# the same admin-administered pattern already used for RofrRequest and
# SettlementRecord: an admin creates and manages a program on a real
# company's behalf, recording price/window/eligibility the company already
# agreed to outside the platform. KEVO never sets, suggests, or computes
# an allocation - the admin records the company's own real decision,
# preserving the standing no-trade-term-setting invariant (2026-09-09).
# Jurisdictional research (claude/kevo-m30b-tender-offer-program-research-
# and-audit.md) found Canada currently lacks a clean small-private-company
# issuer-bid exemption, so Canada is deliberately excluded here - the CSA's
# proposed Selective Repurchase Exemption is not yet in force.
# ---------------------------------------------------------------------------

TENDER_OFFER_EXCLUDED_JURISDICTIONS = {"Canada"}


@app.post("/tender-offer-programs")
def create_tender_offer_program(
    company: str,
    jurisdiction: str,
    price_per_share: float,
    opens_at: datetime,
    closes_at: datetime,
    source_reference: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can create a tender offer program")
    if jurisdiction in TENDER_OFFER_EXCLUDED_JURISDICTIONS:
        raise HTTPException(
            status_code=400,
            detail="Canada is not yet supported for tender offer programs - current Canadian securities law lacks a clean small-private-company issuer-bid exemption for this"
        )
    if price_per_share <= 0:
        raise HTTPException(status_code=400, detail="Price per share must be greater than zero")
    if closes_at <= opens_at:
        raise HTTPException(status_code=400, detail="Closing time must be after opening time")
    program = TenderOfferProgram(
        company=company,
        jurisdiction=jurisdiction,
        price_per_share=price_per_share,
        opens_at=opens_at,
        closes_at=closes_at,
        status="open",
        source_reference=source_reference,
        created_at=datetime.utcnow()
    )
    db.add(program)
    db.commit()
    db.refresh(program)
    return program


@app.get("/tender-offer-programs")
def get_tender_offer_programs(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        return db.query(TenderOfferProgram).all()
    eligible_companies = {
        row.company for row in db.query(OwnershipRecord).filter(
            OwnershipRecord.seller_id == current_user.id,
            OwnershipRecord.verification_status == "verified"
        ).all()
    }
    if not eligible_companies:
        return []
    return db.query(TenderOfferProgram).filter(TenderOfferProgram.company.in_(eligible_companies)).all()


@app.get("/tender-offer-programs/{program_id}")
def get_tender_offer_program(
    program_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    program = db.query(TenderOfferProgram).filter(TenderOfferProgram.id == program_id).first()
    if program is None:
        raise HTTPException(status_code=404, detail="Tender offer program not found")
    if current_user.account_type == "admin":
        return program
    is_eligible = db.query(OwnershipRecord).filter(
        OwnershipRecord.seller_id == current_user.id,
        OwnershipRecord.company == program.company,
        OwnershipRecord.verification_status == "verified"
    ).first() is not None
    if not is_eligible:
        raise HTTPException(status_code=403, detail="You do not have a verified holding in this company")
    return program


@app.put("/tender-offer-programs/{program_id}/close")
def close_tender_offer_program(
    program_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can close a tender offer program")
    program = db.query(TenderOfferProgram).filter(TenderOfferProgram.id == program_id).first()
    if program is None:
        raise HTTPException(status_code=404, detail="Tender offer program not found")
    if program.status != "open":
        raise HTTPException(status_code=400, detail="Only an open tender offer program can be closed")
    program.status = "closed"
    db.commit()
    db.refresh(program)
    return program


@app.post("/tender-offer-elections")
def create_tender_offer_election(
    program_id: int,
    ownership_record_id: int,
    shares_offered: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    program = db.query(TenderOfferProgram).filter(TenderOfferProgram.id == program_id).first()
    if program is None:
        raise HTTPException(status_code=404, detail="Tender offer program not found")
    if program.status != "open":
        raise HTTPException(status_code=400, detail="This tender offer program is not open")
    now = datetime.utcnow()
    if now < program.opens_at or now > program.closes_at:
        raise HTTPException(status_code=400, detail="This tender offer program's window is not currently open")
    ownership_record = db.query(OwnershipRecord).filter(OwnershipRecord.id == ownership_record_id).first()
    if ownership_record is None:
        raise HTTPException(status_code=404, detail="Ownership record not found")
    if ownership_record.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only elect to participate using your own ownership record")
    if ownership_record.verification_status != "verified":
        raise HTTPException(status_code=400, detail="Ownership record must be verified before it can participate in a tender offer")
    if ownership_record.company != program.company:
        raise HTTPException(status_code=400, detail="This ownership record is not for the company running this tender offer program")
    if shares_offered <= 0:
        raise HTTPException(status_code=400, detail="Shares offered must be greater than zero")
    if shares_offered > ownership_record.quantity:
        raise HTTPException(status_code=400, detail="Shares offered cannot exceed the quantity on this ownership record")
    election = TenderOfferElection(
        program_id=program_id,
        ownership_record_id=ownership_record_id,
        holder_id=current_user.id,
        shares_offered=shares_offered,
        status="pending",
        created_at=datetime.utcnow()
    )
    db.add(election)
    db.commit()
    db.refresh(election)
    return election


@app.put("/tender-offer-elections/{election_id}/withdraw")
def withdraw_tender_offer_election(
    election_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    election = db.query(TenderOfferElection).filter(TenderOfferElection.id == election_id).first()
    if election is None:
        raise HTTPException(status_code=404, detail="Tender offer election not found")
    if election.holder_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only withdraw your own election")
    if election.status != "pending":
        raise HTTPException(status_code=400, detail="Only a pending election can be withdrawn")
    election.status = "withdrawn"
    election.decided_at = datetime.utcnow()
    db.commit()
    db.refresh(election)
    return election


@app.put("/tender-offer-elections/{election_id}/finalize")
def finalize_tender_offer_election(
    election_id: int,
    accepted: bool,
    shares_accepted: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can finalize a tender offer election")
    election = db.query(TenderOfferElection).filter(TenderOfferElection.id == election_id).first()
    if election is None:
        raise HTTPException(status_code=404, detail="Tender offer election not found")
    if election.status != "pending":
        raise HTTPException(status_code=400, detail="Only a pending election can be finalized")
    if accepted:
        if shares_accepted is None or shares_accepted <= 0:
            raise HTTPException(status_code=400, detail="shares_accepted is required and must be greater than zero when accepting")
        if shares_accepted > election.shares_offered:
            raise HTTPException(status_code=400, detail="shares_accepted cannot exceed the shares originally offered")
        election.shares_accepted = shares_accepted
        election.status = "accepted"
    else:
        election.status = "declined"
    election.decided_at = datetime.utcnow()
    db.commit()
    db.refresh(election)
    return election


@app.get("/tender-offer-elections")
def get_tender_offer_elections(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        return db.query(TenderOfferElection).all()
    return db.query(TenderOfferElection).filter(TenderOfferElection.holder_id == current_user.id).all()


@app.get("/tender-offer-elections/{election_id}")
def get_tender_offer_election(
    election_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    election = db.query(TenderOfferElection).filter(TenderOfferElection.id == election_id).first()
    if election is None:
        raise HTTPException(status_code=404, detail="Tender offer election not found")
    if current_user.account_type != "admin" and election.holder_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this tender offer election")
    return election


# ---------------------------------------------------------------------------
# Batch B Group 3 item 9 (2026-09-24) - Seller Financing, tracking-only.
# See SellerFinancingAgreement's docstring in models.py for the legal
# research (Reves test / TILA business-purpose exemption / usury variation)
# behind this design. KEVO never originates, funds, holds, or services this
# credit arrangement - it only records the caller-supplied terms and
# generates the resulting payment schedule via ordinary amortization
# arithmetic. No money moves through KEVO for the installment payments.
# ---------------------------------------------------------------------------

class SellerFinancingAgreementCreate(BaseModel):
    transaction_id: int
    principal_amount: float
    annual_interest_rate_pct: float = 0
    term_months: int
    payment_frequency: str = "monthly"
    first_payment_due_date: date
    source_reference: str | None = None
    restricts_transfer_until_paid: bool = False


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _generate_seller_financing_schedule(principal, annual_rate_pct, term_months, frequency, first_due_date):
    months_per_period = {"monthly": 1, "quarterly": 3}[frequency]
    num_payments = term_months // months_per_period
    periodic_rate = (float(annual_rate_pct) / 100) * (months_per_period / 12)
    principal = float(principal)

    if periodic_rate == 0:
        base_amount = round(principal / num_payments, 2)
    else:
        base_amount = round(
            principal * periodic_rate / (1 - (1 + periodic_rate) ** -num_payments),
            2
        )

    schedule = []
    due_date = first_due_date
    running_total = 0.0
    target_total = round(base_amount * num_payments, 2)
    for i in range(1, num_payments + 1):
        if i < num_payments:
            amount = base_amount
        else:
            # Last installment absorbs rounding drift from the prior
            # payments so the schedule's total ties out to the cent
            # instead of silently drifting.
            amount = round(target_total - running_total, 2)
        schedule.append((i, due_date, amount))
        running_total += amount
        due_date = _add_months(due_date, months_per_period)
    return schedule


def _get_seller_financing_agreement_or_404(agreement_id, db):
    agreement = db.query(SellerFinancingAgreement).filter(SellerFinancingAgreement.id == agreement_id).first()
    if agreement is None:
        raise HTTPException(status_code=404, detail="Seller financing agreement not found")
    return agreement


def _require_seller_financing_party_or_admin(agreement, current_user, db):
    transaction = db.query(Transaction).filter(Transaction.id == agreement.transaction_id).first()
    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(status_code=403, detail="You are not a party to this seller financing agreement")
    return transaction


@app.post("/seller-financing-agreements")
def create_seller_financing_agreement(
    payload: SellerFinancingAgreementCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(Transaction.id == payload.transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if current_user.account_type != "admin" and current_user.id != transaction.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller or an admin can set up seller financing for this transaction")
    if transaction.status not in ("accepted", "settlement_pending"):
        raise HTTPException(status_code=400, detail="Transaction must be accepted (or in settlement) before seller financing can be set up")

    existing = db.query(SellerFinancingAgreement).filter(SellerFinancingAgreement.transaction_id == payload.transaction_id).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="A seller financing agreement already exists for this transaction")

    if payload.principal_amount <= 0:
        raise HTTPException(status_code=400, detail="principal_amount must be positive")
    if payload.annual_interest_rate_pct < 0:
        raise HTTPException(status_code=400, detail="annual_interest_rate_pct cannot be negative")
    if payload.term_months <= 0:
        raise HTTPException(status_code=400, detail="term_months must be positive")
    if payload.payment_frequency not in ("monthly", "quarterly"):
        raise HTTPException(status_code=400, detail="payment_frequency must be 'monthly' or 'quarterly'")
    months_per_period = {"monthly": 1, "quarterly": 3}[payload.payment_frequency]
    if payload.term_months % months_per_period != 0:
        raise HTTPException(status_code=400, detail=f"term_months must be a multiple of {months_per_period} for {payload.payment_frequency} payments")

    agreement = SellerFinancingAgreement(
        transaction_id=payload.transaction_id,
        principal_amount=payload.principal_amount,
        annual_interest_rate_pct=payload.annual_interest_rate_pct,
        term_months=payload.term_months,
        payment_frequency=payload.payment_frequency,
        first_payment_due_date=payload.first_payment_due_date,
        status="active",
        source_reference=payload.source_reference,
        created_at=datetime.utcnow(),
        restricts_transfer_until_paid=payload.restricts_transfer_until_paid
    )
    db.add(agreement)
    db.commit()
    db.refresh(agreement)

    schedule = _generate_seller_financing_schedule(
        payload.principal_amount,
        payload.annual_interest_rate_pct,
        payload.term_months,
        payload.payment_frequency,
        payload.first_payment_due_date
    )
    for installment_number, due_date, amount in schedule:
        db.add(SellerFinancingPayment(
            agreement_id=agreement.id,
            installment_number=installment_number,
            due_date=due_date,
            amount_due=amount,
            status="pending"
        ))
    db.commit()
    db.refresh(agreement)
    return agreement


@app.put("/seller-financing-agreements/{agreement_id}/payments/{payment_id}/confirm")
def confirm_seller_financing_payment(
    agreement_id: int,
    payment_id: int,
    paid_amount: float | None = None,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    transaction = db.query(Transaction).filter(Transaction.id == agreement.transaction_id).first()
    if current_user.account_type != "admin" and current_user.id != transaction.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller (who is owed this payment) or an admin can confirm it was received")
    payment = db.query(SellerFinancingPayment).filter(
        SellerFinancingPayment.id == payment_id,
        SellerFinancingPayment.agreement_id == agreement_id
    ).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found on this agreement")
    if payment.status == "paid":
        raise HTTPException(status_code=400, detail="This payment is already marked paid")
    payment.status = "paid"
    payment.paid_at = datetime.utcnow()
    payment.paid_amount = paid_amount if paid_amount is not None else payment.amount_due
    if notes is not None:
        payment.notes = notes
    db.commit()

    remaining = db.query(SellerFinancingPayment).filter(
        SellerFinancingPayment.agreement_id == agreement_id,
        SellerFinancingPayment.status != "paid"
    ).count()
    if remaining == 0:
        agreement.status = "completed"
        db.commit()

    db.refresh(payment)
    return payment


@app.put("/seller-financing-agreements/{agreement_id}/payments/{payment_id}/mark-late")
def mark_seller_financing_payment_late(
    agreement_id: int,
    payment_id: int,
    notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    transaction = db.query(Transaction).filter(Transaction.id == agreement.transaction_id).first()
    if current_user.account_type != "admin" and current_user.id != transaction.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller or an admin can mark a payment late")
    payment = db.query(SellerFinancingPayment).filter(
        SellerFinancingPayment.id == payment_id,
        SellerFinancingPayment.agreement_id == agreement_id
    ).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found on this agreement")
    if payment.status == "paid":
        raise HTTPException(status_code=400, detail="Cannot mark an already-paid payment as late")
    payment.status = "late"
    if notes is not None:
        payment.notes = notes
    db.commit()
    db.refresh(payment)
    return payment


@app.get("/seller-financing-agreements")
def get_seller_financing_agreements(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        return db.query(SellerFinancingAgreement).all()
    own_transaction_ids = [
        t.id for t in db.query(Transaction).filter(
            (Transaction.buyer_id == current_user.id) | (Transaction.seller_id == current_user.id)
        ).all()
    ]
    return db.query(SellerFinancingAgreement).filter(SellerFinancingAgreement.transaction_id.in_(own_transaction_ids)).all()


@app.get("/seller-financing-agreements/{agreement_id}")
def get_seller_financing_agreement(
    agreement_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    _require_seller_financing_party_or_admin(agreement, current_user, db)
    return agreement


@app.get("/seller-financing-agreements/{agreement_id}/payments")
def get_seller_financing_payments(
    agreement_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    _require_seller_financing_party_or_admin(agreement, current_user, db)
    return db.query(SellerFinancingPayment).filter(
        SellerFinancingPayment.agreement_id == agreement_id
    ).order_by(SellerFinancingPayment.installment_number).all()


@app.put("/seller-financing-agreements/{agreement_id}/default")
def mark_seller_financing_agreement_defaulted(
    agreement_id: int,
    reason: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Batch B accountability extension (2026-09-24). The seller (or admin)
    marks an agreement defaulted when the buyer has stopped paying -
    KEVO does not decide this on its own via any invented threshold, since
    what actually counts as default is up to the parties' own note, the
    same reasoning already applied to never inventing agreed_price or an
    interest rate. The real consequence is on the buyer's own KEVO
    account, not a report compiled for other companies (see User.
    seller_financing_blocked's docstring for why that distinction
    matters). Acceleration - whether the full remaining balance is now
    demandable - is a fact about the parties' own note, not something
    KEVO enforces; this endpoint records that a default happened and
    applies KEVO's own platform-level consequence, nothing more.
    """
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    transaction = db.query(Transaction).filter(Transaction.id == agreement.transaction_id).first()
    if current_user.account_type != "admin" and current_user.id != transaction.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller or an admin can mark this agreement defaulted")
    if agreement.status != "active":
        raise HTTPException(status_code=400, detail=f"Agreement must be 'active' to be marked defaulted (currently '{agreement.status}')")

    agreement.status = "defaulted"
    agreement.default_reason = reason
    agreement.defaulted_at = datetime.utcnow()
    db.commit()

    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
    buyer.seller_financing_blocked = True
    buyer.seller_financing_blocked_at = datetime.utcnow()
    buyer.seller_financing_blocked_reason = f"Defaulted on seller financing agreement #{agreement.id}: {reason}"
    db.commit()
    db.refresh(agreement)
    return agreement


@app.put("/seller-financing-agreements/{agreement_id}/resolve-default")
def resolve_seller_financing_default(
    agreement_id: int,
    resolution_notes: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    Admin-only, mirroring every other "only an admin can attest this is
    resolved" gate already in the app - a buyer cannot self-declare their
    own way out of a restriction. Lifts the account-level block; whatever
    actually happened (renegotiated, paid off outside the platform,
    written off, escalated) is recorded in resolution_notes as free text,
    not a KEVO-invented outcome category.
    """
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can resolve a seller financing default")
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    if agreement.status != "defaulted":
        raise HTTPException(status_code=400, detail=f"Agreement must be 'defaulted' to be resolved (currently '{agreement.status}')")

    agreement.status = "resolved"
    agreement.resolution_notes = resolution_notes
    agreement.resolved_at = datetime.utcnow()
    db.commit()

    transaction = db.query(Transaction).filter(Transaction.id == agreement.transaction_id).first()
    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
    buyer.seller_financing_blocked = False
    buyer.seller_financing_blocked_at = None
    buyer.seller_financing_blocked_reason = None
    db.commit()
    db.refresh(agreement)
    return agreement


# ---------------------------------------------------------------------------
# Seller Financing Protection System (2026-09-24) - security deposit /
# reserve tracking. KEVO never moves money (same reasoning as
# SettlementRecord). required_amount is a party-agreed term (seller or
# admin records it). funded/released are admin-only attestations of a
# real-world fact, exactly like SettlementRecord.funds_received.
# released_to records who the parties themselves decided the reserve went
# to - KEVO records that outcome, it never decides it.
# ---------------------------------------------------------------------------

class SellerFinancingReserveCreate(BaseModel):
    required_amount: float
    notes: str | None = None


@app.post("/seller-financing-agreements/{agreement_id}/reserve")
def create_seller_financing_reserve(
    agreement_id: int,
    payload: SellerFinancingReserveCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    transaction = _require_seller_financing_party_or_admin(agreement, current_user, db)
    if current_user.account_type != "admin" and current_user.id != transaction.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller or an admin can set up the agreed reserve for this agreement")
    existing = db.query(SellerFinancingReserve).filter(SellerFinancingReserve.agreement_id == agreement_id).first()
    if existing is not None:
        raise HTTPException(status_code=403, detail="A reserve already exists for this agreement")
    if payload.required_amount <= 0:
        raise HTTPException(status_code=400, detail="required_amount must be greater than zero")

    reserve = SellerFinancingReserve(
        agreement_id=agreement_id,
        required_amount=payload.required_amount,
        status="pending",
        notes=payload.notes,
        created_at=datetime.utcnow(),
    )
    db.add(reserve)
    db.commit()
    db.refresh(reserve)
    return reserve


@app.put("/seller-financing-agreements/{agreement_id}/reserve/fund")
def fund_seller_financing_reserve(
    agreement_id: int,
    funded_reference: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can confirm the reserve was funded")
    reserve = db.query(SellerFinancingReserve).filter(SellerFinancingReserve.agreement_id == agreement_id).first()
    if reserve is None:
        raise HTTPException(status_code=404, detail="No reserve exists for this agreement")
    if reserve.status != "pending":
        raise HTTPException(status_code=400, detail="Only a pending reserve can be marked funded")
    if not funded_reference or not funded_reference.strip():
        raise HTTPException(status_code=400, detail="funded_reference is required")

    reserve.status = "funded"
    reserve.funded_at = datetime.utcnow()
    reserve.funded_reference = funded_reference
    db.commit()
    db.refresh(reserve)
    return reserve


@app.put("/seller-financing-agreements/{agreement_id}/reserve/release")
def release_seller_financing_reserve(
    agreement_id: int,
    released_to: str,
    released_reference: str,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can confirm the reserve was released")
    if released_to not in ("buyer", "seller"):
        raise HTTPException(status_code=400, detail="released_to must be 'buyer' or 'seller'")
    reserve = db.query(SellerFinancingReserve).filter(SellerFinancingReserve.agreement_id == agreement_id).first()
    if reserve is None:
        raise HTTPException(status_code=404, detail="No reserve exists for this agreement")
    if reserve.status != "funded":
        raise HTTPException(status_code=400, detail="Only a funded reserve can be released")
    if not released_reference or not released_reference.strip():
        raise HTTPException(status_code=400, detail="released_reference is required")

    reserve.status = "released"
    reserve.released_at = datetime.utcnow()
    reserve.released_to = released_to
    reserve.released_reference = released_reference
    db.commit()
    db.refresh(reserve)
    return reserve


@app.get("/seller-financing-agreements/{agreement_id}/reserve")
def get_seller_financing_reserve(agreement_id: int, db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    _require_seller_financing_party_or_admin(agreement, current_user, db)
    reserve = db.query(SellerFinancingReserve).filter(SellerFinancingReserve.agreement_id == agreement_id).first()
    if reserve is None:
        raise HTTPException(status_code=404, detail="No reserve exists for this agreement")
    return reserve


# ---------------------------------------------------------------------------
# Seller Financing Protection System (2026-09-24) - collateral /
# security-interest tracking, "where legally permitted." UCC Article 9
# research (Sec 9-312/9-314/9-328) found that actually PERFECTING a
# security interest in investment property requires either a filed UCC-1
# financing statement or a control agreement with the custodian/issuer -
# both real legal/administrative acts outside any software system, and
# jurisdiction-specific outside the US. So this table is deliberately
# descriptive-only: it records what the parties privately agreed to
# pledge and its status, exactly as they tell KEVO - it does NOT create,
# file, or perfect a security interest, and every record starts
# legal_review_status="not_reviewed" so nothing is treated as a real,
# enforceable lien until an admin has actually looked at it.
# ---------------------------------------------------------------------------

class SellerFinancingCollateralCreate(BaseModel):
    description: str
    collateral_type: str
    estimated_value: float | None = None
    source_reference: str | None = None


@app.post("/seller-financing-agreements/{agreement_id}/collateral")
def create_seller_financing_collateral(
    agreement_id: int,
    payload: SellerFinancingCollateralCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    transaction = _require_seller_financing_party_or_admin(agreement, current_user, db)
    if not payload.description or not payload.description.strip():
        raise HTTPException(status_code=400, detail="description is required")
    if not payload.collateral_type or not payload.collateral_type.strip():
        raise HTTPException(status_code=400, detail="collateral_type is required")

    collateral = SellerFinancingCollateral(
        agreement_id=agreement_id,
        description=payload.description,
        collateral_type=payload.collateral_type,
        estimated_value=payload.estimated_value,
        status="pledged",
        legal_review_status="not_reviewed",
        source_reference=payload.source_reference,
        created_at=datetime.utcnow(),
    )
    db.add(collateral)
    db.commit()
    db.refresh(collateral)
    return collateral


@app.put("/seller-financing-agreements/{agreement_id}/collateral/{collateral_id}")
def update_seller_financing_collateral(
    agreement_id: int,
    collateral_id: int,
    status: str | None = None,
    legal_review_status: str | None = None,
    legal_review_notes: str | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can update a collateral record's status or legal review")
    collateral = db.query(SellerFinancingCollateral).filter(
        SellerFinancingCollateral.id == collateral_id,
        SellerFinancingCollateral.agreement_id == agreement_id,
    ).first()
    if collateral is None:
        raise HTTPException(status_code=404, detail="Collateral record not found for this agreement")

    if status is not None:
        if status not in ("pledged", "released", "disputed"):
            raise HTTPException(status_code=400, detail="status must be one of: pledged, released, disputed")
        collateral.status = status
        if status == "released":
            collateral.released_at = datetime.utcnow()
    if legal_review_status is not None:
        if legal_review_status not in ("not_reviewed", "reviewed_ok", "reviewed_flagged"):
            raise HTTPException(status_code=400, detail="legal_review_status must be one of: not_reviewed, reviewed_ok, reviewed_flagged")
        collateral.legal_review_status = legal_review_status
    if legal_review_notes is not None:
        collateral.legal_review_notes = legal_review_notes
    collateral.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(collateral)
    return collateral


@app.get("/seller-financing-agreements/{agreement_id}/collateral")
def get_seller_financing_collateral(agreement_id: int, db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    _require_seller_financing_party_or_admin(agreement, current_user, db)
    return db.query(SellerFinancingCollateral).filter(SellerFinancingCollateral.agreement_id == agreement_id).all()


@app.get("/seller-financing-agreements/{agreement_id}/summary")
def get_seller_financing_summary(agreement_id: int, db: Session = Depends(get_db), current_user: UserModel = Depends(get_current_user)):
    agreement = _get_seller_financing_agreement_or_404(agreement_id, db)
    transaction = _require_seller_financing_party_or_admin(agreement, current_user, db)

    payments = db.query(SellerFinancingPayment).filter(
        SellerFinancingPayment.agreement_id == agreement_id
    ).order_by(SellerFinancingPayment.installment_number).all()
    today = date.today()

    paid = [p for p in payments if p.status == "paid"]
    overdue = [p for p in payments if p.status in ("pending", "late") and p.due_date < today]
    upcoming = [p for p in payments if p.status == "pending" and p.due_date >= today]
    outstanding_total = sum(float(p.amount_due) for p in payments if p.status in ("pending", "late"))
    total_paid = sum(float(p.paid_amount) for p in paid if p.paid_amount is not None)

    reserve = db.query(SellerFinancingReserve).filter(SellerFinancingReserve.agreement_id == agreement_id).first()
    collateral_items = db.query(SellerFinancingCollateral).filter(SellerFinancingCollateral.agreement_id == agreement_id).all()
    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()

    return {
        "agreement_id": agreement.id,
        "agreement_status": agreement.status,
        "restricts_transfer_until_paid": agreement.restricts_transfer_until_paid,
        "payments_total": len(payments),
        "payments_paid": len(paid),
        "payments_upcoming": len(upcoming),
        "payments_overdue": len(overdue),
        "outstanding_amount": round(outstanding_total, 2),
        "total_paid": round(total_paid, 2),
        "next_payment_due_date": upcoming[0].due_date.isoformat() if upcoming else None,
        "reserve": {
            "required_amount": float(reserve.required_amount),
            "status": reserve.status,
        } if reserve is not None else None,
        "collateral": [
            {
                "id": c.id,
                "description": c.description,
                "collateral_type": c.collateral_type,
                "status": c.status,
                "legal_review_status": c.legal_review_status,
            }
            for c in collateral_items
        ],
        "buyer_account_blocked": buyer.seller_financing_blocked if buyer else None,
    }


def run_seller_financing_reminder_scan(db):
    """
    Seller Financing Protection System - automatic payment reminders
    (2026-09-24). Scans for payments due soon (not yet reminded) and
    payments overdue (not yet reminded), sends one email each via the
    existing Mailgun sandbox client, and marks the reminder sent so it
    never fires twice for the same payment. Never assesses a penalty,
    never changes an amount, never auto-declares default - it only
    surfaces facts and notifies people. An overdue reminder also notifies
    the seller (not just the buyer) since that directly feeds the
    accountability the default workflow exists for. A failed send (e.g.
    the sandbox email provider isn't configured) is caught per-payment
    and logged so it never blocks the rest of the scan.
    """
    today = date.today()
    upcoming_window_end = today + timedelta(days=3)
    counts = {"upcoming_sent": 0, "overdue_sent": 0, "failed": 0}

    upcoming_due = db.query(SellerFinancingPayment).filter(
        SellerFinancingPayment.status == "pending",
        SellerFinancingPayment.due_date >= today,
        SellerFinancingPayment.due_date <= upcoming_window_end,
        SellerFinancingPayment.reminder_upcoming_sent_at.is_(None),
    ).all()

    for payment in upcoming_due:
        agreement = db.query(SellerFinancingAgreement).filter(SellerFinancingAgreement.id == payment.agreement_id).first()
        if agreement is None or agreement.status != "active":
            continue
        transaction = db.query(Transaction).filter(Transaction.id == agreement.transaction_id).first()
        buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first() if transaction else None
        if buyer is None:
            continue
        try:
            email_client.send_email(
                buyer.email,
                "Upcoming seller financing payment due",
                f"Installment #{payment.installment_number} of ${payment.amount_due} is due on {payment.due_date.isoformat()}.",
            )
            payment.reminder_upcoming_sent_at = datetime.utcnow()
            counts["upcoming_sent"] += 1
        except Exception as exc:
            counts["failed"] += 1

    overdue_unreminded = db.query(SellerFinancingPayment).filter(
        SellerFinancingPayment.status.in_(["pending", "late"]),
        SellerFinancingPayment.due_date < today,
        SellerFinancingPayment.reminder_overdue_sent_at.is_(None),
    ).all()

    for payment in overdue_unreminded:
        agreement = db.query(SellerFinancingAgreement).filter(SellerFinancingAgreement.id == payment.agreement_id).first()
        if agreement is None or agreement.status != "active":
            continue
        transaction = db.query(Transaction).filter(Transaction.id == agreement.transaction_id).first()
        if transaction is None:
            continue
        buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
        seller = db.query(UserModel).filter(UserModel.id == transaction.seller_id).first()
        if buyer is None:
            continue
        try:
            email_client.send_email(
                buyer.email,
                "Seller financing payment overdue",
                f"Installment #{payment.installment_number} of ${payment.amount_due} was due on {payment.due_date.isoformat()} and has not been confirmed as paid.",
            )
            if seller is not None:
                email_client.send_email(
                    seller.email,
                    "Buyer payment overdue on your seller financing agreement",
                    f"Installment #{payment.installment_number} of ${payment.amount_due} from your buyer was due on {payment.due_date.isoformat()} and has not been confirmed as paid.",
                )
            if payment.status == "pending":
                payment.status = "late"
            payment.reminder_overdue_sent_at = datetime.utcnow()
            counts["overdue_sent"] += 1
        except Exception as exc:
            counts["failed"] += 1

    db.commit()
    return counts


@app.post("/seller-financing-agreements/reminders/run")
def run_seller_financing_reminders_endpoint(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type != "admin":
        raise HTTPException(status_code=403, detail="Only an admin can manually trigger the reminder scan")
    return run_seller_financing_reminder_scan(db)


# In-process scheduler (APScheduler) rather than Celery/Redis - KEVO runs
# as a single uvicorn worker with no message broker, and this needs
# nothing heavier than "run a function every few hours in this process."
# A future multi-worker deployment would move this to a dedicated worker
# process or an external cron hitting the endpoint above instead of
# running it here in every worker.
_seller_financing_scheduler = BackgroundScheduler()


def _seller_financing_reminder_job():
    db = SessionLocal()
    try:
        run_seller_financing_reminder_scan(db)
    finally:
        db.close()


@app.on_event("startup")
def _start_seller_financing_reminder_scheduler():
    if not _seller_financing_scheduler.running:
        _seller_financing_scheduler.add_job(
            _seller_financing_reminder_job,
            "interval",
            hours=6,
            id="seller_financing_reminders",
            replace_existing=True,
        )
        _seller_financing_scheduler.start()


@app.on_event("shutdown")
def _stop_seller_financing_reminder_scheduler():
    if _seller_financing_scheduler.running:
        _seller_financing_scheduler.shutdown(wait=False)


# --- M25 gap-closure: Due-Diligence Checklist (2026-09-25) ---
# Purely organizational - any party to the transaction (buyer, seller) or
# an admin can add or complete an item. No self-submit/admin-verify split
# needed here, unlike KYC/Evidence, since nothing is being certified.

class ChecklistItemCreate(BaseModel):
    description: str
    evidence_id: int | None = None
    source_reference: str | None = None


def _require_checklist_party_or_admin(transaction, current_user):
    is_admin = current_user.account_type == "admin"
    is_party = current_user.id in (transaction.buyer_id, transaction.seller_id)
    if not (is_admin or is_party):
        raise HTTPException(status_code=403, detail="You are not a party to this transaction")


@app.post("/transactions/{transaction_id}/checklist-items")
def create_checklist_item(
    transaction_id: int,
    payload: ChecklistItemCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _require_checklist_party_or_admin(transaction, current_user)

    if payload.evidence_id is not None:
        evidence = db.query(Evidence).filter(Evidence.id == payload.evidence_id).first()
        if evidence is None:
            raise HTTPException(status_code=404, detail="Evidence not found")

    item = DueDiligenceChecklistItem(
        transaction_id=transaction_id,
        description=payload.description,
        status="pending",
        evidence_id=payload.evidence_id,
        created_by_user_id=current_user.id,
        source_reference=payload.source_reference,
        created_at=datetime.utcnow(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.put("/checklist-items/{item_id}")
def update_checklist_item(
    item_id: int,
    status: str,
    evidence_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    item = db.query(DueDiligenceChecklistItem).filter(DueDiligenceChecklistItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    transaction = db.query(Transaction).filter(Transaction.id == item.transaction_id).first()
    _require_checklist_party_or_admin(transaction, current_user)

    if status not in ("pending", "complete", "not_applicable"):
        raise HTTPException(status_code=400, detail="Invalid status")

    if evidence_id is not None:
        evidence = db.query(Evidence).filter(Evidence.id == evidence_id).first()
        if evidence is None:
            raise HTTPException(status_code=404, detail="Evidence not found")
        item.evidence_id = evidence_id

    item.status = status
    if status == "complete":
        item.completed_by_user_id = current_user.id
        item.completed_at = datetime.utcnow()
    else:
        item.completed_by_user_id = None
        item.completed_at = None

    db.commit()
    db.refresh(item)
    return item


@app.get("/transactions/{transaction_id}/checklist-items")
def get_checklist_items(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _require_checklist_party_or_admin(transaction, current_user)
    return db.query(DueDiligenceChecklistItem).filter(
        DueDiligenceChecklistItem.transaction_id == transaction_id
    ).all()


class AuctionBidCreate(BaseModel):
    quantity: int
    bid_price: float
    note: str | None = None


def _require_auction_seller_or_admin(listing, current_user):
    is_admin = current_user.account_type == "admin"
    is_seller = current_user.id == listing.seller_id
    if not (is_admin or is_seller):
        raise HTTPException(status_code=403, detail="Only the listing's seller can do this")


@app.post("/listings/{listing_id}/auction-bids")
def create_auction_bid(
    listing_id: int,
    payload: AuctionBidCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    listing = db.query(ListingModel).filter(ListingModel.id == listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    if current_user.id == listing.seller_id:
        raise HTTPException(status_code=403, detail="You cannot bid on your own listing")

    if payload.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    if payload.bid_price <= 0:
        raise HTTPException(status_code=400, detail="Bid price must be positive")

    bid = SecondaryAuctionBid(
        listing_id=listing_id,
        bidder_id=current_user.id,
        quantity=payload.quantity,
        bid_price=payload.bid_price,
        note=payload.note,
        status="submitted",
        created_at=datetime.utcnow(),
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


@app.get("/listings/{listing_id}/auction-bids")
def get_auction_bids(
    listing_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    listing = db.query(ListingModel).filter(ListingModel.id == listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")

    is_admin = current_user.account_type == "admin"
    is_seller = current_user.id == listing.seller_id

    query = db.query(SecondaryAuctionBid).filter(SecondaryAuctionBid.listing_id == listing_id)
    if not (is_admin or is_seller):
        # Sealed bid: a buyer only ever sees their own bid, never another
        # buyer's terms - this is what keeps the mechanism a private
        # negotiation rather than a public order book.
        query = query.filter(SecondaryAuctionBid.bidder_id == current_user.id)

    return query.all()


@app.put("/auction-bids/{bid_id}/accept")
def accept_auction_bid(
    bid_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    bid = db.query(SecondaryAuctionBid).filter(SecondaryAuctionBid.id == bid_id).first()
    if bid is None:
        raise HTTPException(status_code=404, detail="Bid not found")

    listing = db.query(ListingModel).filter(ListingModel.id == bid.listing_id).first()
    _require_auction_seller_or_admin(listing, current_user)

    if bid.status != "submitted":
        raise HTTPException(status_code=400, detail=f"Cannot accept a bid with status '{bid.status}'")

    transaction = Transaction(
        listing_id=bid.listing_id,
        buyer_id=bid.bidder_id,
        seller_id=listing.seller_id,
        quantity=bid.quantity,
        agreed_price=bid.bid_price,
        status="accepted",
    )
    db.add(transaction)
    db.flush()

    bid.status = "accepted"
    bid.decided_at = datetime.utcnow()
    bid.decided_by_user_id = current_user.id
    bid.resulting_transaction_id = transaction.id

    db.commit()
    db.refresh(bid)
    return bid


@app.put("/auction-bids/{bid_id}/reject")
def reject_auction_bid(
    bid_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    bid = db.query(SecondaryAuctionBid).filter(SecondaryAuctionBid.id == bid_id).first()
    if bid is None:
        raise HTTPException(status_code=404, detail="Bid not found")

    listing = db.query(ListingModel).filter(ListingModel.id == bid.listing_id).first()
    _require_auction_seller_or_admin(listing, current_user)

    if bid.status != "submitted":
        raise HTTPException(status_code=400, detail=f"Cannot reject a bid with status '{bid.status}'")

    bid.status = "rejected"
    bid.decided_at = datetime.utcnow()
    bid.decided_by_user_id = current_user.id

    db.commit()
    db.refresh(bid)
    return bid


@app.put("/auction-bids/{bid_id}/withdraw")
def withdraw_auction_bid(
    bid_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    bid = db.query(SecondaryAuctionBid).filter(SecondaryAuctionBid.id == bid_id).first()
    if bid is None:
        raise HTTPException(status_code=404, detail="Bid not found")

    if current_user.id != bid.bidder_id:
        raise HTTPException(status_code=403, detail="Only the bidder can withdraw their own bid")

    if bid.status != "submitted":
        raise HTTPException(status_code=400, detail=f"Cannot withdraw a bid with status '{bid.status}'")

    bid.status = "withdrawn"
    bid.decided_at = datetime.utcnow()
    bid.decided_by_user_id = current_user.id

    db.commit()
    db.refresh(bid)
    return bid


def _trigger_compliance_rule_change_alerts(rule, db):
    """
    Called after a ComplianceRule is edited (PUT /compliance-rules/{id}).
    Finds every still-open transaction whose most recent Compliance
    Decision Ledger entry cited this exact rule code, re-runs the real
    assess_compliance() verdict against the rule's new wording, and
    creates one ComplianceRuleChangeAlert only where the outcome actually
    changed. Purely informational - mirrors DealAlert's trigger pattern
    (M31), never blocks or changes the transaction itself.
    """
    terminal_statuses = {"completed", "rejected", "cancelled"}

    candidate_entries = db.query(ComplianceDecisionLedger).filter(
        ComplianceDecisionLedger.applicable_rule_codes.like(f"%{rule.rule_code}%")
    ).order_by(ComplianceDecisionLedger.decided_at.desc()).all()

    latest_entry_by_transaction = {}
    for entry in candidate_entries:
        if entry.transaction_id in latest_entry_by_transaction:
            continue
        latest_entry_by_transaction[entry.transaction_id] = entry

    for transaction_id, last_entry in latest_entry_by_transaction.items():
        cited_codes = json.loads(last_entry.applicable_rule_codes)
        if rule.rule_code not in cited_codes:
            continue

        transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
        if transaction is None or transaction.status in terminal_statuses:
            continue

        buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
        listing = db.query(ListingModel).filter(ListingModel.id == transaction.listing_id).first()
        if buyer is None or listing is None:
            continue

        # "Current known state" is the most recent rule-change alert
        # already raised for this transaction (if any), not always the
        # original Ledger entry - the Ledger is append-only and only
        # gains a new row on a real transaction lifecycle event (creation,
        # a status change), never on a rule edit. Without this, a second,
        # unrelated rule edit would keep comparing against the same
        # now-stale Ledger snapshot and wrongly re-alert on a change that
        # already has an alert.
        most_recent_alert = db.query(ComplianceRuleChangeAlert).filter(
            ComplianceRuleChangeAlert.transaction_id == transaction_id
        ).order_by(ComplianceRuleChangeAlert.created_at.desc()).first()

        previous_status = most_recent_alert.new_decision_status if most_recent_alert else last_entry.decision_status
        previous_explanation = most_recent_alert.new_explanation if most_recent_alert else last_entry.explanation

        fresh_verdict = assess_compliance(buyer, listing, db)

        if fresh_verdict["status"] == previous_status:
            continue

        alert = ComplianceRuleChangeAlert(
            compliance_rule_id=rule.id,
            transaction_id=transaction.id,
            buyer_id=transaction.buyer_id,
            listing_id=transaction.listing_id,
            previous_decision_status=previous_status,
            new_decision_status=fresh_verdict["status"],
            previous_explanation=previous_explanation,
            new_explanation=fresh_verdict["explanation"],
            created_at=datetime.utcnow(),
        )
        db.add(alert)

    db.commit()


@app.get("/rule-change-alerts")
def list_rule_change_alerts(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        alerts = db.query(ComplianceRuleChangeAlert).order_by(ComplianceRuleChangeAlert.created_at.desc()).all()
    else:
        alerts = db.query(ComplianceRuleChangeAlert).filter(
            ComplianceRuleChangeAlert.buyer_id == current_user.id
        ).order_by(ComplianceRuleChangeAlert.created_at.desc()).all()

    return {
        "alerts": [
            {
                "id": a.id,
                "compliance_rule_id": a.compliance_rule_id,
                "transaction_id": a.transaction_id,
                "listing_id": a.listing_id,
                "buyer_id": a.buyer_id,
                "previous_decision_status": a.previous_decision_status,
                "new_decision_status": a.new_decision_status,
                "previous_explanation": a.previous_explanation,
                "new_explanation": a.new_explanation,
                "is_read": a.is_read,
                "read_at": a.read_at.isoformat() if a.read_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ]
    }


@app.get("/rule-change-alerts/{alert_id}")
def get_rule_change_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    alert = db.query(ComplianceRuleChangeAlert).filter(ComplianceRuleChangeAlert.id == alert_id).first()

    if alert is None:
        raise HTTPException(status_code=404, detail="Rule change alert not found")

    if current_user.account_type != "admin" and current_user.id != alert.buyer_id:
        raise HTTPException(status_code=403, detail="You can only view your own rule change alerts")

    return {
        "id": alert.id,
        "compliance_rule_id": alert.compliance_rule_id,
        "transaction_id": alert.transaction_id,
        "listing_id": alert.listing_id,
        "buyer_id": alert.buyer_id,
        "previous_decision_status": alert.previous_decision_status,
        "new_decision_status": alert.new_decision_status,
        "previous_explanation": alert.previous_explanation,
        "new_explanation": alert.new_explanation,
        "is_read": alert.is_read,
        "read_at": alert.read_at.isoformat() if alert.read_at else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


@app.put("/rule-change-alerts/{alert_id}/mark-read")
def mark_rule_change_alert_read(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    alert = db.query(ComplianceRuleChangeAlert).filter(ComplianceRuleChangeAlert.id == alert_id).first()

    if alert is None:
        raise HTTPException(status_code=404, detail="Rule change alert not found")

    if current_user.id != alert.buyer_id:
        raise HTTPException(status_code=403, detail="You can only mark your own rule change alerts as read")

    alert.is_read = True
    alert.read_at = datetime.utcnow()
    db.commit()
    db.refresh(alert)

    return {
        "id": alert.id,
        "is_read": alert.is_read,
        "read_at": alert.read_at.isoformat() if alert.read_at else None,
    }


@app.get("/transactions/{transaction_id}/dependency-changes")
def get_transaction_dependency_changes(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    M27 gap-closure item, 2026-09-25 - the Deal Dependency Graph, the
    third and final M27 piece. Per the project's own already-recorded
    design: a diff layer over M15's Liquidity Path Engine, not a new
    graph structure. Every call to the existing liquidity-path endpoints
    already persists a full snapshot of LiquidityPathStep rows tagged
    with a fresh run_id; this endpoint takes the most recent EXISTING
    snapshot as "before", computes and persists one more fresh snapshot
    as "after" (reusing build_liquidity_path exactly as the existing
    endpoint does), and diffs them step by step (matched by step_type,
    the stable identifier for each fixed pipeline stage). For every step
    whose complete/determinability/reasons actually changed, it walks
    the real blocking_step_id edges the engine already produces (forward,
    from that step to whatever steps in the new run list it as their
    blocker) to report exactly which downstream steps are affected -
    read-only, on-demand, no new trigger points or background jobs,
    matching KEVO's existing pattern of computing everything live.
    """
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if current_user.account_type != "admin" and current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(status_code=403, detail="You are not a party to this transaction")

    listing = db.query(ListingModel).filter(ListingModel.id == transaction.listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found for this transaction")

    previous_latest_row = db.query(LiquidityPathStep).filter(
        LiquidityPathStep.transaction_id == transaction_id
    ).order_by(LiquidityPathStep.id.desc()).first()

    previous_run_id = previous_latest_row.run_id if previous_latest_row else None
    previous_steps = []
    if previous_run_id is not None:
        previous_steps = db.query(LiquidityPathStep).filter(
            LiquidityPathStep.transaction_id == transaction_id,
            LiquidityPathStep.run_id == previous_run_id
        ).all()

    result = build_liquidity_path(listing, db, transaction_id=transaction.id)
    ownership_record_id = result["ownership_record_id"]
    new_run_id = uuid.uuid4().hex
    computed_at = date.today()

    new_steps = []
    previous_step_id_in_new_run = None

    for step in result["steps"]:
        row = LiquidityPathStep(
            listing_id=listing.id,
            ownership_record_id=ownership_record_id,
            transaction_id=transaction.id,
            run_id=new_run_id,
            computed_at=computed_at,
            step_type=step["step_type"],
            sequence_position=step["sequence_position"],
            required=step["required"],
            complete=step["complete"],
            evidence_reference_type=step["evidence_reference_type"],
            evidence_reference_id=step["evidence_reference_id"],
            responsible_party=step["responsible_party"],
            blocking_step_id=previous_step_id_in_new_run,
            completion_trigger=step["completion_trigger"],
            determinability=step["determinability"],
            reasons=step["reasons"],
            source_milestone=step["source_milestone"]
        )
        db.add(row)
        db.flush()
        previous_step_id_in_new_run = row.id
        new_steps.append(row)

    db.commit()

    if previous_run_id is None:
        return {
            "transaction_id": transaction_id,
            "previous_run_id": None,
            "new_run_id": new_run_id,
            "message": "No prior snapshot existed for this transaction - this run establishes the baseline. Call this endpoint again after something changes to see a real diff.",
            "changed_steps": []
        }

    previous_by_type = {s.step_type: s for s in previous_steps}

    children_by_blocking_id = {}
    for s in new_steps:
        if s.blocking_step_id is not None:
            children_by_blocking_id.setdefault(s.blocking_step_id, []).append(s)

    def walk_downstream(start_step_id):
        downstream = []
        seen = set()
        frontier = [start_step_id]
        while frontier:
            current_id = frontier.pop()
            for child in children_by_blocking_id.get(current_id, []):
                if child.id in seen:
                    continue
                seen.add(child.id)
                downstream.append(child)
                frontier.append(child.id)
        downstream.sort(key=lambda s: s.sequence_position)
        return downstream

    changed_steps = []
    for new_step in new_steps:
        old_step = previous_by_type.get(new_step.step_type)
        if old_step is None:
            continue
        if (
            old_step.complete == new_step.complete
            and old_step.determinability == new_step.determinability
            and old_step.reasons == new_step.reasons
        ):
            continue

        downstream_steps = walk_downstream(new_step.id)

        changed_steps.append({
            "step_type": new_step.step_type,
            "sequence_position": new_step.sequence_position,
            "previous": {
                "complete": old_step.complete,
                "determinability": old_step.determinability,
                "reasons": old_step.reasons,
            },
            "current": {
                "complete": new_step.complete,
                "determinability": new_step.determinability,
                "reasons": new_step.reasons,
            },
            "downstream_steps_affected": [
                {"step_type": d.step_type, "sequence_position": d.sequence_position}
                for d in downstream_steps
            ]
        })

    return {
        "transaction_id": transaction_id,
        "previous_run_id": previous_run_id,
        "new_run_id": new_run_id,
        "changed_steps": changed_steps
    }


class MessageCreate(BaseModel):
    body: str


@app.post("/transactions/{transaction_id}/messages")
def create_message(
    transaction_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    M31 gap-closure item, 2026-09-25 - send a message on a real
    transaction. Party-only (buyer or seller), never admin - an admin
    has no legitimate reason to send on someone else's behalf. Gated by
    _check_buyer_communication_eligible(): if the transaction's buyer
    fails the narrow buyer-only eligibility check, sending is rejected
    for EITHER party, not just the buyer, since the underlying concern
    is whether communication with this buyer is permitted at all.
    """
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )

    if current_user.id not in (transaction.buyer_id, transaction.seller_id):
        raise HTTPException(
            status_code=403,
            detail="You are not a party to this transaction"
        )

    buyer = db.query(UserModel).filter(UserModel.id == transaction.buyer_id).first()
    listing = db.query(ListingModel).filter(ListingModel.id == transaction.listing_id).first()

    eligible, reason = _check_buyer_communication_eligible(buyer, listing, db)
    if not eligible:
        raise HTTPException(
            status_code=403,
            detail=f"Messaging is gated: {reason}"
        )

    message = Message(
        transaction_id=transaction.id,
        sender_id=current_user.id,
        body=payload.body,
        created_at=datetime.utcnow(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    return {
        "id": message.id,
        "transaction_id": message.transaction_id,
        "sender_id": message.sender_id,
        "body": message.body,
        "created_at": message.created_at
    }


@app.get("/transactions/{transaction_id}/messages")
def list_messages(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    M31 gap-closure item, 2026-09-25 - read a transaction's message
    thread. Party-or-admin, matching every other transaction-scoped read
    endpoint in KEVO (deal room, deal health, risk radar, liquidity
    path). Read access itself is never gated - only sending is.
    """
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id
    ).first()

    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="Transaction not found"
        )

    is_party = current_user.id in (transaction.buyer_id, transaction.seller_id)
    if not is_party and current_user.account_type != "admin":
        raise HTTPException(
            status_code=403,
            detail="You are not a party to this transaction"
        )

    messages = db.query(Message).filter(
        Message.transaction_id == transaction_id
    ).order_by(Message.created_at.asc()).all()

    return [
        {
            "id": m.id,
            "transaction_id": m.transaction_id,
            "sender_id": m.sender_id,
            "body": m.body,
            "created_at": m.created_at
        }
        for m in messages
    ]


class LiquidityCommitmentCreate(BaseModel):
    buyer_id: int
    company: str
    asset_type: str
    min_quantity: int | None = None
    max_quantity: int | None = None
    min_price: float | None = None
    max_price: float | None = None
    expiration_date: date | None = None
    conditions: str | None = None


def _serialize_commitment(c: LiquidityCommitment):
    return {
        "id": c.id,
        "buyer_id": c.buyer_id,
        "company": c.company,
        "asset_type": c.asset_type,
        "min_quantity": c.min_quantity,
        "max_quantity": c.max_quantity,
        "min_price": c.min_price,
        "max_price": c.max_price,
        "expiration_date": c.expiration_date,
        "conditions": c.conditions,
        "status": c.status,
        "created_at": c.created_at,
        "disclaimer": (
            "This is a non-binding expression of standing interest, not "
            "an offer to buy and not a binding commitment. KEVO does not "
            "match or act on it automatically."
        ),
    }


@app.post("/liquidity-commitments")
def create_liquidity_commitment(
    payload: LiquidityCommitmentCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    """
    M31 gap-closure item, 2026-09-25 - Liquidity Commitment, the fourth of
    M31's remaining pieces. Self-submit only (caller must be the named
    buyer, or admin) - same owner pattern as create_buyer_interest.
    Deliberately pure data capture: nothing here matches or notifies
    anyone automatically (confirmed with Eze 2026-09-25, to avoid edging
    toward resting-limit-order territory the way M16B's original full
    scope did before it was narrowed).
    """
    if current_user.account_type != "admin" and current_user.id != payload.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only create a liquidity commitment for yourself"
        )

    if payload.min_quantity is not None and payload.max_quantity is not None:
        if payload.min_quantity > payload.max_quantity:
            raise HTTPException(
                status_code=400,
                detail="min_quantity cannot be greater than max_quantity"
            )

    if payload.min_price is not None and payload.max_price is not None:
        if payload.min_price > payload.max_price:
            raise HTTPException(
                status_code=400,
                detail="min_price cannot be greater than max_price"
            )

    commitment = LiquidityCommitment(
        buyer_id=payload.buyer_id,
        company=payload.company,
        asset_type=payload.asset_type,
        min_quantity=payload.min_quantity,
        max_quantity=payload.max_quantity,
        min_price=payload.min_price,
        max_price=payload.max_price,
        expiration_date=payload.expiration_date,
        conditions=payload.conditions,
        status="active",
        created_at=datetime.utcnow(),
    )
    db.add(commitment)
    db.commit()
    db.refresh(commitment)

    return _serialize_commitment(commitment)


@app.get("/liquidity-commitments")
def list_liquidity_commitments(
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    if current_user.account_type == "admin":
        commitments = db.query(LiquidityCommitment).all()
    else:
        commitments = db.query(LiquidityCommitment).filter(
            LiquidityCommitment.buyer_id == current_user.id
        ).all()

    return [_serialize_commitment(c) for c in commitments]


@app.get("/liquidity-commitments/{commitment_id}")
def get_liquidity_commitment(
    commitment_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    commitment = db.query(LiquidityCommitment).filter(
        LiquidityCommitment.id == commitment_id
    ).first()

    if commitment is None:
        raise HTTPException(
            status_code=404,
            detail="Liquidity commitment not found"
        )

    if current_user.account_type != "admin" and current_user.id != commitment.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only view your own liquidity commitments"
        )

    return _serialize_commitment(commitment)


@app.put("/liquidity-commitments/{commitment_id}/withdraw")
def withdraw_liquidity_commitment(
    commitment_id: int,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_user)
):
    commitment = db.query(LiquidityCommitment).filter(
        LiquidityCommitment.id == commitment_id
    ).first()

    if commitment is None:
        raise HTTPException(
            status_code=404,
            detail="Liquidity commitment not found"
        )

    if current_user.id != commitment.buyer_id:
        raise HTTPException(
            status_code=403,
            detail="You can only withdraw your own liquidity commitments"
        )

    commitment.status = "withdrawn"
    db.commit()
    db.refresh(commitment)

    return _serialize_commitment(commitment)
