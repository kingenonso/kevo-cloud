import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch } from "@/lib/auth"
import { toQueryString } from "@/lib/api"
import { useAuth } from "@/contexts/AuthContext"
import { formatMoney } from "@/lib/format"
import { formatLabel } from "@/lib/status"

// M33C (first slice) - Private Market Data & Insights, a reporting
// dashboard over data KEVO already produces and already exposes
// publicly, unauthenticated, via /price-range, /demand-heatmap,
// /demand-curve, and /liquidity-aggregation (M16/M16B's own deliberate
// design - identical output for any caller). This page composes the
// same four engines through one authenticated endpoint,
// GET /insights/dashboard, which also gives KEVO a named relationship
// with the external customer (a VC, family office, or issuing company)
// and a query log - groundwork for an eventual paid relationship, not a
// paywall on data that was already public.

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

type Dashboard = {
  company: string
  asset_type: string
  price_range: PriceRange
  demand_heatmap: DemandHeatmap
  demand_curve: DemandCurve
  liquidity_aggregation: LiquidityAggregation
}

export function InsightsDashboardPage() {
  const { user } = useAuth()

  const [company, setCompany] = useState("")
  const [assetType, setAssetType] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)

  const notSubscriber = user && user.account_type !== "insights_subscriber"

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!company.trim() || !assetType.trim()) return
    setLoading(true)
    setError(null)
    setSubmitted(true)
    try {
      const response = await apiFetch(`/insights/dashboard${toQueryString({ company, asset_type: assetType })}`)
      if (!response.ok) {
        setError(response.status === 403 ? "This account is not provisioned for Insights access." : "Could not load the dashboard.")
        setDashboard(null)
        return
      }
      setDashboard((await response.json()) as Dashboard)
    } catch {
      setError("Could not reach the server.")
    } finally {
      setLoading(false)
    }
  }

  if (notSubscriber) {
    return (
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          This account is not provisioned for Insights Dashboard access. An admin provisions
          Insights subscriber accounts via the Platform Access admin page.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Insights Dashboard
        </p>
        <p className="mb-4 text-sm text-muted-foreground">
          Informational only, based solely on real, anonymized data already on KEVO. The same
          underlying figures are also independently available, unauthenticated, at
          /price-range, /demand-heatmap, /demand-curve, and /liquidity-aggregation - this
          dashboard is a packaged view for your organization, not a different data set.
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

      {submitted && !loading && dashboard && (
        <>
          <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
            <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Price Range</p>
            {dashboard.price_range.status === "insufficient_data" ? (
              <p className="text-sm text-muted-foreground">{dashboard.price_range.message ?? "No data available."}</p>
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                {dashboard.price_range.observed_price_range && (
                  <div className="rounded-xl border border-border p-4 text-sm">
                    <p className="mb-1 text-xs text-muted-foreground">Observed Completed-Transaction Price</p>
                    <p className="font-medium text-foreground">
                      {formatMoney(dashboard.price_range.observed_price_range.low)} – {formatMoney(dashboard.price_range.observed_price_range.high)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">n={dashboard.price_range.observed_price_range.sample_size}</p>
                  </div>
                )}
                {dashboard.price_range.current_ask_range && (
                  <div className="rounded-xl border border-border p-4 text-sm">
                    <p className="mb-1 text-xs text-muted-foreground">Current Asking Price</p>
                    <p className="font-medium text-foreground">
                      {formatMoney(dashboard.price_range.current_ask_range.low)} – {formatMoney(dashboard.price_range.current_ask_range.high)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">{dashboard.price_range.current_ask_range.distinct_seller_count} sellers</p>
                  </div>
                )}
                {dashboard.price_range.current_demand_range && (
                  <div className="rounded-xl border border-border p-4 text-sm">
                    <p className="mb-1 text-xs text-muted-foreground">Current Buyer Demand</p>
                    <p className="font-medium text-foreground">
                      {formatMoney(dashboard.price_range.current_demand_range.low)} – {formatMoney(dashboard.price_range.current_demand_range.high)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">{dashboard.price_range.current_demand_range.distinct_buyer_count} buyers</p>
                  </div>
                )}
              </div>
            )}
            {dashboard.price_range.disclaimer && <p className="mt-4 text-xs text-muted-foreground">{dashboard.price_range.disclaimer}</p>}
          </div>

          <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
            <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Demand Heatmap</p>
            {dashboard.demand_heatmap.status === "insufficient_data" || !dashboard.demand_heatmap.cells?.length ? (
              <p className="text-sm text-muted-foreground">{dashboard.demand_heatmap.message ?? "No data available."}</p>
            ) : (
              <div className="divide-y divide-border">
                <div className="grid grid-cols-4 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <div>Price Band</div>
                  <div>Jurisdiction</div>
                  <div>Buyers</div>
                  <div>Desired Quantity</div>
                </div>
                {dashboard.demand_heatmap.cells.map((cell, i) => (
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
            {dashboard.demand_curve.status === "insufficient_data" || !dashboard.demand_curve.points?.length ? (
              <p className="text-sm text-muted-foreground">{dashboard.demand_curve.message ?? "No data available."}</p>
            ) : (
              <div className="divide-y divide-border">
                <div className="grid grid-cols-3 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <div>Price At Or Above</div>
                  <div>Cumulative Quantity</div>
                  <div>Distinct Buyers In Step</div>
                </div>
                {dashboard.demand_curve.points.map((point, i) => (
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
            {dashboard.liquidity_aggregation.status === "insufficient_data" ? (
              <p className="text-sm text-muted-foreground">{dashboard.liquidity_aggregation.message ?? "No data available."}</p>
            ) : (
              <>
                <div className="mb-4 grid grid-cols-2 gap-6 text-sm sm:grid-cols-4">
                  <div>
                    <p className="text-xs text-muted-foreground">Active Buyers</p>
                    <p className="mt-1 font-mono text-foreground">{dashboard.liquidity_aggregation.active_buyer_count}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Total Desired Quantity</p>
                    <p className="mt-1 font-mono text-foreground">{dashboard.liquidity_aggregation.total_desired_quantity}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Active Sellers</p>
                    <p className="mt-1 font-mono text-foreground">{dashboard.liquidity_aggregation.active_seller_count}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Total Available Quantity</p>
                    <p className="mt-1 font-mono text-foreground">{dashboard.liquidity_aggregation.total_available_quantity}</p>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground">{dashboard.liquidity_aggregation.reason}</p>
              </>
            )}
          </div>
        </>
      )}
    </div>
  )
}
