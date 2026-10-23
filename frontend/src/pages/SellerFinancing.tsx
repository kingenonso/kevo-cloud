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

type Transaction = { id: number; buyer_id: number; seller_id: number; status: string }

type Agreement = {
  id: number
  transaction_id: number
  principal_amount: number
  annual_interest_rate_pct: number
  term_months: number
  payment_frequency: string
  status: string
  restricts_transfer_until_paid: boolean
}

type Payment = {
  id: number
  installment_number: number
  due_date: string
  amount_due: number
  status: string
  paid_amount: number | null
}

type Summary = {
  payments_total: number
  payments_paid: number
  payments_upcoming: number
  payments_overdue: number
  outstanding_amount: number
  total_paid: number
  next_payment_due_date: string | null
  reserve: { required_amount: number; status: string } | null
  collateral: Array<{ id: number; description: string; collateral_type: string; status: string; legal_review_status: string }>
  buyer_account_blocked: boolean | null
}

export function SellerFinancingPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [agreements, setAgreements] = useState<Agreement[]>([])
  const [myTransactions, setMyTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [expanded, setExpanded] = useState<number | null>(null)
  const [payments, setPayments] = useState<Record<number, Payment[]>>({})
  const [summaries, setSummaries] = useState<Record<number, Summary>>({})

  const [createOpen, setCreateOpen] = useState(false)
  const [transactionId, setTransactionId] = useState("")
  const [principalAmount, setPrincipalAmount] = useState("")
  const [annualRate, setAnnualRate] = useState("0")
  const [termMonths, setTermMonths] = useState("")
  const [paymentFrequency, setPaymentFrequency] = useState("monthly")
  const [firstPaymentDueDate, setFirstPaymentDueDate] = useState("")
  const [restrictsTransfer, setRestrictsTransfer] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  async function load() {
    if (!user) return
    setLoading(true)
    setError(null)
    try {
      const [agreementsResp, txResp] = await Promise.all([
        apiFetch("/seller-financing-agreements"),
        apiFetch("/transactions"),
      ])
      if (agreementsResp.ok) setAgreements((await agreementsResp.json()) as Agreement[])
      if (txResp.ok) {
        const txs = (await txResp.json()) as Transaction[]
        setMyTransactions(txs.filter((t) => t.seller_id === user.id))
      }
    } catch {
      setError("Could not load seller financing agreements.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  async function loadDetail(agreementId: number) {
    const [paymentsResp, summaryResp] = await Promise.all([
      apiFetch(`/seller-financing-agreements/${agreementId}/payments`),
      apiFetch(`/seller-financing-agreements/${agreementId}/summary`),
    ])
    if (paymentsResp.ok) {
      const p = (await paymentsResp.json()) as Payment[]
      setPayments((prev) => ({ ...prev, [agreementId]: p }))
    }
    if (summaryResp.ok) {
      const s = (await summaryResp.json()) as Summary
      setSummaries((prev) => ({ ...prev, [agreementId]: s }))
    }
  }

  async function toggleExpand(id: number) {
    if (expanded === id) {
      setExpanded(null)
      return
    }
    setExpanded(id)
    await loadDetail(id)
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateError(null)
    if (!transactionId || !principalAmount || !termMonths || !firstPaymentDueDate) {
      setCreateError("Fill in all required fields.")
      return
    }
    const response = await apiFetch("/seller-financing-agreements", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transaction_id: Number(transactionId),
        principal_amount: Number(principalAmount),
        annual_interest_rate_pct: Number(annualRate) || 0,
        term_months: Number(termMonths),
        payment_frequency: paymentFrequency,
        first_payment_due_date: firstPaymentDueDate,
        restricts_transfer_until_paid: restrictsTransfer,
      }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setCreateError(data?.detail ?? "Could not create this agreement.")
      return
    }
    setCreateOpen(false)
    setTransactionId("")
    setPrincipalAmount("")
    setAnnualRate("0")
    setTermMonths("")
    setFirstPaymentDueDate("")
    setRestrictsTransfer(false)
    await load()
  }

  async function confirmPayment(agreementId: number, paymentId: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/seller-financing-agreements/${agreementId}/payments/${paymentId}/confirm`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not confirm this payment.")
      return
    }
    await loadDetail(agreementId)
  }

  async function markLate(agreementId: number, paymentId: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/seller-financing-agreements/${agreementId}/payments/${paymentId}/mark-late`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not mark this payment late.")
      return
    }
    await loadDetail(agreementId)
  }

  async function markDefaulted(agreementId: number) {
    const reason = window.prompt("Reason for default:")
    if (!reason) return
    const response = await apiFetchQuery(`/seller-financing-agreements/${agreementId}/default`, "PUT", { reason })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not mark this agreement defaulted.")
      return
    }
    await load()
  }

  async function resolveDefault(agreementId: number) {
    const notes = window.prompt("Resolution notes:")
    if (!notes) return
    const response = await apiFetchQuery(`/seller-financing-agreements/${agreementId}/resolve-default`, "PUT", {
      resolution_notes: notes,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not resolve this default.")
      return
    }
    await load()
  }

  async function createReserve(agreementId: number) {
    const amountStr = window.prompt("Required reserve amount ($):")
    if (!amountStr) return
    const response = await apiFetch(`/seller-financing-agreements/${agreementId}/reserve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ required_amount: Number(amountStr) }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not create the reserve.")
      return
    }
    await loadDetail(agreementId)
  }

  async function fundReserve(agreementId: number) {
    const ref = window.prompt("Funded reference:")
    if (!ref) return
    const response = await apiFetchQuery(`/seller-financing-agreements/${agreementId}/reserve/fund`, "PUT", {
      funded_reference: ref,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not fund the reserve.")
      return
    }
    await loadDetail(agreementId)
  }

  async function releaseReserve(agreementId: number) {
    const to = window.prompt("Release to (buyer/seller):")
    if (!to) return
    const ref = window.prompt("Release reference:")
    if (!ref) return
    const response = await apiFetchQuery(`/seller-financing-agreements/${agreementId}/reserve/release`, "PUT", {
      released_to: to,
      released_reference: ref,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not release the reserve.")
      return
    }
    await loadDetail(agreementId)
  }

  async function addCollateral(agreementId: number) {
    const description = window.prompt("Collateral description:")
    if (!description) return
    const collateralType = window.prompt("Collateral type:")
    if (!collateralType) return
    const response = await apiFetch(`/seller-financing-agreements/${agreementId}/collateral`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, collateral_type: collateralType }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not add this collateral record.")
      return
    }
    await loadDetail(agreementId)
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          KEVO never originates, funds, holds, or services this credit arrangement — it
          only records the terms the buyer and seller already agreed to off-platform and
          generates the resulting payment schedule by ordinary amortization arithmetic. No
          money moves through KEVO for the installment payments.
        </p>
      </div>

      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {isAdmin ? "All Seller Financing Agreements" : "Your Seller Financing Agreements"}
          </p>
          {myTransactions.length > 0 && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              New Agreement
            </Button>
          )}
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : agreements.length === 0 ? (
          <p className="text-sm text-muted-foreground">No seller financing agreements yet.</p>
        ) : (
          <div className="space-y-3">
            {agreements.map((a) => (
              <div key={a.id} className="rounded-xl border border-border p-4 text-sm">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-foreground">Agreement #{a.id} — Transaction #{a.transaction_id}</p>
                  <StatusBadge status={a.status} />
                </div>
                <div className="mb-3 flex flex-wrap gap-6 text-xs text-muted-foreground">
                  <span>Principal: {formatMoney(a.principal_amount)}</span>
                  <span>Rate: {a.annual_interest_rate_pct}%</span>
                  <span>Term: {a.term_months} months, {a.payment_frequency}</span>
                  {a.restricts_transfer_until_paid && <span>Transfer restricted until paid</span>}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => toggleExpand(a.id)}>
                    {expanded === a.id ? "Hide Details" : "View Details"}
                  </Button>
                  {a.status === "active" && (
                    <Button size="sm" variant="outline" onClick={() => markDefaulted(a.id)}>
                      Mark Defaulted
                    </Button>
                  )}
                  {isAdmin && a.status === "defaulted" && (
                    <Button size="sm" variant="outline" onClick={() => resolveDefault(a.id)}>
                      Resolve Default
                    </Button>
                  )}
                </div>
                {expanded === a.id && (
                  <div className="mt-4 space-y-4 border-t border-border pt-4">
                    {summaries[a.id] && (
                      <div className="grid grid-cols-2 gap-4 text-xs sm:grid-cols-4">
                        <div><p className="text-muted-foreground">Outstanding</p><p className="font-mono text-foreground">{formatMoney(summaries[a.id].outstanding_amount)}</p></div>
                        <div><p className="text-muted-foreground">Total Paid</p><p className="font-mono text-foreground">{formatMoney(summaries[a.id].total_paid)}</p></div>
                        <div><p className="text-muted-foreground">Overdue</p><p className="font-mono text-foreground">{summaries[a.id].payments_overdue}</p></div>
                        <div><p className="text-muted-foreground">Next Due</p><p className="font-mono text-foreground">{summaries[a.id].next_payment_due_date ?? "-"}</p></div>
                      </div>
                    )}

                    <div>
                      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Payments</p>
                      {(payments[a.id] ?? []).map((p) => (
                        <div key={p.id} className="flex items-center justify-between py-1 text-xs">
                          <span className="text-foreground">#{p.installment_number} — {formatMoney(p.amount_due)} due {new Date(p.due_date).toLocaleDateString()}</span>
                          <div className="flex items-center gap-2">
                            <StatusBadge status={p.status} />
                            {p.status !== "paid" && (
                              <>
                                <Button size="sm" variant="outline" onClick={() => confirmPayment(a.id, p.id)}>Confirm Paid</Button>
                                {p.status !== "late" && (
                                  <Button size="sm" variant="outline" onClick={() => markLate(a.id, p.id)}>Mark Late</Button>
                                )}
                              </>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>

                    <div>
                      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">Reserve</p>
                      {summaries[a.id]?.reserve ? (
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-foreground">Required: {formatMoney(summaries[a.id].reserve!.required_amount)}</span>
                          <div className="flex items-center gap-2">
                            <StatusBadge status={summaries[a.id].reserve!.status} />
                            {summaries[a.id].reserve!.status === "pending" && (
                              <Button size="sm" variant="outline" onClick={() => fundReserve(a.id)}>Mark Funded</Button>
                            )}
                            {summaries[a.id].reserve!.status === "funded" && (
                              <Button size="sm" variant="outline" onClick={() => releaseReserve(a.id)}>Release</Button>
                            )}
                          </div>
                        </div>
                      ) : (
                        <Button size="sm" variant="outline" onClick={() => createReserve(a.id)}>Set Up Reserve</Button>
                      )}
                    </div>

                    <div>
                      <div className="mb-2 flex items-center justify-between">
                        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Collateral</p>
                        <Button size="sm" variant="outline" onClick={() => addCollateral(a.id)}>Add</Button>
                      </div>
                      {(summaries[a.id]?.collateral ?? []).map((c) => (
                        <div key={c.id} className="flex items-center justify-between py-1 text-xs">
                          <span className="text-foreground">{c.description} ({c.collateral_type})</span>
                          <div className="flex items-center gap-2">
                            <StatusBadge status={c.status} />
                            <StatusBadge status={c.legal_review_status} />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create a seller financing agreement</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Transaction</label>
              <select
                value={transactionId}
                onChange={(e) => setTransactionId(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                required
              >
                <option value="">Select one of your transactions</option>
                {myTransactions.map((t) => (
                  <option key={t.id} value={t.id}>#{t.id}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Principal Amount</label>
                <Input type="number" min="0" step="0.01" value={principalAmount} onChange={(e) => setPrincipalAmount(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Annual Interest Rate %</label>
                <Input type="number" min="0" step="0.01" value={annualRate} onChange={(e) => setAnnualRate(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Term (months)</label>
                <Input type="number" min="1" value={termMonths} onChange={(e) => setTermMonths(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Payment Frequency</label>
                <select
                  value={paymentFrequency}
                  onChange={(e) => setPaymentFrequency(e.target.value)}
                  className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                >
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                </select>
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">First Payment Due Date</label>
              <Input type="date" value={firstPaymentDueDate} onChange={(e) => setFirstPaymentDueDate(e.target.value)} required />
            </div>
            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={restrictsTransfer}
                onChange={(e) => setRestrictsTransfer(e.target.checked)}
                className="h-4 w-4 rounded border-border"
              />
              Restrict transfer of this position until fully paid
            </label>
            {createError && <p className="text-sm text-destructive">{createError}</p>}
            <DialogFooter>
              <Button type="submit" className="w-full">Create Agreement</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
