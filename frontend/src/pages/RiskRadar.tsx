import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/auth"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { formatLabel } from "@/lib/status"

type Transaction = {
  id: number
  listing_id: number
  status: string
}

type DealHealth = {
  transaction_id: number
  listing_id: number
  summary: string
  main_risk: { dimension: string; status: string; reason: string } | null
  dimensions: Array<{ dimension: string; determinable: boolean; status: string; reason: string }>
}

type RiskRadar = {
  transaction_id: number
  listing_id: number
  summary: string
  flags: Array<{ flag_type: string; status: string; reason: string }>
}

export function RiskRadarPage() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [dealHealth, setDealHealth] = useState<DealHealth | null>(null)
  const [riskRadar, setRiskRadar] = useState<RiskRadar | null>(null)
  const [loading, setLoading] = useState(false)
  const [listLoading, setListLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function loadList() {
      setListLoading(true)
      try {
        const response = await apiFetch("/transactions")
        if (response.ok) setTransactions((await response.json()) as Transaction[])
      } finally {
        setListLoading(false)
      }
    }
    loadList()
  }, [])

  useEffect(() => {
    if (!selectedId) {
      setDealHealth(null)
      setRiskRadar(null)
      return
    }
    let cancelled = false
    async function loadDetail() {
      setLoading(true)
      setError(null)
      try {
        const [healthResp, radarResp] = await Promise.all([
          apiFetch(`/deal-health/transaction/${selectedId}`),
          apiFetch(`/risk-radar/transaction/${selectedId}`),
        ])
        if (!cancelled) {
          if (healthResp.ok) setDealHealth((await healthResp.json()) as DealHealth)
          if (radarResp.ok) setRiskRadar((await radarResp.json()) as RiskRadar)
          if (!healthResp.ok && !radarResp.ok) setError("Could not load risk data for this transaction.")
        }
      } catch {
        if (!cancelled) setError("Could not reach the server.")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    loadDetail()
    return () => {
      cancelled = true
    }
  }, [selectedId])

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Select a Transaction
        </p>
        {listLoading ? (
          <p className="text-sm text-muted-foreground">Loading your transactions...</p>
        ) : transactions.length === 0 ? (
          <p className="text-sm text-muted-foreground">You have no transactions yet.</p>
        ) : (
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="h-8 w-full max-w-sm rounded-lg border border-input bg-transparent px-2.5 text-sm"
          >
            <option value="">Select a transaction</option>
            {transactions.map((t) => (
              <option key={t.id} value={t.id}>
                #{t.id} — listing #{t.listing_id} ({t.status})
              </option>
            ))}
          </select>
        )}
      </div>

      {loading && <p className="text-sm text-muted-foreground">Loading risk data...</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {dealHealth && (
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Deal Health
          </p>
          <p className="mb-4 text-sm text-foreground">{dealHealth.summary}</p>
          {dealHealth.main_risk && (
            <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">Main risk:</span>
              <StatusBadge status={dealHealth.main_risk.status} />
              <span className="text-muted-foreground">
                ({formatLabel(dealHealth.main_risk.dimension)}) {dealHealth.main_risk.reason}
              </span>
            </div>
          )}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {dealHealth.dimensions.map((dim) => (
              <div key={dim.dimension} className="rounded-xl border border-border p-4 text-sm">
                <div className="mb-2 flex items-center justify-between">
                  <p className="font-medium text-foreground">{formatLabel(dim.dimension)}</p>
                  <StatusBadge status={dim.status} />
                </div>
                <p className="text-xs text-muted-foreground">{dim.reason}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {riskRadar && (
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Risk Radar
          </p>
          <p className="mb-4 text-sm text-foreground">{riskRadar.summary}</p>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {riskRadar.flags.map((flag, i) => (
              <div key={i} className="rounded-xl border border-border p-4 text-sm">
                <div className="mb-2 flex items-center justify-between">
                  <p className="font-medium text-foreground">{formatLabel(flag.flag_type)}</p>
                  <StatusBadge status={flag.status} />
                </div>
                <p className="text-xs text-muted-foreground">{flag.reason}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
