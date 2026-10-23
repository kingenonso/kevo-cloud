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

type Program = {
  id: number
  company: string
  jurisdiction: string
  price_per_share: number
  opens_at: string
  closes_at: string
  status: string
  is_recurring: boolean
  recurrence_interval_days: number | null
}

type Election = {
  id: number
  program_id: number
  ownership_record_id: number
  holder_id: number
  shares_offered: number
  shares_accepted: number | null
  status: string
  transfer_reviewed: boolean
  rofr_cleared: boolean | null
}

type Settlement = {
  id: number
  election_id: number
  status: string
  funds_received: boolean
  shares_confirmed_transferable: boolean
  funds_released: boolean
}

type OwnershipRecord = {
  id: number
  company: string
  asset_type: string
  quantity: number
  verification_status: string
}

export function TenderOffersPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [programs, setPrograms] = useState<Program[]>([])
  const [elections, setElections] = useState<Election[]>([])
  const [settlements, setSettlements] = useState<Settlement[]>([])
  const [ownershipRecords, setOwnershipRecords] = useState<OwnershipRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [createProgramOpen, setCreateProgramOpen] = useState(false)
  const [pCompany, setPCompany] = useState("")
  const [pJurisdiction, setPJurisdiction] = useState("")
  const [pPrice, setPPrice] = useState("")
  const [pOpensAt, setPOpensAt] = useState("")
  const [pClosesAt, setPClosesAt] = useState("")
  const [createError, setCreateError] = useState<string | null>(null)

  const [electOpen, setElectOpen] = useState<Program | null>(null)
  const [electOwnershipId, setElectOwnershipId] = useState("")
  const [electShares, setElectShares] = useState("")

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [programsResp, electionsResp, settlementsResp, ownershipResp] = await Promise.all([
        apiFetch("/tender-offer-programs"),
        apiFetch("/tender-offer-elections"),
        apiFetch("/tender-offer-settlements"),
        apiFetch("/ownership-records"),
      ])
      if (programsResp.ok) setPrograms((await programsResp.json()) as Program[])
      if (electionsResp.ok) setElections((await electionsResp.json()) as Election[])
      if (settlementsResp.ok) setSettlements((await settlementsResp.json()) as Settlement[])
      if (ownershipResp.ok) {
        const records = (await ownershipResp.json()) as OwnershipRecord[]
        setOwnershipRecords(records.filter((r) => r.verification_status === "verified"))
      }
    } catch {
      setError("Could not load tender offer data.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function handleCreateProgram(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateError(null)
    const price = Number(pPrice)
    if (!pCompany.trim() || !pJurisdiction.trim() || !price || !pOpensAt || !pClosesAt) {
      setCreateError("Fill in all required fields.")
      return
    }
    const response = await apiFetchQuery("/tender-offer-programs", "POST", {
      company: pCompany,
      jurisdiction: pJurisdiction,
      price_per_share: price,
      opens_at: new Date(pOpensAt).toISOString(),
      closes_at: new Date(pClosesAt).toISOString(),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setCreateError(data?.detail ?? "Could not create tender offer program.")
      return
    }
    setCreateProgramOpen(false)
    setPCompany("")
    setPJurisdiction("")
    setPPrice("")
    setPOpensAt("")
    setPClosesAt("")
    await load()
  }

  async function closeProgram(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/tender-offer-programs/${id}/close`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not close this program.")
      return
    }
    await load()
  }

  async function handleElect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!electOpen) return
    const shares = Number(electShares)
    if (!electOwnershipId || !shares) return
    const response = await apiFetchQuery("/tender-offer-elections", "POST", {
      program_id: electOpen.id,
      ownership_record_id: Number(electOwnershipId),
      shares_offered: shares,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not submit this election.")
      return
    }
    setElectOpen(null)
    setElectOwnershipId("")
    setElectShares("")
    await load()
  }

  async function withdrawElection(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/tender-offer-elections/${id}/withdraw`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not withdraw this election.")
      return
    }
    await load()
  }

  async function finalizeElection(id: number, accepted: boolean) {
    setActionError(null)
    const election = elections.find((e) => e.id === id)
    const params: Record<string, string | number | boolean> = { accepted }
    if (accepted) {
      const sharesStr = window.prompt("Shares accepted (cannot exceed shares offered):", String(election?.shares_offered ?? ""))
      if (sharesStr === null) return
      params.shares_accepted = Number(sharesStr)
    }
    const response = await apiFetchQuery(`/tender-offer-elections/${id}/finalize`, "PUT", params)
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not finalize this election.")
      return
    }
    await load()
  }

  async function transferReview(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/tender-offer-elections/${id}/transfer-review`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not record transfer review.")
      return
    }
    await load()
  }

  async function createSettlement(electionId: number) {
    setActionError(null)
    const response = await apiFetchQuery("/tender-offer-settlements", "POST", { election_id: electionId })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not create settlement tracking.")
      return
    }
    await load()
  }

  async function settlementAction(id: number, action: "confirm-funds-received" | "confirm-shares-transferable" | "release-funds") {
    setActionError(null)
    const response = await apiFetchQuery(`/tender-offer-settlements/${id}/${action}`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not update this settlement.")
      return
    }
    await load()
  }


  return (
    <div className="space-y-6">
      {actionError && (
        <div className="rounded-xl border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
          {actionError}
        </div>
      )}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Tender Offer Programs
          </p>
          {isAdmin && (
            <Button size="sm" onClick={() => setCreateProgramOpen(true)}>
              New Program
            </Button>
          )}
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : programs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No tender offer programs visible to you yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-6 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Company</div>
              <div>Jurisdiction</div>
              <div>Price/Share</div>
              <div>Window</div>
              <div>Status</div>
              <div>Actions</div>
            </div>
            {programs.map((p) => (
              <div key={p.id} className="grid grid-cols-6 items-center gap-4 py-3 text-sm">
                <div className="font-medium text-foreground">{p.company}</div>
                <div className="text-muted-foreground">{p.jurisdiction}</div>
                <div className="text-foreground">{formatMoney(p.price_per_share)}</div>
                <div className="text-xs text-muted-foreground">
                  {new Date(p.opens_at).toLocaleDateString()} – {new Date(p.closes_at).toLocaleDateString()}
                </div>
                <div><StatusBadge status={p.status} /></div>
                <div className="flex flex-wrap gap-2">
                  {!isAdmin && p.status === "open" && ownershipRecords.length > 0 && (
                    <Button size="sm" variant="outline" onClick={() => setElectOpen(p)}>
                      Elect
                    </Button>
                  )}
                  {isAdmin && p.status === "open" && (
                    <Button size="sm" variant="outline" onClick={() => closeProgram(p.id)}>
                      Close
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
        <p className="px-8 pt-8 pb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          {isAdmin ? "All Elections" : "Your Elections"}
        </p>
        {elections.length === 0 ? (
          <p className="px-8 pb-8 text-sm text-muted-foreground">No elections yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-6 gap-4 border-t border-border px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Program</div>
              <div>Offered</div>
              <div>Accepted</div>
              <div>Status</div>
              <div>Transfer Reviewed</div>
              <div>Actions</div>
            </div>
            {elections.map((e) => (
              <div key={e.id} className="grid grid-cols-6 items-center gap-4 px-8 py-3 text-sm">
                <div className="text-foreground">#{e.program_id}</div>
                <div className="text-muted-foreground">{e.shares_offered}</div>
                <div className="text-muted-foreground">{e.shares_accepted ?? "-"}</div>
                <div><StatusBadge status={e.status} /></div>
                <div className="text-muted-foreground">{e.transfer_reviewed ? "Yes" : "No"}</div>
                <div className="flex flex-wrap gap-2">
                  {!isAdmin && e.holder_id === user?.id && e.status === "pending" && (
                    <Button size="sm" variant="outline" onClick={() => withdrawElection(e.id)}>
                      Withdraw
                    </Button>
                  )}
                  {isAdmin && e.status === "pending" && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => finalizeElection(e.id, true)}>
                        Accept
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => finalizeElection(e.id, false)}>
                        Decline
                      </Button>
                    </>
                  )}
                  {isAdmin && e.status === "accepted" && !e.transfer_reviewed && (
                    <Button size="sm" variant="outline" onClick={() => transferReview(e.id)}>
                      Transfer-Review
                    </Button>
                  )}
                  {isAdmin && e.status === "accepted" && e.transfer_reviewed && !settlements.some((s) => s.election_id === e.id) && (
                    <Button size="sm" variant="outline" onClick={() => createSettlement(e.id)}>
                      Start Settlement
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
        <p className="px-8 pt-8 pb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Settlements
        </p>
        {settlements.length === 0 ? (
          <p className="px-8 pb-8 text-sm text-muted-foreground">No settlements tracked yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 border-t border-border px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Election</div>
              <div>Status</div>
              <div>Funds Received</div>
              <div>Shares Transferable</div>
              <div>Actions</div>
            </div>
            {settlements.map((s) => (
              <div key={s.id} className="grid grid-cols-5 items-center gap-4 px-8 py-3 text-sm">
                <div className="text-foreground">#{s.election_id}</div>
                <div><StatusBadge status={s.status} /></div>
                <div className="text-muted-foreground">{s.funds_received ? "Yes" : "No"}</div>
                <div className="text-muted-foreground">{s.shares_confirmed_transferable ? "Yes" : "No"}</div>
                <div className="flex flex-wrap gap-2">
                  {isAdmin && !s.funds_received && (
                    <Button size="sm" variant="outline" onClick={() => settlementAction(s.id, "confirm-funds-received")}>
                      Confirm Funds
                    </Button>
                  )}
                  {isAdmin && !s.shares_confirmed_transferable && (
                    <Button size="sm" variant="outline" onClick={() => settlementAction(s.id, "confirm-shares-transferable")}>
                      Confirm Shares
                    </Button>
                  )}
                  {isAdmin && s.funds_received && s.shares_confirmed_transferable && !s.funds_released && (
                    <Button size="sm" variant="outline" onClick={() => settlementAction(s.id, "release-funds")}>
                      Release Funds
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={createProgramOpen} onOpenChange={setCreateProgramOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create a tender offer program</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateProgram} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Company</label>
                <Input value={pCompany} onChange={(e) => setPCompany(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Jurisdiction</label>
                <Input value={pJurisdiction} onChange={(e) => setPJurisdiction(e.target.value)} placeholder="e.g. US" required />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Price Per Share ($)</label>
              <Input type="number" min="0" step="0.01" value={pPrice} onChange={(e) => setPPrice(e.target.value)} required />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Opens At</label>
                <Input type="datetime-local" value={pOpensAt} onChange={(e) => setPOpensAt(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Closes At</label>
                <Input type="datetime-local" value={pClosesAt} onChange={(e) => setPClosesAt(e.target.value)} required />
              </div>
            </div>
            {createError && <p className="text-sm text-destructive">{createError}</p>}
            <DialogFooter>
              <Button type="submit" className="w-full">Create Program</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={electOpen !== null} onOpenChange={(open) => !open && setElectOpen(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Elect to participate — {electOpen?.company}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleElect} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Ownership Record</label>
              <select
                value={electOwnershipId}
                onChange={(e) => setElectOwnershipId(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                required
              >
                <option value="">Select a verified holding in {electOpen?.company}</option>
                {ownershipRecords
                  .filter((r) => r.company === electOpen?.company)
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      #{r.id} — {r.quantity} units
                    </option>
                  ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Shares Offered</label>
              <Input type="number" min="1" value={electShares} onChange={(e) => setElectShares(e.target.value)} required />
            </div>
            <DialogFooter>
              <Button type="submit" className="w-full">Submit Election</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
