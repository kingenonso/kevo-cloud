import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/auth"
import { StatusBadge } from "@/components/shared/StatusBadge"

// M33 (first slice) - the Issuer Liquidity Portal. Mirrors exactly what
// GET /issuer/dashboard returns (see app.py) - a read-only view scoped to
// the logged-in issuer's own company. Investor identity and per-buyer
// compliance detail are deliberately never included in that response
// (aggregate counts only), so there is nothing to strip here either.

type LiquiditySeeker = {
  listing_id: number
  seller_id: number
  seller_name: string | null
  asset_type: string
  quantity: number
  asking_price: number
  is_transferable: boolean
}

type PendingTransfer = {
  transaction_id: number
  listing_id: number
  quantity: number
  status: string
  settlement_currency: string
}

type RofrRequestRow = {
  rofr_request_id: number
  transaction_id: number
  status: string
  response_due_date: string | null
  responded_at: string | null
}

type OwnershipRow = {
  ownership_record_id: number
  seller_id: number
  asset_type: string
  quantity: number
  verification_status: string
  acquisition_date: string | null
}

type TenderProgram = {
  program_id: number
  status: string
  price_per_share: number
  opens_at: string
  closes_at: string
  is_recurring: boolean
}

type TransferRestriction = {
  rule_id: number
  rule_code: string
  jurisdiction: string
  asset_type: string
  requirement: string
  decision_if_unmet: string
  source_reference: string | null
}

type IssuerDashboard = {
  company_name: string
  liquidity_seekers: LiquiditySeeker[]
  pending_transfers: PendingTransfer[]
  rofr_requests: RofrRequestRow[]
  ownership_on_file: OwnershipRow[]
  tender_programs: TenderProgram[]
  shareholder_concentration: {
    total_quantity_on_file: number
    distinct_holders: number
    top_holder_share_pct: number | null
  }
  transfer_restrictions: TransferRestriction[]
  investor_demand: {
    active_interest_count: number
    total_desired_quantity: number
  }
  compliance_requests: Record<string, number>
  cap_table_sync: {
    connected: boolean
    provider: string | null
    last_synced_at: string | null
    note: string
  }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
      <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">{title}</p>
      {children}
    </div>
  )
}

function Empty({ label }: { label: string }) {
  return <p className="text-sm text-muted-foreground">{label}</p>
}

