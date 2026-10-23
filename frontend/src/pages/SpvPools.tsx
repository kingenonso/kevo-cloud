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

type Pool = {
  id: number
  organizer_id: number
  company: string
  asset_type: string
  sponsor_name: string
  sponsor_is_platform_user: boolean
  minimum_check_size: number
  target_total_amount: number | null
  status: string
  notes: string | null
  disclaimer: string
}

type Commitment = {
  id: number
  pool_id: number
  participant_id: number
  committed_amount: number
  status: string
}

export function SpvPoolsPage() {
  const { user } = useAuth()

  const [pools, setPools] = useState<Pool[]>([])
  const [commitmentsByPool, setCommitmentsByPool] = useState<Record<number, Commitment[]>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [company, setCompany] = useState("")
  const [assetType, setAssetType] = useState("")
  const [sponsorName, setSponsorName] = useState("")
  const [minimumCheckSize, setMinimumCheckSize] = useState("")
  const [targetTotalAmount, setTargetTotalAmount] = useState("")
  const [disclaimerAcknowledged, setDisclaimerAcknowledged] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [commitOpen, setCommitOpen] = useState<Pool | null>(null)
  const [commitAmount, setCommitAmount] = useState("")

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/spv-pools")
      if (!response.ok) throw new Error()
      setPools((await response.json()) as Pool[])
    } catch {
      setError("Could not load SPV pools.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function loadCommitments(poolId: number) {
    const response = await apiFetch(`/spv-pools/${poolId}/commitments`)
    if (response.ok) {
      const data = (await response.json()) as Commitment[]
      setCommitmentsByPool((prev) => ({ ...prev, [poolId]: data }))
    }
  }

  async function toggleExpand(poolId: number) {
    if (expanded === poolId) {
      setExpanded(null)
      return
    }
    setExpanded(poolId)
    if (!commitmentsByPool[poolId]) await loadCommitments(poolId)
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateError(null)
    const minSize = Number(minimumCheckSize)
    if (!company.trim() || !assetType.trim() || !sponsorName.trim() || !minSize) {
      setCreateError("Fill in all required fields.")
      return
    }
    if (!disclaimerAcknowledged) {
      setCreateError("You must acknowledge that KEVO is not the sponsor of this pool.")
      return
    }
    const response = await apiFetchQuery("/spv-pools", "POST", {
      company,
      asset_type: assetType,
      sponsor_name: sponsorName,
      minimum_check_size: minSize,
      legal_disclaimer_acknowledged: disclaimerAcknowledged,
      target_total_amount: targetTotalAmount ? Number(targetTotalAmount) : null,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setCreateError(data?.detail ?? "Could not create this pool.")
      return
    }
    setCreateOpen(false)
    setCompany("")
    setAssetType("")
    setSponsorName("")
    setMinimumCheckSize("")
    setTargetTotalAmount("")
    setDisclaimerAcknowledged(false)
    await load()
  }

  async function closePool(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/spv-pools/${id}/close`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not close this pool.")
      return
    }
    await load()
  }

  async function cancelPool(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/spv-pools/${id}/cancel`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not cancel this pool.")
      return
    }
    await load()
  }

  async function handleCommit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!commitOpen) return
    const amount = Number(commitAmount)
    if (!amount) return
    const response = await apiFetchQuery(`/spv-pools/${commitOpen.id}/commitments`, "POST", {
      committed_amount: amount,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not record this commitment.")
      return
    }
    setCommitOpen(null)
    setCommitAmount("")
    await loadCommitments(commitOpen.id)
  }

  async function withdrawCommitment(commitmentId: number, poolId: number) {
    const response = await apiFetchQuery(`/spv-pool-commitments/${commitmentId}/withdraw`, "PUT")
    if (response.ok) await loadCommitments(poolId)
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          KEVO is not the sponsor, general partner, or manager of any pool listed here and
          does not form or operate it. The named sponsor is solely responsible for legally
          forming and operating the vehicle. KEVO provides record-keeping only and charges
          no fee of any kind tied to a pool.
        </p>
      </div>

      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            SPV Pools
          </p>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            Organize a Pool
          </Button>
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : pools.length === 0 ? (
          <p className="text-sm text-muted-foreground">No SPV pools yet.</p>
        ) : (
          <div className="space-y-3">
            {pools.map((p) => (
              <div key={p.id} className="rounded-xl border border-border p-4 text-sm">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-medium text-foreground">{p.company} ({p.asset_type})</p>
                    <p className="text-xs text-muted-foreground">Sponsor: {p.sponsor_name}</p>
                  </div>
                  <StatusBadge status={p.status} />
                </div>
                <div className="mb-3 flex flex-wrap gap-6 text-xs text-muted-foreground">
                  <span>Minimum check: {formatMoney(p.minimum_check_size)}</span>
                  {p.target_total_amount && <span>Target total: {formatMoney(p.target_total_amount)}</span>}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => toggleExpand(p.id)}>
                    {expanded === p.id ? "Hide Commitments" : "View Commitments"}
                  </Button>
                  {p.status === "forming" && (
                    <Button size="sm" variant="outline" onClick={() => setCommitOpen(p)}>
                      Commit
                    </Button>
                  )}
                  {p.status === "forming" && p.organizer_id === user?.id && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => closePool(p.id)}>
                        Close
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => cancelPool(p.id)}>
                        Cancel
                      </Button>
                    </>
                  )}
                </div>
                {expanded === p.id && (
                  <div className="mt-4 space-y-2 border-t border-border pt-4">
                    {(commitmentsByPool[p.id] ?? []).length === 0 ? (
                      <p className="text-xs text-muted-foreground">No commitments yet.</p>
                    ) : (
                      commitmentsByPool[p.id].map((c) => (
                        <div key={c.id} className="flex items-center justify-between text-xs">
                          <span className="text-foreground">{formatMoney(c.committed_amount)}</span>
                          <StatusBadge status={c.status} />
                          {c.participant_id === user?.id && c.status === "pending" && (
                            <Button size="sm" variant="outline" onClick={() => withdrawCommitment(c.id, p.id)}>
                              Withdraw
                            </Button>
                          )}
                        </div>
                      ))
                    )}
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
            <DialogTitle>Organize an SPV pool</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Company</label>
                <Input value={company} onChange={(e) => setCompany(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Asset Type</label>
                <Input value={assetType} onChange={(e) => setAssetType(e.target.value)} required />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Sponsor Name (who actually bears legal responsibility for this pool)
              </label>
              <Input value={sponsorName} onChange={(e) => setSponsorName(e.target.value)} required />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Minimum Check Size ($)
                </label>
                <Input type="number" min="0" step="0.01" value={minimumCheckSize} onChange={(e) => setMinimumCheckSize(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Target Total Amount (optional)
                </label>
                <Input type="number" min="0" step="0.01" value={targetTotalAmount} onChange={(e) => setTargetTotalAmount(e.target.value)} />
              </div>
            </div>
            <label className="flex items-start gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={disclaimerAcknowledged}
                onChange={(e) => setDisclaimerAcknowledged(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-border"
              />
              I acknowledge that KEVO is not the sponsor, general partner, or manager of
              this pool, does not form or operate it, and charges no fee of any kind tied
              to it. The named sponsor is solely responsible for legally forming and
              operating this vehicle.
            </label>
            {createError && <p className="text-sm text-destructive">{createError}</p>}
            <DialogFooter>
              <Button type="submit" className="w-full">Create Pool</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={commitOpen !== null} onOpenChange={(open) => !open && setCommitOpen(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Commit to {commitOpen?.company}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCommit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Committed Amount ($) — minimum {commitOpen && formatMoney(commitOpen.minimum_check_size)}
              </label>
              <Input type="number" min="0" step="0.01" value={commitAmount} onChange={(e) => setCommitAmount(e.target.value)} required />
            </div>
            <p className="text-xs text-muted-foreground">
              This is a non-binding statement of intent, not an executed subscription agreement.
            </p>
            <DialogFooter>
              <Button type="submit" className="w-full">Submit Commitment</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
