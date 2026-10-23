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

type OwnershipRecord = {
  id: number
  company: string
  asset_type: string
  quantity: number
  verification_status: string
}

type LoanRequest = {
  id: number
  holder_id: number
  ownership_record_id: number
  requested_amount: number
  status: string
  external_lender_name: string | null
  external_lender_reference: string | null
  notes: string | null
}

export function LendingPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [requests, setRequests] = useState<LoanRequest[]>([])
  const [ownershipRecords, setOwnershipRecords] = useState<OwnershipRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [ownershipRecordId, setOwnershipRecordId] = useState("")
  const [requestedAmount, setRequestedAmount] = useState("")
  const [notes, setNotes] = useState("")
  const [createSubmitting, setCreateSubmitting] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [matchTarget, setMatchTarget] = useState<LoanRequest | null>(null)
  const [lenderName, setLenderName] = useState("")
  const [lenderRef, setLenderRef] = useState("")

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [requestsResp, ownershipResp] = await Promise.all([
        apiFetch("/loan-requests"),
        apiFetch("/ownership-records"),
      ])
      if (!requestsResp.ok) throw new Error()
      setRequests((await requestsResp.json()) as LoanRequest[])
      if (ownershipResp.ok) {
        const records = (await ownershipResp.json()) as OwnershipRecord[]
        setOwnershipRecords(records.filter((r) => r.verification_status === "verified"))
      }
    } catch {
      setError("Could not load loan requests.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateError(null)
    const amount = Number(requestedAmount)
    if (!ownershipRecordId || !amount) {
      setCreateError("Fill in all required fields.")
      return
    }
    setCreateSubmitting(true)
    try {
      const response = await apiFetchQuery("/loan-requests", "POST", {
        ownership_record_id: Number(ownershipRecordId),
        requested_amount: amount,
        notes: notes || null,
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setCreateError(data?.detail ?? "Could not create loan request.")
        return
      }
      setCreateOpen(false)
      setOwnershipRecordId("")
      setRequestedAmount("")
      setNotes("")
      await load()
    } catch {
      setCreateError("Could not reach the server.")
    } finally {
      setCreateSubmitting(false)
    }
  }

  async function withdraw(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/loan-requests/${id}/withdraw`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not withdraw this request.")
      return
    }
    await load()
  }

  async function decline(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/loan-requests/${id}/decline`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not decline this request.")
      return
    }
    await load()
  }

  async function close(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/loan-requests/${id}/close`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not close this request.")
      return
    }
    await load()
  }

  async function handleMatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!matchTarget || !lenderName.trim()) return
    const response = await apiFetchQuery(`/loan-requests/${matchTarget.id}/match`, "PUT", {
      external_lender_name: lenderName,
      external_lender_reference: lenderRef || null,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not record this match.")
      return
    }
    setMatchTarget(null)
    setLenderName("")
    setLenderRef("")
    await load()
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          KEVO never originates, funds, or holds collateral for a loan - this connects and
          tracks a request to borrow against verified shares through to a real, licensed
          external lender.
        </p>
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {isAdmin ? "All Loan Requests" : "Your Loan Requests"}
          </p>
          {!isAdmin && (
            <Button size="sm" onClick={() => setCreateOpen(true)} disabled={ownershipRecords.length === 0}>
              Request a Loan
            </Button>
          )}
        </div>

        {actionError && <p className="mb-4 text-sm text-destructive">{actionError}</p>}

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : requests.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {isAdmin ? "No loan requests yet." : "You have no loan requests yet."}
          </p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-6 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>ID</div>
              <div>Ownership Record</div>
              <div>Amount</div>
              <div>Status</div>
              <div>Lender</div>
              <div>Actions</div>
            </div>
            {requests.map((r) => (
              <div key={r.id} className="grid grid-cols-6 items-center gap-4 py-3 text-sm">
                <div className="text-foreground">{r.id}</div>
                <div className="text-muted-foreground">#{r.ownership_record_id}</div>
                <div className="text-foreground">{formatMoney(r.requested_amount)}</div>
                <div><StatusBadge status={r.status} /></div>
                <div className="text-muted-foreground">{r.external_lender_name ?? "-"}</div>
                <div className="flex flex-wrap gap-2">
                  {!isAdmin && r.holder_id === user?.id && r.status === "requested" && (
                    <Button size="sm" variant="outline" onClick={() => withdraw(r.id)}>
                      Withdraw
                    </Button>
                  )}
                  {isAdmin && r.status === "requested" && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => setMatchTarget(r)}>
                        Match
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => decline(r.id)}>
                        Decline
                      </Button>
                    </>
                  )}
                  {isAdmin && r.status === "matched" && (
                    <Button size="sm" variant="outline" onClick={() => close(r.id)}>
                      Close
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Request a loan against verified shares</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Ownership Record
              </label>
              <select
                value={ownershipRecordId}
                onChange={(e) => setOwnershipRecordId(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                required
              >
                <option value="">Select a verified holding</option>
                {ownershipRecords.map((r) => (
                  <option key={r.id} value={r.id}>
                    #{r.id} — {r.company} ({r.asset_type}), {r.quantity} units
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Requested Amount ($)
              </label>
              <Input
                type="number"
                min="0"
                step="0.01"
                value={requestedAmount}
                onChange={(e) => setRequestedAmount(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Notes (optional)
              </label>
              <Input value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
            {createError && <p className="text-sm text-destructive">{createError}</p>}
            <DialogFooter>
              <Button type="submit" disabled={createSubmitting} className="w-full">
                {createSubmitting ? "Submitting..." : "Submit Request"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={matchTarget !== null} onOpenChange={(open) => !open && setMatchTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Record a match to a real external lender</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleMatch} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Lender Name
              </label>
              <Input value={lenderName} onChange={(e) => setLenderName(e.target.value)} required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Lender Reference (optional)
              </label>
              <Input value={lenderRef} onChange={(e) => setLenderRef(e.target.value)} />
            </div>
            <DialogFooter>
              <Button type="submit" className="w-full">
                Record Match
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
