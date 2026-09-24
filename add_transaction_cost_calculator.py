import ast

with open("app.py", "r") as f:
    content = f.read()

# 1. Add Field to pydantic import
old_import = "from pydantic import BaseModel"
new_import = "from pydantic import BaseModel, Field"
assert content.count(old_import) == 1, "pydantic import: match count != 1"
content = content.replace(old_import, new_import)

# 2. Insert new Pydantic model + endpoint after get_transaction, before ownership verify
old_anchor = '''            "status": transaction.status,
            "settlement_currency": transaction.settlement_currency
        }
    }      


@app.put("/ownership/{ownership_id}/verify")'''

new_anchor = '''            "status": transaction.status,
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


@app.put("/ownership/{ownership_id}/verify")'''

assert content.count(old_anchor) == 1, "transaction cost calculator anchor: match count != 1"
content = content.replace(old_anchor, new_anchor)

ast.parse(content)

with open("app.py", "w") as f:
    f.write(content)

print("app.py updated: TransactionCostEstimateRequest model + POST /transaction-cost-estimate endpoint added, Field imported, syntax OK")
