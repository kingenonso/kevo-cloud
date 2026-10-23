import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/auth"
import { useAuth } from "@/contexts/AuthContext"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { formatLabel } from "@/lib/status"

type Step = {
  id: number
  step_type: string
  required: boolean
  complete: boolean
  determinability: string
  reasons: string
}

type ListingResult = {
  listing_id: number
  company: string
  asset_type: string
  summary: string
  complete_count: number
  total_steps: number
  cannot_determine_count: number
  steps: Step[]
}

type PortfolioLiquidity = {
  seller_id: number
  listing_count: number
  listings_fully_complete: number
  next_blocking_step_counts: Record<string, number>
  listings: ListingResult[]
}

export function LiquidityRoadmapPage() {
  const { user } = useAuth()
  const [data, setData] = useState<PortfolioLiquidity | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    if (!user) return
    const userId = user.id
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const response = await apiFetch(`/portfolio-liquidity/seller/${userId}`)
        if (!response.ok) throw new Error()
        if (!cancelled) setData((await response.json()) as PortfolioLiquidity)
      } catch {
        if (!cancelled) setError("Could not load your liquidity roadmap.")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [user])

  if (loading) return <p className="text-sm text-muted-foreground">Loading...</p>
  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!data) return null

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Portfolio Overview
        </p>
        <div className="grid grid-cols-2 gap-6 text-sm sm:grid-cols-3">
          <div>
            <p className="text-xs text-muted-foreground">Listings</p>
            <p className="mt-1 font-mono text-foreground">{data.listing_count}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Fully Complete</p>
            <p className="mt-1 font-mono text-foreground">{data.listings_fully_complete}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Needs Attention</p>
            <p className="mt-1 font-mono text-foreground">{data.listing_count - data.listings_fully_complete}</p>
          </div>
        </div>
        {Object.keys(data.next_blocking_step_counts).length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs text-muted-foreground">Most common next blocker across your listings</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(data.next_blocking_step_counts).map(([step, count]) => (
                <span key={step} className="rounded-full border border-border px-3 py-1 text-xs text-foreground">
                  {formatLabel(step)} ({count})
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {data.listings.length === 0 ? (
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <p className="text-sm text-muted-foreground">You have no listings yet.</p>
        </div>
      ) : (
        data.listings.map((l) => (
          <div key={l.listing_id} className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
            <button
              type="button"
              onClick={() => setExpanded(expanded === l.listing_id ? null : l.listing_id)}
              className="flex w-full items-center justify-between px-8 py-6 text-left"
            >
              <div>
                <p className="font-medium text-foreground">{l.company} ({l.asset_type})</p>
                <p className="text-sm text-muted-foreground">{l.summary}</p>
              </div>
              <StatusBadge status={l.complete_count === l.total_steps ? "known_complete" : "pending"} />
            </button>
            {expanded === l.listing_id && (
              <div className="divide-y divide-border border-t border-border">
                <div className="grid grid-cols-4 gap-4 px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <div>Step</div>
                  <div>Required</div>
                  <div>Status</div>
                  <div>Details</div>
                </div>
                {l.steps.map((step) => (
                  <div key={step.id} className="grid grid-cols-4 items-center gap-4 px-8 py-3 text-sm">
                    <div className="text-foreground">{formatLabel(step.step_type)}</div>
                    <div className="font-mono text-muted-foreground">{step.required ? "Yes" : "No"}</div>
                    <div><StatusBadge status={step.determinability} /></div>
                    <div className="text-xs text-muted-foreground">{step.reasons}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  )
}
