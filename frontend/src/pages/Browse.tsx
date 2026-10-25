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
  is_transferable: boolean
}

type BuyerInterest = {
  id: number
  buyer_id: number
  company: string
  asset_type: string
  desired_quantity: number
  maximum_price: number
  status: string
}

type LiquidityCommitment = {
  id: number
  buyer_id: number
  company: string
  asset_type: string
  min_quantity: number | null
  max_quantity: number | null
  min_price: number | null
  max_price: number | null
  status: string
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

export function BrowsePage() {
  const { user } = useAuth()

  const [listings, setListings] = useState<Listing[]>([])
  const [interests, setInterests] = useState<BuyerInterest[]>([])
  const [commitments, setCommitments] = useState<LiquidityCommitment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [search, setSearch] = useState("")

  const [interestOpen, setInterestOpen] = useState(false)
  const [iCompany, setICompany] = useState("")
  const [iAssetType, setIAssetType] = useState("")
  const [iQuantity, setIQuantity] = useState("")
  const [iMaxPrice, setIMaxPrice] = useState("")
  const [interestError, setInterestError] = useState<string | null>(null)

  const [commitOpen, setCommitOpen] = useState(false)
  const [cCompany, setCCompany] = useState("")
  const [cAssetType, setCAssetType] = useState("")
  const [cMinQty, setCMinQty] = useState("")
  const [cMaxQty, setCMaxQty] = useState("")
  const [cMinPrice, setCMinPrice] = useState("")
  const [cMaxPrice, setCMaxPrice] = useState("")
  const [commitError, setCommitError] = useState<string | null>(null)

  const [bidsByListing, setBidsByListing] = useState<Record<number, AuctionBid[]>>({})
  const [bidListing, setBidListing] = useState<Listing | null>(null)
  const [bidQuantity, setBidQuantity] = useState("")
  const [bidPrice, setBidPrice] = useState("")
  const [bidNote, setBidNote] = useState("")
  const [bidSubmitting, setBidSubmitting] = useState(false)
  const [bidError, setBidError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [listingsResp, interestsResp, commitmentsResp] = await Promise.all([
        apiFetch("/listings"),
        apiFetch("/buyer-interests"),
        apiFetch("/liquidity-commitments"),
      ])
      let loadedListings: Listing[] = []
      if (listingsResp.ok) {
        loadedListings = (await listingsResp.json()) as Listing[]
        setListings(loadedListings)
      }
      if (interestsResp.ok) setInterests((await interestsResp.json()) as BuyerInterest[])
      if (commitmentsResp.ok) setCommitments((await commitmentsResp.json()) as LiquidityCommitment[])
      await loadBids(loadedListings)
    } catch {
      setError("Could not load the marketplace.")
    } finally {
      setLoading(false)
    }
  }

  async function loadBids(forListings: Listing[]) {
    // Sealed-bid design: as a non-seller this only ever returns the
    // current user's own bid for each listing, never another buyer's -
    // fetched per-listing (no aggregate "my bids" endpoint exists), fine
    // at this prototype's scale. Skipped for listings the user owns,
    // since sellers can't bid on their own listing.
    const biddable = forListings.filter((l) => l.seller_id !== user?.id)
    const results = await Promise.all(
      biddable.map((l) =>
        apiFetch(`/listings/${l.id}/auction-bids`)
          .then((r) => (r.ok ? (r.json() as Promise<AuctionBid[]>) : []))
          .catch(() => [] as AuctionBid[])
      )
    )
    const map: Record<number, AuctionBid[]> = {}
    biddable.forEach((l, i) => {
      map[l.id] = results[i]
    })
    setBidsByListing(map)
  }

  useEffect(() => {
    load()
  }, [])

  async function handleCreateInterest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setInterestError(null)
    if (!user) return
    const qty = Number(iQuantity)
    const maxPrice = Number(iMaxPrice)
    if (!iCompany.trim() || !iAssetType.trim() || !qty || !maxPrice) {
      setInterestError("Fill in all required fields.")
      return
    }
    const response = await apiFetch("/buyer-interests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        buyer_id: user.id,
        company: iCompany,
        asset_type: iAssetType,
        desired_quantity: qty,
        maximum_price: maxPrice,
      }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setInterestError(data?.detail ?? "Could not create this interest.")
      return
    }
    setInterestOpen(false)
    setICompany("")
    setIAssetType("")
    setIQuantity("")
    setIMaxPrice("")
    await load()
  }

  async function handleCreateCommitment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCommitError(null)
    if (!user) return
    if (!cCompany.trim() || !cAssetType.trim()) {
      setCommitError("Company and asset type are required.")
      return
    }
    const response = await apiFetch("/liquidity-commitments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        buyer_id: user.id,
        company: cCompany,
        asset_type: cAssetType,
        min_quantity: cMinQty ? Number(cMinQty) : null,
        max_quantity: cMaxQty ? Number(cMaxQty) : null,
        min_price: cMinPrice ? Number(cMinPrice) : null,
        max_price: cMaxPrice ? Number(cMaxPrice) : null,
      }),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setCommitError(data?.detail ?? "Could not create this commitment.")
      return
    }
    setCommitOpen(false)
    setCCompany("")
    setCAssetType("")
    setCMinQty("")
    setCMaxQty("")
    setCMinPrice("")
    setCMaxPrice("")
    await load()
  }

  async function withdrawInterest(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/buyer-interests/${id}/withdraw`, "POST")
    if (!response.ok) {
      setActionError("Could not withdraw this interest.")
      return
    }
    await load()
  }

  async function withdrawCommitment(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/liquidity-commitments/${id}/withdraw`, "PUT")
    if (!response.ok) {
      setActionError("Could not withdraw this commitment.")
      return
    }
    await load()
  }

  async function handlePlaceBid(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBidError(null)
    if (!bidListing) return
    const quantity = Number(bidQuantity)
    const price = Number(bidPrice)
    if (!quantity || quantity <= 0 || !price || price <= 0) {
      setBidError("Enter a positive quantity and bid price.")
      return
    }
    setBidSubmitting(true)
    try {
      const response = await apiFetch(`/listings/${bidListing.id}/auction-bids`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity, bid_price: price, note: bidNote || null }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        setBidError(body?.detail ?? "Could not submit this bid.")
        return
      }
      setBidListing(null)
      setBidQuantity("")
      setBidPrice("")
      setBidNote("")
      await load()
    } catch {
      setBidError("Could not reach the server.")
    } finally {
      setBidSubmitting(false)
    }
  }

  async function handleWithdrawBid(bidId: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/auction-bids/${bidId}/withdraw`, "PUT")
    if (!response.ok) {
      setActionError("Could not withdraw this bid.")
      return
    }
    await load()
  }

  const filteredListings = listings.filter(
    (l) => !search || l.company.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="space-y-6">
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Browse Listings
          </p>
          <div className="flex gap-2">
            <Input placeholder="Search by company" value={search} onChange={(e) => setSearch(e.target.value)} className="max-w-xs" />
            <Button size="sm" onClick={() => setInterestOpen(true)}>Express Interest</Button>
            <Button size="sm" variant="outline" onClick={() => setCommitOpen(true)}>New Commitment</Button>
          </div>
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : filteredListings.length === 0 ? (
          <p className="text-sm text-muted-foreground">No listings match.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-6 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Company</div>
              <div>Asset Type</div>
              <div>Quantity</div>
              <div>Asking Price</div>
              <div>Transferable</div>
              <div>Auction Bid</div>
            </div>
            {filteredListings.map((l) => {
              const ownListing = l.seller_id === user?.id
              const myBid = (bidsByListing[l.id] ?? [])[0]
              return (
                <div key={l.id} className="grid grid-cols-6 items-center gap-4 py-3 text-sm">
                  <div className="font-medium text-foreground">{l.company}</div>
                  <div className="text-muted-foreground">{l.asset_type}</div>
                  <div className="text-muted-foreground">{l.quantity}</div>
                  <div className="text-foreground">{formatMoney(l.asking_price)}</div>
                  <div><StatusBadge status={l.is_transferable ? "known_complete" : "cannot_determine"} /></div>
                  <div className="flex items-center gap-2">
                    {ownListing ? (
                      <span className="text-xs text-muted-foreground">Your listing</span>
                    ) : myBid ? (
                      <>
                        <StatusBadge status={myBid.status} />
                        {myBid.status === "submitted" && (
                          <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => handleWithdrawBid(myBid.id)}>
                            Withdraw
                          </Button>
                        )}
                      </>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => setBidListing(l)}>
                        Place Bid
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
        <p className="px-8 pt-8 pb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Your Buyer Interests
        </p>
        {interests.length === 0 ? (
          <p className="px-8 pb-8 text-sm text-muted-foreground">No buyer interests yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 border-t border-border px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Company</div>
              <div>Asset Type</div>
              <div>Desired Qty</div>
              <div>Max Price</div>
              <div>Status</div>
            </div>
            {interests.map((i) => (
              <div key={i.id} className="grid grid-cols-5 items-center gap-4 px-8 py-3 text-sm">
                <div className="text-foreground">{i.company}</div>
                <div className="text-muted-foreground">{i.asset_type}</div>
                <div className="text-muted-foreground">{i.desired_quantity}</div>
                <div className="text-foreground">{formatMoney(i.maximum_price)}</div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={i.status} />
                  {i.status === "active" && (
                    <Button size="sm" variant="outline" onClick={() => withdrawInterest(i.id)}>Withdraw</Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-3xl border border-border bg-card shadow-sm">
        <p className="px-8 pt-8 pb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Your Liquidity Commitments
        </p>
        {commitments.length === 0 ? (
          <p className="px-8 pb-8 text-sm text-muted-foreground">No liquidity commitments yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-5 gap-4 border-t border-border px-8 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Company</div>
              <div>Asset Type</div>
              <div>Quantity Range</div>
              <div>Price Range</div>
              <div>Status</div>
            </div>
            {commitments.map((c) => (
              <div key={c.id} className="grid grid-cols-5 items-center gap-4 px-8 py-3 text-sm">
                <div className="text-foreground">{c.company}</div>
                <div className="text-muted-foreground">{c.asset_type}</div>
                <div className="text-muted-foreground">{c.min_quantity ?? "-"} – {c.max_quantity ?? "-"}</div>
                <div className="text-muted-foreground">
                  {c.min_price ? formatMoney(c.min_price) : "-"} – {c.max_price ? formatMoney(c.max_price) : "-"}
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={c.status} />
                  {c.status === "active" && (
                    <Button size="sm" variant="outline" onClick={() => withdrawCommitment(c.id)}>Withdraw</Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={interestOpen} onOpenChange={setInterestOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>Express buyer interest</DialogTitle></DialogHeader>
          <form onSubmit={handleCreateInterest} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Company</label>
                <Input value={iCompany} onChange={(e) => setICompany(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Asset Type</label>
                <Input value={iAssetType} onChange={(e) => setIAssetType(e.target.value)} required />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Desired Quantity</label>
                <Input type="number" min="1" value={iQuantity} onChange={(e) => setIQuantity(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Maximum Price ($)</label>
                <Input type="number" min="0" step="0.01" value={iMaxPrice} onChange={(e) => setIMaxPrice(e.target.value)} required />
              </div>
            </div>
            {interestError && <p className="text-sm text-destructive">{interestError}</p>}
            <DialogFooter><Button type="submit" className="w-full">Submit Interest</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={commitOpen} onOpenChange={setCommitOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>New liquidity commitment</DialogTitle></DialogHeader>
          <form onSubmit={handleCreateCommitment} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Company</label>
                <Input value={cCompany} onChange={(e) => setCCompany(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Asset Type</label>
                <Input value={cAssetType} onChange={(e) => setCAssetType(e.target.value)} required />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Min Quantity (optional)</label>
                <Input type="number" min="0" value={cMinQty} onChange={(e) => setCMinQty(e.target.value)} />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Max Quantity (optional)</label>
                <Input type="number" min="0" value={cMaxQty} onChange={(e) => setCMaxQty(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Min Price (optional)</label>
                <Input type="number" min="0" step="0.01" value={cMinPrice} onChange={(e) => setCMinPrice(e.target.value)} />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Max Price (optional)</label>
                <Input type="number" min="0" step="0.01" value={cMaxPrice} onChange={(e) => setCMaxPrice(e.target.value)} />
              </div>
            </div>
            {commitError && <p className="text-sm text-destructive">{commitError}</p>}
            <DialogFooter><Button type="submit" className="w-full">Submit Commitment</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={bidListing !== null} onOpenChange={(open) => !open && setBidListing(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Place a sealed bid{bidListing ? ` on ${bidListing.company}` : ""}</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">
            Your quantity and price are your own stated terms, never computed or suggested by
            KEVO. Only the seller (and an admin) can see this bid — other bidders never can.
          </p>
          <form onSubmit={handlePlaceBid} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Quantity</label>
                <Input type="number" min="1" value={bidQuantity} onChange={(e) => setBidQuantity(e.target.value)} required />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Bid Price ($)</label>
                <Input type="number" min="0" step="0.01" value={bidPrice} onChange={(e) => setBidPrice(e.target.value)} required />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Note (optional)</label>
              <Input value={bidNote} onChange={(e) => setBidNote(e.target.value)} />
            </div>
            {bidError && <p className="text-sm text-destructive">{bidError}</p>}
            <DialogFooter>
              <Button type="submit" className="w-full" disabled={bidSubmitting}>
                {bidSubmitting ? "Submitting..." : "Submit Bid"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
