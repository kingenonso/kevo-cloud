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

type OptionFundingReferral = {
  id: number
  holder_id: number
  company: string
  notes: string | null
  status: string
  referred_provider_name: string | null
}

export function OptionFundingPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [referrals, setReferrals] = useState<OptionFundingReferral[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [company, setCompany] = useState("")
  const [notes, setNotes] = useState("")
  const [createSubmitting, setCreateSubmitting] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [referTarget, setReferTarget] = useState<OptionFundingReferral | null>(null)
  const [providerName, setProviderName] = useState("")

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/option-funding-referrals")
      if (!response.ok) throw new Error()
      setReferrals((await response.json()) as OptionFundingReferral[])
    } catch {
      setError("Could not load option funding referrals.")
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
    if (!company.trim()) {
      setCreateError("Company is required.")
      return
    }
    setCreateSubmitting(true)
    try {
      const response = await apiFetchQuery("/option-funding-referrals", "POST", {
        company,
        notes: notes || null,
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setCreateError(data?.detail ?? "Could not create referral request.")
        return
      }
      setCreateOpen(false)
      setCompany("")
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
    const response = await apiFetchQuery(`/option-funding-referrals/${id}/withdraw`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not withdraw this request.")
      return
    }
    await load()
  }

  async function decline(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/option-funding-referrals/${id}/decline`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not decline this request.")
      return
    }
    await load()
  }

  async function close(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/option-funding-referrals/${id}/close`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not close this referral.")
      return
    }
    await load()
  }

  async function handleRefer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!referTarget || !providerName.trim()) return
    const response = await apiFetchQuery(`/option-funding-referrals/${referTarget.id}/refer`, "PUT", {
      referred_provider_name: providerName,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not record this referral.")
      return
    }
    setReferTarget(null)
    setProviderName("")
    await load()
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          KEVO originates nothing here and holds no interest in the outcome - this only
          tracks that you asked for a referral and were pointed at a named, real,
          already-licensed external option-exercise-funding provider.
        </p>
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {isAdmin ? "All Referral Requests" : "Your Referral Requests"}
          </p>
          {!isAdmin && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              Request a Referral
            </Button>
          )}
        </div>

        {actionError && <p className="mb-4 text-sm text-destructive">{actionError}</p>}

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : referrals.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {isAdmin ? "No referral requests yet." : "You have no referral requests yet."}
          </p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>ID</div>
              <div>Company</div>
              <div>Status</div>
              <div>Provider</div>
              <div>Actions</div>
            </div>
            {referrals.map((r) => (
              <div key={r.id} className="grid grid-cols-5 items-center gap-4 py-3 text-sm">
                <div className="text-foreground">{r.id}</div>
                <div className="font-medium text-foreground">{r.company}</div>
                <div><StatusBadge status={r.status} /></div>
                <div className="text-muted-foreground">{r.referred_provider_name ?? "-"}</div>
                <div className="flex flex-wrap gap-2">
                  {!isAdmin && r.holder_id === user?.id && r.status === "requested" && (
                    <Button size="sm" variant="outline" onClick={() => withdraw(r.id)}>
                      Withdraw
                    </Button>
                  )}
                  {isAdmin && r.status === "requested" && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => setReferTarget(r)}>
                        Refer
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => decline(r.id)}>
                        Decline
                      </Button>
                    </>
                  )}
                  {isAdmin && r.status === "referred" && (
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
            <DialogTitle>Request an option-funding referral</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Company
              </label>
              <Input value={company} onChange={(e) => setCompany(e.target.value)} required />
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

      <Dialog open={referTarget !== null} onOpenChange={(open) => !open && setReferTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Record a referral to a real external provider</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleRefer} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Provider Name
              </label>
              <Input value={providerName} onChange={(e) => setProviderName(e.target.value)} required />
            </div>
            <DialogFooter>
              <Button type="submit" className="w-full">
                Record Referral
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
