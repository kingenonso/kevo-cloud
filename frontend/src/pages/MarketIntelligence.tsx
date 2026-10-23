import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch } from "@/lib/auth"
import { formatMoney } from "@/lib/format"
import { formatLabel } from "@/lib/status"

type PriceRange = {
  status: string
  message?: string
  observed_price_range: { low: number; high: number; sample_size: number; basis: string } | null
  current_ask_range: { low: number; high: number; distinct_seller_count: number; basis: string } | null
  current_demand_range: { low: number; high: number; distinct_buyer_count: number; basis: string } | null
  disclaimer?: string
}

type DemandHeatmap = {
  status: string
  message?: string
  cells?: Array<{ price_band_low: number; price_band_high: number; jurisdiction: string | null; buyer_count: number; total_desired_quantity: number }>
}

type DemandCurve = {
  status: string
  message?: string
  points?: Array<{ price_at_or_above: number; cumulative_quantity: number; distinct_buyers_in_step: number }>
}

type LiquidityAggregation = {
  status: string
  message?: string
  active_buyer_count?: number
  total_desired_quantity?: number
  active_seller_count?: number
  total_available_quantity?: number
  aggregate_status?: string
  reason?: string
}

export function MarketIntelligencePage() {
  const [company, setCompany] = useState("")
  const [assetType, setAssetType] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [priceRange, setPriceRange] = useState<PriceRange | null>(null)
  const [heatmap, setHeatmap] = useState<DemandHeatmap | null>(null)
  const [curve, setCurve] = useState<DemandCurve | null>(null)
  const [aggregation, setAggregation] = useState<LiquidityAggregation | null>(null)

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!company.trim() || !assetType.trim()) return
    setLoading(true)
    setError(null)
    setSubmitted(true)
    const qs = `?company=${encodeURIComponent(company)}&asset_type=${encodeURIComponent(assetType)}`
    try {
      const [prResp, hmResp, dcResp, laResp] = await Promise.all([
        apiFetch(`/price-range${qs}`),
        apiFetch(`/demand-heatmap${qs}`),
        apiFetch(`/demand-curve${qs}`),
        apiFetch(`/liquidity-aggregation${qs}`),
      ])
      setPriceRange(prResp.ok ? ((await prResp.json()) as PriceRange) : null)
      setHeatmap(hmResp.ok ? ((await hmResp.json()) as DemandHeatmap) : null)
      setCurve(dcResp.ok ? ((await dcResp.json()) as DemandCurve) : null)
      setAggregation(laResp.ok ? ((await laResp.json()) as LiquidityAggregation) : null)
    } catch {
      setError("Could not reach the server.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Market Intelligence
        </p>
        <p className="mb-4 text-sm text-muted-foreground">
          Informational only, based solely on real data already on KEVO. Never a prediction,
          never a single confident price, and never investment advice. Figures are withheld
          below a minimum sample size to avoid false precision or re-identification.
        </p>
        <form onSubmit={handleSearch} className="flex flex-wrap gap-3">
          <Input placeholder="Company" value={company} onChange={(e) => setCompany(e.target.value)} className="max-w-xs" />
          <Input placeholder="Asset Type (e.g. common_stock)" value={assetType} onChange={(e) => setAssetType(e.target.value)} className="max-w-xs" />
          <Button type="submit" disabled={loading}>
            {loading ? "Loading..." : "Search"}
          </Button>
        </form>
        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      </div>

      {submitted && !loading && (
        <>
          <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
            <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Price Range</p>
            {!priceRange || priceRange.status === "insufficient_data" ? (
              <p className="text-sm text-muted-foreground">{priceRange?.message ?? "No data available."}</p>
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                {priceRange.observed_price_range && (
                  <div className="rounded-xl border border-border p-4 text-sm">
                    <p className="mb-1 text-xs text-muted-foreground">Observed Completed-Transaction Price</p>
                    <p className="font-medium text-foreground">
                      {formatMoney(priceRange.observed_price_range.low)} – {formatMoney(priceRange.observed_price_range.high)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">n={priceRange.observed_price_range.sample_size}</p>
                  </div>
                )}
                {priceRange.current_ask_range && (
                  <div className="rounded-xl border border-border p-4 text-sm">
                    <p className="mb-1 text-xs text-muted-foreground">Current Asking Price</p>
                    <p className="font-medium text-foreground">
                      {formatMoney(priceRange.current_ask_range.low)} – {formatMoney(priceRange.current_ask_range.high)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">{priceRange.current_ask_range.distinct_seller_count} sellers</p>
                  </div>
                )}
                {priceRange.current_demand_range && (
                  <div className="rounded-xl border border-border p-4 text-sm">
                    <p className="mb-1 text-xs text-muted-foreground">Current Buyer Demand</p>
                    <p className="font-medium text-foreground">
                      {formatMoney(priceRange.current_demand_range.low)} – {formatMoney(priceRange.current_demand_range.high)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">{priceRange.current_demand_range.distinct_buyer_count} buyers</p>
                  </div>
                )}
              </div>
            )}
            {priceRange?.disclaimer && <p className="mt-4 text-xs text-muted-foreground">{priceRange.disclaimer}</p>}
          </div>

          <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
            <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Demand Heatmap</p>
            {!heatmap || heatmap.status === "insufficient_data" || !heatmap.cells?.length ? (
              <p className="text-sm text-muted-foreground">{heatmap?.message ?? "No data available."}</p>
            ) : (
              <div className="divide-y divide-border">
                <div className="grid grid-cols-4 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <div>Price Band</div>
                  <div>Jurisdiction</div>
                  <div>Buyers</div>
                  <div>Desired Quantity</div>
                </div>
                {heatmap.cells.map((cell, i) => (
                  <div key={i} className="grid grid-cols-4 items-center gap-4 py-3 text-sm">
                    <div className="text-foreground">{formatMoney(cell.price_band_low)} – {formatMoney(cell.price_band_high)}</div>
                    <div className="text-muted-foreground">{cell.jurisdiction ? formatLabel(cell.jurisdiction) : "Multiple (aggregated)"}</div>
                    <div className="text-muted-foreground">{cell.buyer_count}</div>
                    <div className="text-muted-foreground">{cell.total_desired_quantity}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
            <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Demand Curve</p>
            {!curve || curve.status === "insufficient_data" || !curve.points?.length ? (
              <p className="text-sm text-muted-foreground">{curve?.message ?? "No data available."}</p>
            ) : (
              <div className="divide-y divide-border">
                <div className="grid grid-cols-3 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <div>Price At Or Above</div>
                  <div>Cumulative Quantity</div>
                  <div>Distinct Buyers In Step</div>
                </div>
                {curve.points.map((point, i) => (
                  <div key={i} className="grid grid-cols-3 items-center gap-4 py-3 text-sm">
                    <div className="text-foreground">{formatMoney(point.price_at_or_above)}</div>
                    <div className="text-muted-foreground">{point.cumulative_quantity}</div>
                    <div className="text-muted-foreground">{point.distinct_buyers_in_step}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
            <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Aggregate Supply/Demand</p>
            {!aggregation || aggregation.status === "insufficient_data" ? (
              <p className="text-sm text-muted-foreground">{aggregation?.message ?? "No data available."}</p>
            ) : (
              <>
                <div className="mb-4 grid grid-cols-2 gap-6 text-sm sm:grid-cols-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Active Buyers</p>
                    <p className="mt-1 font-mono text-foreground">{aggregation.active_buyer_count}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Total Desired Quantity</p>
                    <p className="mt-1 font-mono text-foreground">{aggregation.total_desired_quantity}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Active Sellers</p>
                    <p className="mt-1 font-mono text-foreground">{aggregation.active_seller_count}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Total Available Quantity</p>
                    <p className="mt-1 font-mono text-foreground">{aggregation.total_available_quantity}</p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground">{aggregation.reason}</p>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