export function IssuerPortalPage() {
  const [data, setData] = useState<IssuerDashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const response = await apiFetch("/issuer/dashboard")
        if (!response.ok) {
          const body = await response.json().catch(() => null)
          setError(body?.detail ?? "Could not load the issuer portal.")
          return
        }
        setData((await response.json()) as IssuerDashboard)
      } catch {
        setError("Could not reach the server.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading...</p>
  }

  if (error) {
    return (
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">Company</p>
        <p className="mt-2 text-2xl font-semibold text-foreground">{data.company_name}</p>
      </div>

      <Section title="Liquidity Seekers">
        {data.liquidity_seekers.length === 0 ? (
          <Empty label="No active listings for this company." />
        ) : (
          <div className="divide-y divide-border">
            {data.liquidity_seekers.map((row) => (
              <div key={row.listing_id} className="grid grid-cols-5 gap-4 py-3 text-sm">
                <div>{row.seller_name ?? `Seller #${row.seller_id}`}</div>
                <div>{row.asset_type}</div>
                <div>{row.quantity.toLocaleString()} units</div>
                <div>${row.asking_price.toLocaleString()}</div>
                <div><StatusBadge status={row.is_transferable ? "transferable" : "not_transferable"} /></div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Pending Transfers">
        {data.pending_transfers.length === 0 ? (
          <Empty label="No transfers in progress." />
        ) : (
          <div className="divide-y divide-border">
            {data.pending_transfers.map((row) => (
              <div key={row.transaction_id} className="grid grid-cols-4 gap-4 py-3 text-sm">
                <div>Transaction #{row.transaction_id}</div>
                <div>{row.quantity.toLocaleString()} units</div>
                <div>{row.settlement_currency}</div>
                <div><StatusBadge status={row.status} /></div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="ROFR Requests">
        {data.rofr_requests.length === 0 ? (
          <Empty label="No ROFR requests on file." />
        ) : (
          <div className="divide-y divide-border">
            {data.rofr_requests.map((row) => (
              <div key={row.rofr_request_id} className="grid grid-cols-4 gap-4 py-3 text-sm">
                <div>Transaction #{row.transaction_id}</div>
                <div><StatusBadge status={row.status} /></div>
                <div>{row.response_due_date ? `Due ${row.response_due_date}` : "No due date on file"}</div>
                <div>{row.responded_at ? `Responded ${new Date(row.responded_at).toLocaleDateString()}` : "Awaiting response"}</div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Ownership on File">
        {data.ownership_on_file.length === 0 ? (
          <Empty label="No ownership records on file." />
        ) : (
          <div className="divide-y divide-border">
            {data.ownership_on_file.map((row) => (
              <div key={row.ownership_record_id} className="grid grid-cols-4 gap-4 py-3 text-sm">
                <div>Holder #{row.seller_id}</div>
                <div>{row.asset_type}</div>
                <div>{row.quantity.toLocaleString()} units</div>
                <div><StatusBadge status={row.verification_status} /></div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Tender Offer Programs">
        {data.tender_programs.length === 0 ? (
          <Empty label="No tender offer programs for this company." />
        ) : (
          <div className="divide-y divide-border">
            {data.tender_programs.map((row) => (
              <div key={row.program_id} className="grid grid-cols-4 gap-4 py-3 text-sm">
                <div>${row.price_per_share.toLocaleString()} / share</div>
                <div>{new Date(row.opens_at).toLocaleDateString()} - {new Date(row.closes_at).toLocaleDateString()}</div>
                <div>{row.is_recurring ? "Recurring" : "One-time"}</div>
                <div><StatusBadge status={row.status} /></div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <div className="grid gap-6 md:grid-cols-2">
        <Section title="Shareholder Concentration">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Total quantity on file</dt>
              <dd className="font-medium">{data.shareholder_concentration.total_quantity_on_file.toLocaleString()}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Distinct holders</dt>
              <dd className="font-medium">{data.shareholder_concentration.distinct_holders}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Top holder share</dt>
              <dd className="font-medium">
                {data.shareholder_concentration.top_holder_share_pct !== null
                  ? `${data.shareholder_concentration.top_holder_share_pct}%`
                  : "N/A"}
              </dd>
            </div>
          </dl>
        </Section>

        <Section title="Investor Demand">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Active expressions of interest</dt>
              <dd className="font-medium">{data.investor_demand.active_interest_count}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Total desired quantity</dt>
              <dd className="font-medium">{data.investor_demand.total_desired_quantity.toLocaleString()}</dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-muted-foreground">
            Shown in aggregate only - individual investor identity is never shared with an issuer.
          </p>
        </Section>
      </div>

      <Section title="Transfer Restrictions">
        {data.transfer_restrictions.length === 0 ? (
          <Empty label="No applicable transferability rules on file for this company's listings." />
        ) : (
          <div className="divide-y divide-border">
            {data.transfer_restrictions.map((rule) => (
              <div key={rule.rule_id} className="py-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{rule.rule_code}</span>
                  <StatusBadge status={rule.decision_if_unmet} />
                </div>
                <p className="mt-1 text-muted-foreground">{rule.requirement}</p>
                <p className="mt-1 text-xs text-muted-foreground">{rule.jurisdiction} - {rule.asset_type}</p>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Compliance Requests">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {Object.entries(data.compliance_requests).map(([status, count]) => (
            <div key={status} className="rounded-2xl border border-border p-4 text-center">
              <p className="text-2xl font-semibold text-foreground">{count}</p>
              <p className="mt-1 text-xs text-muted-foreground">{status.replace(/_/g, " ")}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Cap Table Sync">
        <div className="flex items-center justify-between">
          <StatusBadge status={data.cap_table_sync.connected ? "connected" : "not_connected"} />
        </div>
        <p className="mt-3 text-sm text-muted-foreground">{data.cap_table_sync.note}</p>
      </Section>
    </div>
  )
}
