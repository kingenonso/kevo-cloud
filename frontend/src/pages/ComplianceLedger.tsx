import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch } from "@/lib/auth"
import { useAuth } from "@/contexts/AuthContext"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { formatLabel } from "@/lib/status"

type LedgerEntry = {
  id: number
  transaction_id: number
  buyer_id: number
  listing_id: number
  decision_status: string
  explanation: string | null
  applicable_rule_codes: string[]
  triggered_by: string
  decided_at: string
  previous_hash: string
  entry_hash: string
  hash_valid: boolean
}

type VerifyResult = {
  valid: boolean
  total_entries: number
  first_invalid_entry_id: number | null
}

export function ComplianceLedgerPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [transactionId, setTransactionId] = useState("")
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null)
  const [verifyLoading, setVerifyLoading] = useState(false)
  const [verifyError, setVerifyError] = useState<string | null>(null)

  async function handleLookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!transactionId) return
    setLoading(true)
    setError(null)
    setEntries(null)
    try {
      const response = await apiFetch(`/compliance-ledger/transaction/${transactionId}`)
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setError(data?.detail ?? "Could not load the compliance ledger for this transaction.")
        return
      }
      setEntries((await response.json()) as LedgerEntry[])
    } catch {
      setError("Could not reach the server.")
    } finally {
      setLoading(false)
    }
  }

  async function handleVerify() {
    setVerifyLoading(true)
    setVerifyError(null)
    try {
      const response = await apiFetch("/compliance-ledger/verify")
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setVerifyError(data?.detail ?? "Could not verify the ledger.")
        return
      }
      setVerifyResult((await response.json()) as VerifyResult)
    } catch {
      setVerifyError("Could not reach the server.")
    } finally {
      setVerifyLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Look up a transaction's compliance decision history
        </p>
        <p className="mb-4 text-sm text-muted-foreground">
          Every compliance decision made for a transaction is snapshotted here and
          cryptographically chained to the one before it, so the history can be proven
          untampered rather than just logged.
        </p>
        <form onSubmit={handleLookup} className="flex gap-3">
          <Input
            type="number"
            placeholder="Transaction ID"
            value={transactionId}
            onChange={(e) => setTransactionId(e.target.value)}
            className="max-w-xs"
          />
          <Button type="submit" disabled={loading}>
            {loading ? "Loading..." : "Look Up"}
          </Button>
        </form>
        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      </div>

      {entries !== null && (
        <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
          <p className="px-8 pt-8 pb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Decision History
          </p>
          {entries.length === 0 ? (
            <p className="px-8 pb-8 text-sm text-muted-foreground">No ledger entries for this transaction yet.</p>
          ) : (
            <div className="divide-y divide-border">
              <div className="grid grid-cols-5 gap-4 border-t border-border px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                <div>Decided At</div>
                <div>Status</div>
                <div>Triggered By</div>
                <div>Rules</div>
                <div>Hash Valid</div>
              </div>
              {entries.map((entry) => (
                <div key={entry.id} className="grid grid-cols-5 items-start gap-4 px-8 py-3 text-sm">
                  <div className="text-muted-foreground">{new Date(entry.decided_at).toLocaleString()}</div>
                  <div><StatusBadge status={entry.decision_status} /></div>
                  <div className="text-muted-foreground">{formatLabel(entry.triggered_by)}</div>
                  <div className="text-xs text-muted-foreground">{entry.applicable_rule_codes.join(", ") || "-"}</div>
                  <div>
                    <StatusBadge status={entry.hash_valid ? "verified" : "flagged"} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {isAdmin && (
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
              Verify the Full Platform Ledger
            </p>
            <Button size="sm" onClick={handleVerify} disabled={verifyLoading}>
              {verifyLoading ? "Verifying..." : "Verify Chain"}
            </Button>
          </div>
          {verifyError && <p className="text-sm text-destructive">{verifyError}</p>}
          {verifyResult && (
            <div className="flex items-center gap-4 text-sm">
              <StatusBadge status={verifyResult.valid ? "verified" : "flagged"} />
              <span className="text-muted-foreground">{verifyResult.total_entries} total entries</span>
              {verifyResult.first_invalid_entry_id !== null && (
                <span className="text-destructive">First invalid entry: #{verifyResult.first_invalid_entry_id}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
