import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch } from "@/lib/auth"

// The wallet-review data comes from a separate Java service
// (kevo-wallet-service) that isn't in this repo, so the exact JSON key
// names of each pending-review item aren't something this frontend can
// verify from source - rather than guess field names, each item is
// rendered generically from whatever keys the server actually returns,
// and the two IDs the approve/reject actions need are editable fields
// the admin confirms before acting (best-effort pre-filled from common
// key name guesses).
type PendingWithdrawal = Record<string, unknown>

function guessId(item: PendingWithdrawal, keys: string[]): string {
  for (const key of keys) {
    const value = item[key]
    if (typeof value === "number" || typeof value === "string") return String(value)
  }
  return ""
}

export function WithdrawalReviewPage() {
  const [items, setItems] = useState<PendingWithdrawal[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/admin/withdrawals/pending-review")
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setError(data?.detail ?? "Could not load withdrawals pending review.")
        return
      }
      setItems((await response.json()) as PendingWithdrawal[])
    } catch {
      setError("Could not reach the server.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function approve(kevoUserId: string, withdrawalId: string) {
    setActionError(null)
    setActionMessage(null)
    if (!kevoUserId || !withdrawalId) {
      setActionError("Enter both the KEVO user ID and withdrawal ID.")
      return
    }
    const response = await apiFetch(`/admin/withdrawals/${kevoUserId}/${withdrawalId}/approve`, { method: "PUT" })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not approve this withdrawal.")
      return
    }
    setActionMessage("Withdrawal approved.")
    await load()
  }

  async function reject(kevoUserId: string, withdrawalId: string, reason: string) {
    setActionError(null)
    setActionMessage(null)
    if (!kevoUserId || !withdrawalId) {
      setActionError("Enter both the KEVO user ID and withdrawal ID.")
      return
    }
    if (!reason.trim()) {
      setActionError("A reason is required to reject a withdrawal.")
      return
    }
    const response = await apiFetch(`/admin/withdrawals/${kevoUserId}/${withdrawalId}/reject`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not reject this withdrawal.")
      return
    }
    setActionMessage("Withdrawal rejected.")
    await load()
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          Withdrawals held for manual review by the wallet service's own behavioral risk
          scoring (multiple flags, or repeated recent failures). Nothing moves until an
          admin approves or rejects it here.
        </p>
      </div>

      {actionError && <p className="text-sm text-destructive">{actionError}</p>}
      {actionMessage && <p className="text-sm text-primary">{actionMessage}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Pending Review
        </p>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : !items || items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No withdrawals are currently pending review.</p>
        ) : (
          <div className="space-y-4">
            {items.map((item, i) => {
              const kevoUserIdGuess = guessId(item, ["kevoUserId", "kevo_user_id", "userId", "user_id"])
              const withdrawalIdGuess = guessId(item, ["withdrawalId", "withdrawal_id", "id"])
              return <WithdrawalCard key={i} item={item} kevoUserIdGuess={kevoUserIdGuess} withdrawalIdGuess={withdrawalIdGuess} onApprove={approve} onReject={reject} />
            })}
          </div>
        )}
      </div>
    </div>
  )
}

function WithdrawalCard({
  item,
  kevoUserIdGuess,
  withdrawalIdGuess,
  onApprove,
  onReject,
}: {
  item: PendingWithdrawal
  kevoUserIdGuess: string
  withdrawalIdGuess: string
  onApprove: (kevoUserId: string, withdrawalId: string) => void
  onReject: (kevoUserId: string, withdrawalId: string, reason: string) => void
}) {
  const [kevoUserId, setKevoUserId] = useState(kevoUserIdGuess)
  const [withdrawalId, setWithdrawalId] = useState(withdrawalIdGuess)
  const [reason, setReason] = useState("")

  return (
    <div className="rounded-xl border border-border p-4">
      <div className="mb-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
        {Object.entries(item).map(([key, value]) => (
          <div key={key}>
            <p className="text-muted-foreground">{key}</p>
            <p className="font-mono text-foreground">{String(value)}</p>
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">KEVO User ID</label>
          <Input className="w-32" value={kevoUserId} onChange={(e) => setKevoUserId(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">Withdrawal ID</label>
          <Input className="w-32" value={withdrawalId} onChange={(e) => setWithdrawalId(e.target.value)} />
        </div>
        <div className="flex-1">
          <label className="mb-1 block text-xs text-muted-foreground">Reject Reason</label>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <Button size="sm" onClick={() => onApprove(kevoUserId, withdrawalId)}>
          Approve
        </Button>
        <Button size="sm" variant="outline" onClick={() => onReject(kevoUserId, withdrawalId, reason)}>
          Reject
        </Button>
      </div>
    </div>
  )
}
