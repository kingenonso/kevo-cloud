import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/auth"
import { formatLabel } from "@/lib/status"

type AuditLogEntry = {
  id: number
  actor_user_id: number | null
  action: string
  target_type: string | null
  target_id: number | null
  detail: string | null
  created_at: string
}

export function AuditLogPage() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/audit-log")
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setError(data?.detail ?? "Could not load the audit log.")
        return
      }
      setEntries((await response.json()) as AuditLogEntry[])
    } catch {
      setError("Could not reach the server.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
      <p className="px-8 pt-8 pb-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
        Audit Log
      </p>
      <p className="px-8 pb-6 text-sm text-muted-foreground">
        Admin-only read of the curated security/compliance audit trail, newest first.
      </p>

      {loading ? (
        <p className="px-8 pb-8 text-sm text-muted-foreground">Loading...</p>
      ) : error ? (
        <p className="px-8 pb-8 text-sm text-destructive">{error}</p>
      ) : entries.length === 0 ? (
        <p className="px-8 pb-8 text-sm text-muted-foreground">No audit log entries yet.</p>
      ) : (
        <div className="divide-y divide-border">
          <div className="grid grid-cols-6 gap-4 border-t border-border px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <div>When</div>
            <div>Actor</div>
            <div>Action</div>
            <div>Target</div>
            <div className="col-span-2">Detail</div>
          </div>
          {entries.map((entry) => (
            <div key={entry.id} className="grid grid-cols-6 items-start gap-4 px-8 py-3 text-sm">
              <div className="text-muted-foreground">{new Date(entry.created_at).toLocaleString()}</div>
              <div className="font-mono text-foreground">
                {entry.actor_user_id !== null ? `User #${entry.actor_user_id}` : "System"}
              </div>
              <div className="text-foreground">{formatLabel(entry.action)}</div>
              <div className="text-muted-foreground">
                {entry.target_type ? `${formatLabel(entry.target_type)} #${entry.target_id}` : "-"}
              </div>
              <div className="col-span-2 text-xs text-muted-foreground">{entry.detail || "-"}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
