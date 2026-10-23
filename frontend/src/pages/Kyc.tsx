import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch } from "@/lib/auth"
import { apiFetchQuery } from "@/lib/api"
import { useAuth } from "@/contexts/AuthContext"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { formatLabel } from "@/lib/status"

type KycFact = {
  id: number
  jurisdiction: string
  fact_type: string
  fact_value: string
  as_of_date: string | null
  verification_status: string
  source_reference: string | null
  superseded_by_id: number | null
}

export function KycPage() {
  const { user } = useAuth()

  const [kycStatus, setKycStatus] = useState<string | null>(null)
  const [facts, setFacts] = useState<KycFact[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [jurisdiction, setJurisdiction] = useState("")
  const [factType, setFactType] = useState("")
  const [factValue, setFactValue] = useState("")
  const [asOfDate, setAsOfDate] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  async function load() {
    if (!user) return
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch(`/kyc-facts/user/${user.id}`)
      if (!response.ok) throw new Error()
      const data = (await response.json()) as { kyc_status: string; kyc_facts: KycFact[] }
      setKycStatus(data.kyc_status)
      setFacts(data.kyc_facts)
    } catch {
      setError("Could not load your KYC facts.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitError(null)
    if (!user || !jurisdiction.trim() || !factType.trim() || !factValue.trim()) {
      setSubmitError("Fill in all required fields.")
      return
    }
    setSubmitting(true)
    try {
      const response = await apiFetch("/kyc-facts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.id,
          jurisdiction,
          fact_type: factType,
          fact_value: factValue,
          as_of_date: asOfDate || null,
        }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setSubmitError(data?.detail ?? "Could not submit this fact.")
        return
      }
      setJurisdiction("")
      setFactType("")
      setFactValue("")
      setAsOfDate("")
      await load()
    } catch {
      setSubmitError("Could not reach the server.")
    } finally {
      setSubmitting(false)
    }
  }

  async function verify(factId: number, status: "verified" | "rejected") {
    setActionError(null)
    const response = await apiFetchQuery(`/kyc-facts/${factId}/verify`, "PUT", { status })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not update verification status.")
      return
    }
    await load()
  }

  const isAdmin = user?.account_type === "admin"

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Overall KYC Status
        </p>
        {kycStatus && <StatusBadge status={kycStatus} />}
      </div>

      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Your KYC Facts
        </p>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : facts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No KYC facts on file yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Jurisdiction</div>
              <div>Fact Type</div>
              <div>Value</div>
              <div>Status</div>
              {isAdmin && <div>Actions</div>}
            </div>
            {facts.map((f) => (
              <div key={f.id} className={`grid items-center gap-4 py-3 text-sm ${isAdmin ? "grid-cols-5" : "grid-cols-4"}`}>
                <div className="text-foreground">{f.jurisdiction}</div>
                <div className="text-muted-foreground">{formatLabel(f.fact_type)}</div>
                <div className="text-foreground">{f.fact_value}</div>
                <div><StatusBadge status={f.verification_status} /></div>
                {isAdmin && (
                  <div className="flex gap-2">
                    {f.verification_status === "pending" && (
                      <>
                        <Button size="sm" variant="outline" onClick={() => verify(f.id, "verified")}>
                          Verify
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => verify(f.id, "rejected")}>
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
          Submit a New KYC Fact
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Jurisdiction
              </label>
              <Input value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} placeholder="e.g. US" required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Fact Type
              </label>
              <Input value={factType} onChange={(e) => setFactType(e.target.value)} placeholder="e.g. accredited_investor" required />
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Fact Value
            </label>
            <Input value={factValue} onChange={(e) => setFactValue(e.target.value)} required />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              As Of Date (optional)
            </label>
            <Input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
          </div>
          {submitError && <p className="text-sm text-destructive">{submitError}</p>}
          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Submitting..." : "Submit Fact"}
          </Button>
        </form>
      </div>
    </div>
  )
}
