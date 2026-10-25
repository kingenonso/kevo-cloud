import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { apiFetch } from "@/lib/auth"
import { apiFetchQuery } from "@/lib/api"
import { StatusBadge } from "@/components/shared/StatusBadge"

type RuleChangeAlert = {
  id: number
  compliance_rule_id: number
  transaction_id: number
  listing_id: number
  buyer_id: number
  previous_decision_status: string
  new_decision_status: string
  previous_explanation: string | null
  new_explanation: string | null
  is_read: boolean
  read_at: string | null
  created_at: string
}

export function RuleChangeAlertsPage() {
  const [alerts, setAlerts] = useState<RuleChangeAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/rule-change-alerts")
      if (!response.ok) throw new Error()
      const data = (await response.json()) as { alerts: RuleChangeAlert[] }
      setAlerts(data.alerts)
    } catch {
      setError("Could not load rule-change alerts.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function markRead(id: number) {
    const response = await apiFetchQuery(`/rule-change-alerts/${id}/mark-read`, "PUT")
    if (response.ok) await load()
  }

  return (
    <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
      <p className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
        Compliance Rule-Change Alerts
      </p>
      <p className="mb-6 text-sm text-muted-foreground">
        Raised automatically when an admin edits a compliance rule and that change actually
        flips the verdict on one of your still-open transactions. Purely informational — it
        never blocks or changes the transaction itself.
      </p>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : alerts.length === 0 ? (
        <p className="text-sm text-muted-foreground">No rule-change alerts yet.</p>
      ) : (
        <div className="divide-y divide-border">
          <div className="grid grid-cols-6 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <div>Transaction</div>
            <div>Created</div>
            <div>Was</div>
            <div>Now</div>
            <div></div>
            <div>Actions</div>
          </div>
          {alerts.map((a) => (
            <div key={a.id} className="grid grid-cols-6 items-center gap-4 py-3 text-sm">
              <Link to={`/deal-room/${a.transaction_id}`} className="text-foreground hover:underline">
                Transaction #{a.transaction_id}
              </Link>
              <div className="text-muted-foreground">{new Date(a.created_at).toLocaleString()}</div>
              <div><StatusBadge status={a.previous_decision_status} /></div>
              <div><StatusBadge status={a.new_decision_status} /></div>
              <div><StatusBadge status={a.is_read ? "read" : "unread"} /></div>
              <div>
                {!a.is_read && (
                  <Button size="sm" variant="outline" onClick={() => markRead(a.id)}>
                    Mark Read
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
