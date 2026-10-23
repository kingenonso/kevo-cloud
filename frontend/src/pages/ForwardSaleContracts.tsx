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
import { formatLabel } from "@/lib/status"

type Listing = {
  id: number
  seller_id: number
  company: string
  asset_type: string
}

type Contract = {
  id: number
  listing_id: number
  seller_id: number
  buyer_id: number
  company: string
  asset_type: string
  floor_price: number
  cap_price: number
  prepaid_amount: number
  trigger_event: string
  governing_document_review_status: string
  status: string
  final_price: number | null
  final_quantity: number | null
  created_by_user_id: number
}

const TRIGGER_EVENTS = ["holding_period_expiration", "issuer_consent_or_rofr_cleared", "liquidity_event_ipo_or_acquisition"]

export function ForwardSaleContractsPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [contracts, setContracts] = useState<Contract[]>([])
  const [myListings, setMyListings] = useState<Listing[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [listingId, setListingId] = useState("")
  const [buyerId, setBuyerId] = useState("")
  const [floorPrice, setFloorPrice] = useState("")
  const [capPrice, setCapPrice] = useState("")
  const [prepaidAmount, setPrepaidAmount] = useState("")
  const [triggerEvent, setTriggerEvent] = useState(TRIGGER_EVENTS[0])
  const [attested, setAttested] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  async function load() {
    if (!user) return
    setLoading(true)
    setError(null)
    try {
      const [contractsResp, listingsResp] = await Promise.all([
        apiFetch("/forward-sale-contracts"),
        apiFetch("/listings"),
      ])
      if (contractsResp.ok) setContracts((await contractsResp.json()) as Contract[])
      if (listingsResp.ok) {
        const listings = (await listingsResp.json()) as Listing[]
        setMyListings(listings.filter((l) => l.seller_id === user.id))
      }
    } catch {
      setError("Could not load forward-sale contracts.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateError(null)
    const floor = Number(floorPrice)
    const cap = Number(capPrice)
    const prepaid = Number(prepaidAmount)
    if (!listingId || !buyerId || !floor || !cap || !prepaid) {
      setCreateError("Fill in all required fields.")
      return
    }
    if (!attested) {
      setCreateError("The seller attestation is required.")
      return
    }
    const response = await apiFetchQuery("/forward-sale-contracts", "POST", {
      listing_id: Number(listingId),
      buyer_id: Number(buyerId),
      floor_price: floor,
      cap_price: cap,
      prepaid_amount: prepaid,
      trigger_event: triggerEvent,
      seller_attests_no_governing_document_prohibition: attested,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setCreateError(data?.detail ?? "Could not create this contract.")
      return
    }
    setCreateOpen(false)
    setListingId("")
    setBuyerId("")
    setFloorPrice("")
    setCapPrice("")
    setPrepaidAmount("")
    setAttested(false)
    await load()
  }

  async function accept(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/forward-sale-contracts/${id}/accept`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not accept this contract.")
      return
    }
    await load()
  }

  async function cancel(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/forward-sale-contracts/${id}/cancel`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not cancel this contract.")
      return
    }
    await load()
  }

  async function reviewGoverningDocument(id: number, status: "reviewed_ok" | "reviewed_flagged") {
    setActionError(null)
    const notes = window.prompt("Review notes (optional):") ?? undefined
    const response = await apiFetchQuery(`/forward-sale-contracts/${id}/governing-document-review`, "PUT", {
      review_status: status,
      review_notes: notes,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not record this review.")
      return
    }
    await load()
  }

  async function settle(id: number) {
    setActionError(null)
    const priceStr = window.prompt("Final price (must be within the floor/cap corridor):")
    if (priceStr === null) return
    const response = await apiFetchQuery(`/forward-sale-contracts/${id}/settle`, "PUT", {
      final_price: Number(priceStr),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not settle this contract.")
      return
    }
    await load()
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          Uses a floor/cap price corridor rather than a single fixed price, to avoid IRC
          §1259 constructive-sale treatment. The named buyer must already have an
          admin-verified Eligible Contract Participant eligibility record. KEVO cannot
          verify a company's governing documents — the seller attests directly, and an
          admin can separately flag a review.
        </p>
      </div>

      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            {isAdmin ? "All Forward-Sale Contracts" : "Your Forward-Sale Contracts"}
          </p>
          {myListings.length > 0 && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              Propose Contract
            </Button>
          )}
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : contracts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No forward-sale contracts yet.</p>
        ) : (
          <div className="space-y-3">
            {contracts.map((c) => (
              <div key={c.id} className="rounded-xl border border-border p-4 text-sm">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-foreground">{c.company} ({c.asset_type})</p>
                  <StatusBadge status={c.status} />
                </div>
                <div className="mb-3 flex flex-wrap gap-6 text-xs text-muted-foreground">
                  <span>Floor–Cap: {formatMoney(c.floor_price)} – {formatMoney(c.cap_price)}</span>
                  <span>Prepaid: {formatMoney(c.prepaid_amount)}</span>
                  <span>Trigger: {formatLabel(c.trigger_event)}</span>
                  <span>Governing docs: <StatusBadge status={c.governing_document_review_status} /></span>
                  {c.final_price !== null && <span>Settled at: {formatMoney(c.final_price)}</span>}
                </div>
                <div className="flex flex-wrap gap-2">
                  {!isAdmin && c.status === "proposed" && c.created_by_user_id !== user?.id && (c.buyer_id === user?.id || c.seller_id === user?.id) && (
                    <Button size="sm" variant="outline" onClick={() => accept(c.id)}>
                      Accept
                    </Button>
                  )}
                  {(c.buyer_id === user?.id || c.seller_id === user?.id || isAdmin) && ["proposed", "accepted"].includes(c.status) && (
                    <Button size="sm" variant="outline" onClick={() => cancel(c.id)}>
                      Cancel
                    </Button>
                  )}
                  {isAdmin && c.governing_document_review_status === "not_reviewed" && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => reviewGoverningDocument(c.id, "reviewed_ok")}>
                        Mark Reviewed OK
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => reviewGoverningDocument(c.id, "reviewed_flagged")}>
                        Flag
                      </Button>
                    </>
                  )}
                  {isAdmin && c.status === "accepted" && (
                    <Button size="sm" variant="outline" onClick={() => settle(c.id)}>
                      Settle
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
            <DialogTitle>Propose a forward-sale contract</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Listing</label>
              <select
                value={listingId}
                onChange={(e) => setListingId(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                required
              >
                <option value="">Select one of your listings</option>
                {myListings.map((l) => (
                  <option key={l.id} value={l.id}>#{l.id} — {l.company} ({l.asset_type})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Buyer User ID (must have a verified Eligible Contract Participant record)
              </label>
              <Input type="number" value={buyerId} onChange={(e) => setBuyerId(e.target.value)} required />
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Floor Price</label>
                <Input type="number" min="0" step="0.01" value={floorPrice} onChange={(e) => setFloorPrice(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Cap Price</label>
                <Input type="number" min="0" step="0.01" value={capPrice} onChange={(e) => setCapPrice(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Prepaid Amount</label>
                <Input type="number" min="0" step="0.01" value={prepaidAmount} onChange={(e) => setPrepaidAmount(e.target.value)} required />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Trigger Event</label>
              <select
                value={triggerEvent}
                onChange={(e) => setTriggerEvent(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
              >
                {TRIGGER_EVENTS.map((t) => (
                  <option key={t} value={t}>{formatLabel(t)}</option>
                ))}
              </select>
            </div>
            <label className="flex items-start gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={attested}
                onChange={(e) => setAttested(e.target.checked)}
                className="mt-0.5 h-4 w-4 rounded border-border"
              />
              I attest that this company's governing documents do not prohibit this arrangement.
            </label>
            {createError && <p className="text-sm text-destructive">{createError}</p>}
            <DialogFooter>
              <Button type="submit" className="w-full">Propose Contract</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
