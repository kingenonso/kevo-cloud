import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch } from "@/lib/auth"
import { apiFetchQuery } from "@/lib/api"
import { useAuth } from "@/contexts/AuthContext"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { formatLabel } from "@/lib/status"

type EligibilityRecord = {
  id: number
  buyer_id: number
  investor_type: string
  classification: string
  status: string
  verification_method: string | null
  evidence_reference: string | null
  effective_date: string | null
  review_date: string | null
  jurisdiction: string | null
}

export function EligibilityPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [records, setRecords] = useState<EligibilityRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [investorType, setInvestorType] = useState("")
  const [classification, setClassification] = useState("")
  const [verificationMethod, setVerificationMethod] = useState("")
  const [jurisdiction, setJurisdiction] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/investor-eligibility")
      if (!response.ok) throw new Error()
      setRecords((await response.json()) as EligibilityRecord[])
    } catch {
      setError("Could not load eligibility records.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitError(null)
    if (!user || !investorType.trim() || !classification.trim()) {
      setSubmitError("Fill in all required fields.")
      return
    }
    setSubmitting(true)
    try {
      const response = await apiFetch("/investor-eligibility", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          buyer_id: user.id,
          investor_type: investorType,
          classification,
          verification_method: verificationMethod || null,
          jurisdiction: jurisdiction || null,
        }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setSubmitError(data?.detail ?? "Could not submit this eligibility record.")
        return
      }
      setInvestorType("")
      setClassification("")
      setVerificationMethod("")
      setJurisdiction("")
      await load()
    } catch {
      setSubmitError("Could not reach the server.")
    } finally {
      setSubmitting(false)
    }
  }

  async function verify(id: number, status: "verified" | "rejected") {
    setActionError(null)
    const response = await apiFetchQuery(`/investor-eligibility/${id}/verify`, "PUT", { status })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not update this record.")
      return
    }
    await load()
  }

  return (
    <div className="space-y-6">
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          {isAdmin ? "All Investor Eligibility Records" : "Your Investor Eligibility Records"}
        </p>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : records.length === 0 ? (
          <p className="text-sm text-muted-foreground">No eligibility records yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Investor Type</div>
              <div>Classification</div>
              <div>Jurisdiction</div>
              <div>Status</div>
              {isAdmin && <div>Actions</div>}
            </div>
            {records.map((r) => (
              <div key={r.id} className={`grid items-center gap-4 py-3 text-sm ${isAdmin ? "grid-cols-5" : "grid-cols-4"}`}>
                <div className="text-foreground">{formatLabel(r.investor_type)}</div>
                <div className="text-muted-foreground">{formatLabel(r.classification)}</div>
                <div className="text-muted-foreground">{r.jurisdiction ?? "-"}</div>
                <div><StatusBadge status={r.status} /></div>
                {isAdmin && (
                  <div className="flex gap-2">
                    {r.status === "pending" && (
                      <>
                        <Button size="sm" variant="outline" onClick={() => verify(r.id, "verified")}>
                          Verify
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => verify(r.id, "rejected")}>
                          Reject
                        </Button>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Submit a New Eligibility Record
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Investor Type
              </label>
              <Input value={investorType} onChange={(e) => setInvestorType(e.target.value)} placeholder="e.g. individual" required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Classification
              </label>
              <Input
                value={classification}
                onChange={(e) => setClassification(e.target.value)}
                placeholder="e.g. accredited_investor, eligible_contract_participant"
                required
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Verification Method (optional)
              </label>
              <Input value={verificationMethod} onChange={(e) => setVerificationMethod(e.target.value)} />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Jurisdiction (optional)
              </label>
              <Input value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} placeholder="e.g. US" />
            </div>
          </div>
          {submitError && <p className="text-sm text-destructive">{submitError}</p>}
          <Button type="submit" disabled={submitting}>
            {submitting ? "Submitting..." : "Submit Record"}
          </Button>
        </form>
      </div>
    </div>
  )
}
