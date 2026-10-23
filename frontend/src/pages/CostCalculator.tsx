import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch } from "@/lib/auth"
import { formatMoney } from "@/lib/format"
import { formatLabel } from "@/lib/status"

type EstimateResult = {
  transaction_id: number | null
  currency: string
  headline_valuation: number
  breakdown: Record<string, number>
  total_friction: number
  net_proceeds: number
}

export function CostCalculatorPage() {
  const [transactionId, setTransactionId] = useState("")
  const [headlineValuation, setHeadlineValuation] = useState("")
  const [legalFee, setLegalFee] = useState("0")
  const [platformFee, setPlatformFee] = useState("0")
  const [settlementFee, setSettlementFee] = useState("0")
  const [custodyFee, setCustodyFee] = useState("0")
  const [fxFee, setFxFee] = useState("0")
  const [transferFee, setTransferFee] = useState("0")
  const [taxesOther, setTaxesOther] = useState("0")

  const [result, setResult] = useState<EstimateResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const response = await apiFetch("/transaction-cost-estimate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transaction_id: transactionId ? Number(transactionId) : null,
          headline_valuation: headlineValuation ? Number(headlineValuation) : null,
          legal_fee: Number(legalFee) || 0,
          platform_fee: Number(platformFee) || 0,
          settlement_fee: Number(settlementFee) || 0,
          custody_fee: Number(custodyFee) || 0,
          fx_fee: Number(fxFee) || 0,
          transfer_fee: Number(transferFee) || 0,
          taxes_other: Number(taxesOther) || 0,
        }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setError(data?.detail ?? "Could not compute this estimate.")
        return
      }
      setResult((await response.json()) as EstimateResult)
    } catch {
      setError("Could not reach the server.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Transaction Cost Estimate
        </p>
        <p className="mb-6 text-sm text-muted-foreground">
          Pure arithmetic: your headline valuation minus every friction cost you enter
          equals estimated net proceeds. KEVO doesn't assume or set any fee, including its
          own "platform fee" — every figure below is one you supply yourself.
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Transaction ID (optional — derives valuation &amp; currency)
              </label>
              <Input type="number" value={transactionId} onChange={(e) => setTransactionId(e.target.value)} />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Headline Valuation ($) {transactionId ? "(optional override)" : ""}
              </label>
              <Input type="number" min="0" step="0.01" value={headlineValuation} onChange={(e) => setHeadlineValuation(e.target.value)} required={!transactionId} />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            {[
              ["Legal Fee", legalFee, setLegalFee],
              ["Platform Fee", platformFee, setPlatformFee],
              ["Settlement Fee", settlementFee, setSettlementFee],
              ["Custody Fee", custodyFee, setCustodyFee],
              ["FX Fee", fxFee, setFxFee],
              ["Transfer Fee", transferFee, setTransferFee],
              ["Taxes / Other", taxesOther, setTaxesOther],
            ].map(([label, value, setter]) => (
              <div key={label as string}>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {label as string} ($)
                </label>
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={value as string}
                  onChange={(e) => (setter as (v: string) => void)(e.target.value)}
                />
              </div>
            ))}
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={loading}>
            {loading ? "Calculating..." : "Calculate"}
          </Button>
        </form>
      </div>

      {result && (
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Result</p>
          <div className="mb-6 grid grid-cols-3 gap-6 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Headline Valuation</p>
              <p className="mt-1 font-mono text-foreground">{formatMoney(result.headline_valuation, result.currency)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Total Friction</p>
              <p className="mt-1 font-mono text-foreground">{formatMoney(result.total_friction, result.currency)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Net Proceeds</p>
              <p className="mt-1 font-mono text-foreground">{formatMoney(result.net_proceeds, result.currency)}</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Object.entries(result.breakdown).map(([key, value]) => (
              <div key={key} className="text-sm">
                <p className="text-xs text-muted-foreground">{formatLabel(key)}</p>
                <p className="font-mono text-foreground">{formatMoney(value, result.currency)}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
