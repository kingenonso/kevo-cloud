import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { apiFetch } from "@/lib/auth"
import { apiFetchQuery } from "@/lib/api"
import { useAuth } from "@/contexts/AuthContext"
import { formatMoney } from "@/lib/format"
import { StatusBadge } from "@/components/shared/StatusBadge"

type SettlementRecord = {
  id: number
  transaction_id: number
  status: string
  escrow_provider_reference: string | null
  funds_received: boolean
  funds_received_at: string | null
  shares_confirmed_transferable: boolean
  shares_confirmed_transferable_at: string | null
  funds_released: boolean
  funds_released_at: string | null
  notes: string | null
  escrow_release_initiated: boolean
}

type Transaction = {
  id: number
  listing_id: number
  buyer_id: number
  seller_id: number
  quantity: number
  agreed_price: number
  status: string
  settlement_currency: string
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "-"
}

export function SettlementPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [records, setRecords] = useState<SettlementRecord[]>([])
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const [resolveTarget, setResolveTarget] = useState<SettlementRecord | null>(null)
  const [resolveReference, setResolveReference] = useState("")

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [recordsResp, txResp] = await Promise.all([
        apiFetch("/settlement-records"),
        apiFetch("/transactions"),
      ])
      if (!recordsResp.ok) throw new Error()
      setRecords((await recordsResp.json()) as SettlementRecord[])
      if (txResp.ok) setTransactions((await txResp.json()) as Transaction[])
    } catch {
      setError("Could not load settlement records.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function transactionFor(transactionId: number): Transaction | undefined {
    return transactions.find((t) => t.id === transactionId)
  }

  async function beginSettlement(transactionId: number) {
    setActionError(null)
    setBusyId(transactionId)
    try {
      const response = await apiFetchQuery("/settlement-records", "POST", {
        transaction_id: transactionId,
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setActionError(data?.detail ?? "Could not begin settlement for this transaction.")
        return
      }
      await load()
    } finally {
      setBusyId(null)
    }
  }

  async function confirmFundsReceived(record: SettlementRecord) {
    setActionError(null)
    setBusyId(record.id)
    try {
      const response = await apiFetchQuery(`/settlement-records/${record.id}/confirm-funds-received`, "PUT")
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setActionError(data?.detail ?? "Could not confirm funds received.")
        return
      }
      await load()
    } finally {
      setBusyId(null)
    }
  }

  async function confirmSharesTransferable(record: SettlementRecord) {
    setActionError(null)
    setBusyId(record.id)
    try {
      const response = await apiFetchQuery(`/settlement-records/${record.id}/confirm-shares-transferable`, "PUT")
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setActionError(data?.detail ?? "Could not confirm shares are transferable.")
        return
      }
      await load()
    } finally {
      setBusyId(null)
    }
  }

  async function releaseFunds(record: SettlementRecord) {
    setActionError(null)
    setBusyId(record.id)
    try {
      const response = await apiFetchQuery(`/settlement-records/${record.id}/release-funds`, "PUT")
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setActionError(data?.detail ?? "Could not release funds yet.")
        return
      }
      await load()
    } finally {
      setBusyId(null)
    }
  }

  async function handleResolve(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!resolveTarget) return
    setActionError(null)
    const response = await apiFetchQuery(
      `/settlement-records/${resolveTarget.id}/resolve-unconfirmed-creation`,
      "PUT",
      { escrow_provider_reference: resolveReference || null }
    )
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not resolve this settlement record.")
      return
    }
    setResolveTarget(null)
    setResolveReference("")
    await load()
  }

  // Transactions still in "accepted" status, where settlement either
  // hasn't started yet, or a previous attempt was confirmed abandoned
  // (no Escrow.com transaction was actually created) and is safe to
  // retry. "escrow_creation_unconfirmed" attempts are NOT retryable
  // from here - they need the Resolve action in the main table below
  // first, to avoid risking a duplicate Escrow.com transaction.
  const recordByTxId = new Map(records.map((r) => [r.transaction_id, r]))
  const beginnable = transactions.filter((t) => {
    if (t.status !== "accepted") return false
    const existing = recordByTxId.get(t.id)
    return !existing || existing.status === "escrow_creation_abandoned"
  })

  // Abandoned attempts are represented above (as retryable), not as a
  // dead row in the main history table below.
  const visibleRecords = records.filter((r) => r.status !== "escrow_creation_abandoned")

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          KEVO never holds client funds or acts as custodian - these are the real-world
          confirmations a licensed escrow provider (Escrow.com) reports as a deal moves
          through settlement. Release is sequential, not automatic: funds can only be
          released once both funds-received and shares-confirmed-transferable are
          independently true.
        </p>
      </div>

      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      {isAdmin && beginnable.length > 0 && (
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Accepted Transactions Awaiting Settlement
          </p>
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Transaction</div>
              <div>Quantity</div>
              <div>Agreed Price</div>
              <div>Buyer / Seller</div>
              <div>Action</div>
            </div>
            {beginnable.map((t) => (
              <div key={t.id} className="grid grid-cols-5 items-center gap-4 py-3 text-sm">
                <div className="text-foreground">#{t.id}</div>
                <div className="text-muted-foreground">{t.quantity}</div>
                <div className="text-foreground">{formatMoney(t.agreed_price, t.settlement_currency)}</div>
                <div className="text-muted-foreground">#{t.buyer_id} / #{t.seller_id}</div>
                <div>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busyId === t.id}
                    onClick={() => beginSettlement(t.id)}
                  >
                    {recordByTxId.has(t.id) ? "Retry Settlement" : "Begin Settlement"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          {isAdmin ? "All Settlement Records" : "Your Settlement Records"}
        </p>

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : visibleRecords.length === 0 ? (
          <p className="text-sm text-muted-foreground">No settlement records yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-6 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Transaction</div>
              <div>Status</div>
              <div>Funds Received</div>
              <div>Shares Transferable</div>
              <div>Funds Released</div>
              <div>{isAdmin ? "Actions" : "Notes"}</div>
            </div>
            {visibleRecords.map((r) => {
              const tx = transactionFor(r.transaction_id)
              return (
                <div key={r.id} className="grid grid-cols-6 items-start gap-4 py-3 text-sm">
                  <div className="text-foreground">
                    #{r.transaction_id}
                    {tx && (
                      <div className="text-xs text-muted-foreground">
                        {formatMoney(tx.agreed_price, tx.settlement_currency)}
                      </div>
                    )}
                  </div>
                  <div><StatusBadge status={r.status} /></div>
                  <div className="text-xs text-muted-foreground">
                    {r.funds_received ? formatDate(r.funds_received_at) : "Pending"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {r.shares_confirmed_transferable ? formatDate(r.shares_confirmed_transferable_at) : "Pending"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {r.funds_released ? formatDate(r.funds_released_at) : "Pending"}
                  </div>
                  <div>
                    {isAdmin ? (
                      <div className="flex flex-wrap gap-2">
                        {r.status === "escrow_creation_unconfirmed" && (
                          <Button size="sm" variant="outline" onClick={() => setResolveTarget(r)}>
                            Resolve
                          </Button>
                        )}
                        {r.status !== "escrow_creation_unconfirmed" && r.status !== "completed" && (
                          <>
                            {!r.funds_received && (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busyId === r.id}
                                onClick={() => confirmFundsReceived(r)}
                              >
                                Confirm Funds Received
                              </Button>
                            )}
                            {!r.shares_confirmed_transferable && (
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busyId === r.id}
                                onClick={() => confirmSharesTransferable(r)}
                              >
                                Confirm Shares Transferable
                              </Button>
                            )}
                            {r.funds_received && r.shares_confirmed_transferable && !r.funds_released && (
                              <Button
                                size="sm"
                                disabled={busyId === r.id}
                                onClick={() => releaseFunds(r)}
                              >
                                Release Funds
                              </Button>
                            )}
                          </>
                        )}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">{r.notes ?? "-"}</p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <Dialog open={resolveTarget !== null} onOpenChange={(open) => !open && setResolveTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Resolve unconfirmed escrow creation</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleResolve} className="space-y-4">
            <p className="text-sm text-muted-foreground">
              A previous attempt to create this settlement's Escrow.com transaction did not
              confirm success. Check directly with Escrow.com before resolving this.
            </p>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Escrow.com Transaction Reference (only if it WAS actually created)
              </label>
              <Input
                value={resolveReference}
                onChange={(e) => setResolveReference(e.target.value)}
                placeholder="Leave blank if no transaction was created on Escrow.com"
              />
            </div>
            <DialogFooter>
              <Button type="submit" className="w-full">
                {resolveReference ? "Confirm Created, Resume Settlement" : "Confirm Not Created, Allow Retry"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
