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

type Listing = {
  id: number
  seller_id: number
  company: string
  asset_type: string
  quantity: number
  asking_price: number
  issuer_reporting_status: string | null
  issuer_current_information_available: boolean | null
  issuer_jurisdiction: string | null
  is_transferable: boolean
}

type AuctionBid = {
  id: number
  listing_id: number
  bidder_id: number
  quantity: number
  bid_price: number
  note: string | null
  status: "submitted" | "accepted" | "rejected" | "withdrawn"
  decided_at: string | null
  decided_by_user_id: number | null
  resulting_transaction_id: number | null
  created_at: string
}

export function MyListingsPage() {
  const { user } = useAuth()
  const [listings, setListings] = useState<Listing[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [company, setCompany] = useState("")
  const [assetType, setAssetType] = useState("")
  const [quantity, setQuantity] = useState("")
  const [askingPrice, setAskingPrice] = useState("")
  const [issuerJurisdiction, setIssuerJurisdiction] = useState("")
  const [isTransferable, setIsTransferable] = useState(false)
  const [createSubmitting, setCreateSubmitting] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const [bidsByListing, setBidsByListing] = useState<Record<number, AuctionBid[]>>({})
  const [expandedListingId, setExpandedListingId] = useState<number | null>(null)
  const [bidActionError, setBidActionError] = useState<string | null>(null)

  async function loadListings() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/listings")
      if (!response.ok) throw new Error()
      const data = (await response.json()) as Listing[]
      const own = data.filter((listing) => listing.seller_id === user?.id)
      setListings(own)
      await loadBids(own)
    } catch {
      setError("Could not load your listings.")
    } finally {
      setLoading(false)
    }
  }

  async function loadBids(forListings: Listing[]) {
    // As the seller, each of these GETs returns every bid on that
    // listing, not just one bidder's own (sealed from other bidders,
    // not from the seller) - fetched per-listing, same as Browse.tsx's
    // buyer-side equivalent, fine at this prototype's scale.
    const results = await Promise.all(
      forListings.map((l) =>
        apiFetch(`/listings/${l.id}/auction-bids`)
          .then((r) => (r.ok ? (r.json() as Promise<AuctionBid[]>) : []))
          .catch(() => [] as AuctionBid[])
      )
    )
    const map: Record<number, AuctionBid[]> = {}
    forListings.forEach((l, i) => {
      map[l.id] = results[i]
    })
    setBidsByListing(map)
  }

  async function handleAcceptBid(bidId: number) {
    setBidActionError(null)
    const response = await apiFetchQuery(`/auction-bids/${bidId}/accept`, "PUT")
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      setBidActionError(body?.detail ?? "Could not accept this bid.")
      return
    }
    await loadListings()
  }

  async function handleRejectBid(bidId: number) {
    setBidActionError(null)
    const response = await apiFetchQuery(`/auction-bids/${bidId}/reject`, "PUT")
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      setBidActionError(body?.detail ?? "Could not reject this bid.")
      return
    }
    await loadListings()
  }

  useEffect(() => {
    if (user) {
      loadListings()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user])

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateError(null)

    if (!user) return

    const quantityNum = Number(quantity)
    const askingPriceNum = Number(askingPrice)
    if (!company.trim() || !assetType.trim() || !quantityNum || !askingPriceNum) {
      setCreateError("Fill in all required fields.")
      return
    }

    setCreateSubmitting(true)
    try {
      const response = await apiFetch("/listings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          seller_id: user.id,
          company,
          asset_type: assetType,
          quantity: quantityNum,
          asking_price: askingPriceNum,
          issuer_jurisdiction: issuerJurisdiction || null,
          is_transferable: isTransferable,
        }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setCreateError(data?.detail ?? "Could not create listing.")
        return
      }
      setCreateOpen(false)
      setCompany("")
      setAssetType("")
      setQuantity("")
      setAskingPrice("")
      setIssuerJurisdiction("")
      setIsTransferable(false)
      await loadListings()
    } catch {
      setCreateError("Could not reach the server. Please check your connection.")
    } finally {
      setCreateSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Your Listings
          </p>
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            Add Listing
          </Button>
        </div>

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : listings.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            You have no listings yet. Add your first one above.
          </p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Company</div>
              <div>Asset Type</div>
              <div>Quantity</div>
              <div>Asking Price</div>
              <div>Auction Bids</div>
            </div>
            {bidActionError && <p className="text-sm text-destructive">{bidActionError}</p>}
            {listings.map((listing) => {
              const bids = bidsByListing[listing.id] ?? []
              const pendingCount = bids.filter((b) => b.status === "submitted").length
              const expanded = expandedListingId === listing.id
              return (
                <div key={listing.id}>
                  <div className="grid grid-cols-5 items-center gap-4 py-3 text-sm">
                    <div className="font-medium text-foreground">{listing.company}</div>
                    <div className="text-muted-foreground">{listing.asset_type}</div>
                    <div className="text-muted-foreground">{listing.quantity}</div>
                    <div className="text-foreground">{formatMoney(listing.asking_price)}</div>
                    <div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setExpandedListingId(expanded ? null : listing.id)}
                      >
                        {bids.length === 0
                          ? "No bids"
                          : `${bids.length} bid${bids.length === 1 ? "" : "s"}${pendingCount > 0 ? ` (${pendingCount} open)` : ""}`}
                      </Button>
                    </div>
                  </div>
                  {expanded && (
                    <div className="mb-3 rounded-xl border border-border bg-muted/30 p-4">
                      {bids.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No bids on this listing yet.</p>
                      ) : (
                        <div className="divide-y divide-border">
                          {bids.map((bid) => (
                            <div key={bid.id} className="flex items-center justify-between gap-4 py-2 text-sm">
                              <div>
                                <p className="text-foreground">
                                  {bid.quantity} units @ {formatMoney(bid.bid_price)}
                                </p>
                                {bid.note && <p className="text-xs text-muted-foreground">{bid.note}</p>}
                              </div>
                              <div className="flex items-center gap-2">
                                <StatusBadge status={bid.status} />
                                {bid.status === "submitted" && (
                                  <>
                                    <Button size="sm" onClick={() => handleAcceptBid(bid.id)}>Accept</Button>
                                    <Button size="sm" variant="outline" onClick={() => handleRejectBid(bid.id)}>Reject</Button>
                                  </>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add listing</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Company
                </label>
                <Input value={company} onChange={(e) => setCompany(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Asset Type
                </label>
                <Input
                  value={assetType}
                  onChange={(e) => setAssetType(e.target.value)}
                  placeholder="e.g. common_stock"
                  required
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Quantity
                </label>
                <Input
                  type="number"
                  min="1"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Asking Price ($)
                </label>
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={askingPrice}
                  onChange={(e) => setAskingPrice(e.target.value)}
                  required
                />
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Issuer Jurisdiction (optional)
              </label>
              <Input
                value={issuerJurisdiction}
                onChange={(e) => setIssuerJurisdiction(e.target.value)}
                placeholder="e.g. US"
              />
            </div>

            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={isTransferable}
                onChange={(e) => setIsTransferable(e.target.checked)}
                className="h-4 w-4 rounded border-border"
              />
              Known to be transferable
            </label>

            {createError && <p className="text-sm text-destructive">{createError}</p>}

            <DialogFooter>
              <Button type="submit" disabled={createSubmitting} className="w-full">
                {createSubmitting ? "Creating..." : "Create Listing"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
