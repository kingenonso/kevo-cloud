import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { apiFetch } from "@/lib/auth"
import { apiFetchQuery } from "@/lib/api"
import { StatusBadge } from "@/components/shared/StatusBadge"

type DealAlert = {
  id: number
  buyer_interest_id: number
  listing_id: number
  buyer_id: number
  is_read: boolean
  read_at: string | null
  created_at: string
}

export function DealAlertsPage() {
  const [alerts, setAlerts] = useState<DealAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/deal-alerts")
      if (!response.ok) throw new Error()
      setAlerts((await response.json()) as DealAlert[])
    } catch {
      setError("Could not load your deal alerts.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function markRead(id: number) {
    const response = await apiFetchQuery(`/deal-alerts/${id}/mark-read`, "PUT")
    if (response.ok) await load()
  }

  return (
    <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
      <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
        Deal Alerts
      </p>
      <p className="mb-6 text-sm text-muted-foreground">
        A flat, chronological list of new listings that match one of your stated buyer
        interests on company, asset type, price, and quantity — never ranked or scored.
      </p>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : alerts.length === 0 ? (
        <p className="text-sm text-muted-foreground">No deal alerts yet.</p>
      ) : (
        <div className="divide-y divide-border">
          <div className="grid grid-cols-5 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <div>Listing</div>
            <div>Created</div>
            <div>Status</div>
            <div></div>
            <div>Actions</div>
          </div>
          {alerts.map((a) => (
            <div key={a.id} className="grid grid-cols-5 items-center gap-4 py-3 text-sm">
              <Link to={`/listings`} className="text-foreground hover:underline">
                Listing #{a.listing_id}
              </Link>
              <div className="text-muted-foreground">{new Date(a.created_at).toLocaleString()}</div>
              <div><StatusBadge status={a.is_read ? "read" : "unread"} /></div>
              <div></div>
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
