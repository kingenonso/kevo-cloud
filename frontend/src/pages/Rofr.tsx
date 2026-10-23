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
import { StatusBadge } from "@/components/shared/StatusBadge"

type RofrRequest = {
  id: number
  transaction_id: number
  transferability_rule_id: number
  status: string
  source_reference: string | null
  response_due_date: string | null
  response_notes: string | null
}

type Transaction = {
  id: number
  listing_id: number
  buyer_id: number
  seller_id: number
}

type ApplicableRule = {
  id: number
  rule_code: string
  requirement: string
  decision_if_unmet: string
}

export function RofrPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [requests, setRequests] = useState<RofrRequest[]>([])
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [selectedTxId, setSelectedTxId] = useState("")
  const [applicableRules, setApplicableRules] = useState<ApplicableRule[]>([])
  const [selectedRuleId, setSelectedRuleId] = useState("")
  const [createError, setCreateError] = useState<string | null>(null)

  const [respondTarget, setRespondTarget] = useState<RofrRequest | null>(null)
  const [respondStatus, setRespondStatus] = useState("approved")
  const [respondNotes, setRespondNotes] = useState("")

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [requestsResp, txResp] = await Promise.all([
        apiFetch("/rofr-requests"),
        apiFetch("/transactions"),
      ])
      if (!requestsResp.ok) throw new Error()
      setRequests((await requestsResp.json()) as RofrRequest[])
      if (txResp.ok) setTransactions((await txResp.json()) as Transaction[])
    } catch {
      setError("Could not load ROFR requests.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function onSelectTransaction(txId: string) {
    setSelectedTxId(txId)
    setSelectedRuleId("")
    setApplicableRules([])
    const tx = transactions.find((t) => String(t.id) === txId)
    if (!tx) return
    const response = await apiFetch(`/transferability/listing/${tx.listing_id}/applicable-rules`)
    if (response.ok) {
      const data = (await response.json()) as { applicable_rules: ApplicableRule[] }
      setApplicableRules(data.applicable_rules)
    }
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateError(null)
    if (!selectedTxId || !selectedRuleId) {
      setCreateError("Select a transaction and an applicable rule.")
      return
    }
    const response = await apiFetch("/rofr-requests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transaction_id: Number(selectedTxId),
        transferability_rule_id: Number(selectedRuleId),
      }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setCreateError(data?.detail ?? "Could not create this ROFR request.")
      return
    }
    setCreateOpen(false)
    setSelectedTxId("")
    setSelectedRuleId("")
    setApplicableRules([])
    await load()
  }

  async function handleRespond(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!respondTarget) return
    const response = await apiFetchQuery(`/rofr-requests/${respondTarget.id}/respond`, "PUT", {
      status: respondStatus,
      response_notes: respondNotes || null,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not record this response.")
      return
    }
    setRespondTarget(null)
    setRespondNotes("")
    await load()
  }

  const mySellerTransactions = transactions.filter((t) => t.seller_id === user?.id)

  return (
    <div className="space-y-6">
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {isAdmin ? "All ROFR Requests" : "Your ROFR Requests"}
          </p>
          {!isAdmin && mySellerTransactions.length > 0 && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              New ROFR Request
            </Button>
          )}
        </div>

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : requests.length === 0 ? (
          <p className="text-sm text-muted-foreground">No ROFR requests yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Transaction</div>
              <div>Rule</div>
              <div>Status</div>
              <div>Response Due</div>
              <div>Actions</div>
            </div>
            {requests.map((r) => (
              <div key={r.id} className="grid grid-cols-5 items-center gap-4 py-3 text-sm">
                <div className="text-foreground">#{r.transaction_id}</div>
                <div className="text-muted-foreground">#{r.transferability_rule_id}</div>
                <div><StatusBadge status={r.status} /></div>
                <div className="text-muted-foreground">
                  {r.response_due_date ? new Date(r.response_due_date).toLocaleDateString() : "-"}
                </div>
                <div>
                  {isAdmin && r.status === "pending" && (
                    <Button size="sm" variant="outline" onClick={() => setRespondTarget(r)}>
                      Respond
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
            <DialogTitle>Submit a ROFR request</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Transaction</label>
              <select
                value={selectedTxId}
                onChange={(e) => onSelectTransaction(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                required
              >
                <option value="">Select one of your transactions</option>
                {mySellerTransactions.map((t) => (
                  <option key={t.id} value={t.id}>
                    #{t.id} (listing #{t.listing_id})
                  </option>
                ))}
              </select>
            </div>
            {selectedTxId && (
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Applicable Rule
                </label>
                <select
                  value={selectedRuleId}
                  onChange={(e) => setSelectedRuleId(e.target.value)}
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                  required
                >
                  <option value="">
                    {applicableRules.length === 0 ? "No applicable rules found" : "Select a rule"}
                  </option>
                  {applicableRules.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.rule_code} — {r.requirement}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {createError && <p className="text-sm text-destructive">{createError}</p>}
            <DialogFooter>
              <Button type="submit" className="w-full">Submit Request</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={respondTarget !== null} onOpenChange={(open) => !open && setRespondTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Respond to ROFR request #{respondTarget?.id}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleRespond} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Status</label>
              <select
                value={respondStatus}
                onChange={(e) => setRespondStatus(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
              >
                <option value="approved">Approved</option>
                <option value="waived">Waived</option>
                <option value="exercised">Exercised</option>
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Notes (optional)
              </label>
              <Input value={respondNotes} onChange={(e) => setRespondNotes(e.target.value)} />
            </div>
            <DialogFooter>
              <Button type="submit" className="w-full">Record Response</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
