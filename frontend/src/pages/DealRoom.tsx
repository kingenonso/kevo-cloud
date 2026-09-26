import { useEffect, useState } from "react"
import { useParams, Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { apiFetch } from "@/lib/auth"
import { formatMoney } from "@/lib/format"
import { useAuth } from "@/contexts/AuthContext"

type DealRoomData = {
  transaction: {
    id: number
    listing_id: number
    quantity: number
    agreed_price: number
    status: string
    settlement_currency: string
  }
  participants: {
    buyer: { id: number; role: string }
    seller: { id: number; role: string }
  }
  compliance: { status: string; explanation: string }
  ownership: { records_on_file: number; all_verified: boolean }
  documents: Array<{
    id: number
    evidence_type: string
    description: string | null
    verification_status: string
  }>
  deal_health: {
    summary: string
    main_risk: { status: string; dimension: string; reason: string }
    dimensions: Array<{ dimension: string; status: string; reason: string }>
  }
  risk_radar: {
    summary: string
    flags: Array<{ flag_type: string; status: string; reason: string }>
  }
  liquidity_roadmap: {
    steps: Array<{ step_type: string; required: boolean; determinability: string; reasons: string }>
  }
}

const STATUS_GREEN = new Set(["verified", "eligible", "clear", "known_complete"])
const STATUS_RED = new Set(["blocked", "flagged", "known_incomplete", "rejected"])
const STATUS_AMBER = new Set(["review", "pending", "required_but_unverified"])

function statusBadgeClasses(status: string): string {
  const s = status.toLowerCase()
  if (STATUS_GREEN.has(s)) return "bg-primary/10 text-primary border-primary/20"
  if (STATUS_RED.has(s)) return "bg-destructive/10 text-destructive border-destructive/20"
  if (STATUS_AMBER.has(s)) return "bg-[#F5E3BE] text-[#92672A] border-[#92672A]/20"
  return "bg-muted text-muted-foreground border-border"
}

function formatLabel(value: string): string {
  return value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={statusBadgeClasses(status)}>
      {formatLabel(status)}
    </Badge>
  )
}

export function DealRoomPage() {
  const { transactionId } = useParams()
  const { user } = useAuth()
  const [data, setData] = useState<DealRoomData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const response = await apiFetch(`/deal-room/transaction/${transactionId}`)
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          if (!cancelled) setError(body?.detail ?? "Could not load this deal room.")
          return
        }
        const body = (await response.json()) as DealRoomData
        if (!cancelled) setData(body)
      } catch {
        if (!cancelled) setError("Could not reach the server. Please check your connection.")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [transactionId])

  if (loading) return <p className="text-sm text-muted-foreground">Loading...</p>
  if (error) return <p className="text-sm text-destructive">{error}</p>
  if (!data) return null

  const {
    transaction,
    participants,
    compliance,
    ownership,
    documents,
    deal_health,
    risk_radar,
    liquidity_roadmap,
  } = data

  const yourPosition =
    participants.buyer.id === user?.id
      ? "Buyer"
      : participants.seller.id === user?.id
        ? "Seller"
        : "Admin View"

  return (
    <div className="space-y-6">
      <Link
        to="/transactions"
        className="text-xs font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground"
      >
        Back to Transactions
      </Link>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Transaction
        </p>
        <div className="grid grid-cols-2 gap-6 text-sm sm:grid-cols-4">
          <div>
            <p className="text-xs text-muted-foreground">ID</p>
            <p className="mt-1 font-mono text-foreground">{transaction.id}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Listing</p>
            <p className="mt-1 font-mono text-foreground">{transaction.listing_id}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Quantity</p>
            <p className="mt-1 font-mono text-foreground">{transaction.quantity}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Price</p>
            <p className="mt-1 font-mono text-foreground">
              {formatMoney(transaction.agreed_price, transaction.settlement_currency)}
            </p>
          </div>
        </div>
        <div className="mt-4">
          <p className="mb-1.5 text-xs text-muted-foreground">Status</p>
          <StatusBadge status={transaction.status} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Participants
          </p>
          <div className="space-y-2 text-sm">
            <p className="text-foreground">
              Buyer: <span className="font-mono">#{participants.buyer.id}</span>
            </p>
            <p className="text-foreground">
              Seller: <span className="font-mono">#{participants.seller.id}</span>
            </p>
            <p className="text-muted-foreground">
              Your position in this deal: <span className="font-medium text-foreground">{yourPosition}</span>
            </p>
          </div>
        </div>
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Compliance
          </p>
          <StatusBadge status={compliance.status} />
          <p className="mt-2 text-sm text-muted-foreground">{compliance.explanation}</p>
        </div>
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Ownership
        </p>
        <div className="flex items-center justify-between text-sm">
          <p className="text-foreground">{ownership.records_on_file} ownership record(s) on file</p>
          <StatusBadge status={ownership.all_verified ? "verified" : "pending"} />
        </div>
      </div>

      <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
        <p className="px-8 pt-8 pb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Documents
        </p>
        {documents.length === 0 ? (
          <p className="px-8 pb-8 text-sm text-muted-foreground">
            No documents on file for this transaction yet.
          </p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-3 gap-4 border-b border-border px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Type</div>
              <div>Description</div>
              <div>Status</div>
            </div>
            {documents.map((doc) => (
              <div key={doc.id} className="grid grid-cols-3 items-center gap-4 px-8 py-3 text-sm">
                <div className="text-foreground">{formatLabel(doc.evidence_type)}</div>
                <div className="text-muted-foreground">{doc.description || "-"}</div>
                <div>
                  <StatusBadge status={doc.verification_status} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Deal Health
        </p>
        <p className="text-sm text-foreground">{deal_health.summary}</p>
        <div className="mt-2 mb-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Main risk:</span>
          <StatusBadge status={deal_health.main_risk.status} />
          <span className="text-muted-foreground">
            ({formatLabel(deal_health.main_risk.dimension)}) {deal_health.main_risk.reason}
          </span>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {deal_health.dimensions.map((dim) => (
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

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Risk Radar
        </p>
        <p className="mb-4 text-sm text-foreground">{risk_radar.summary}</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {risk_radar.flags.map((flag, i) => (
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

      <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
        <p className="px-8 pt-8 pb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Liquidity Roadmap
        </p>
        <div className="grid grid-cols-4 gap-4 border-b border-t border-border px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          <div>Step</div>
          <div>Required</div>
          <div>Status</div>
          <div>Details</div>
        </div>
        <div className="divide-y divide-border">
          {liquidity_roadmap.steps.map((step, i) => (
            <div key={i} className="grid grid-cols-4 items-center gap-4 px-8 py-3 text-sm">
              <div className="text-foreground">{formatLabel(step.step_type)}</div>
              <div className="font-mono text-muted-foreground">{step.required ? "Yes" : "No"}</div>
              <div>
                <StatusBadge status={step.determinability} />
              </div>
              <div className="text-xs text-muted-foreground">{step.reasons}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
