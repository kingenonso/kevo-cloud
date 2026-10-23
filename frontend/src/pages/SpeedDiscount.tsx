import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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
  asking_price: number
}

type Offer = {
  id: number
  listing_id: number
  seller_id: number
  max_discount_percent: number | null
  floor_price: number | null
  speed_window_days: number
  notes: string | null
  status: string
  disclaimer: string
}

type TimeToSaleStats = {
  status: string
  message?: string
  sample_size?: number
  average_days_to_sale?: number
  median_days_to_sale?: number
}

export function SpeedDiscountPage() {
  const { user } = useAuth()

  const [myListings, setMyListings] = useState<Listing[]>([])
  const [offers, setOffers] = useState<Offer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [listingId, setListingId] = useState("")
  const [maxDiscountPercent, setMaxDiscountPercent] = useState("")
  const [floorPrice, setFloorPrice] = useState("")
  const [speedWindowDays, setSpeedWindowDays] = useState("")
  const [notes, setNotes] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const [statsCompany, setStatsCompany] = useState("")
  const [statsAssetType, setStatsAssetType] = useState("")
  const [stats, setStats] = useState<TimeToSaleStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)

  async function load() {
    if (!user) return
    setLoading(true)
    setError(null)
    try {
      const [listingsResp, offersResp] = await Promise.all([
        apiFetch("/listings"),
        apiFetch("/speed-discount-offers"),
      ])
      if (listingsResp.ok) {
        const listings = (await listingsResp.json()) as Listing[]
        setMyListings(listings.filter((l) => l.seller_id === user.id))
      }
      if (offersResp.ok) setOffers((await offersResp.json()) as Offer[])
    } catch {
      setError("Could not load speed discount offers.")
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
    if (!user || !listingId || !speedWindowDays) {
      setSubmitError("Fill in all required fields.")
      return
    }
    if (!maxDiscountPercent && !floorPrice) {
      setSubmitError("State either a max discount percent or a floor price.")
      return
    }
    setSubmitting(true)
    try {
      const response = await apiFetch("/speed-discount-offers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          listing_id: Number(listingId),
          seller_id: user.id,
          max_discount_percent: maxDiscountPercent ? Number(maxDiscountPercent) : null,
          floor_price: floorPrice ? Number(floorPrice) : null,
          speed_window_days: Number(speedWindowDays),
          notes: notes || null,
        }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setSubmitError(data?.detail ?? "Could not create this offer.")
        return
      }
      setListingId("")
      setMaxDiscountPercent("")
      setFloorPrice("")
      setSpeedWindowDays("")
      setNotes("")
      await load()
    } catch {
      setSubmitError("Could not reach the server.")
    } finally {
      setSubmitting(false)
    }
  }

  async function withdraw(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/speed-discount-offers/${id}/withdraw`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not withdraw this offer.")
      return
    }
    await load()
  }

  async function lookupStats(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!statsCompany.trim() || !statsAssetType.trim()) return
    setStatsLoading(true)
    setStats(null)
    try {
      const response = await apiFetch(
        `/time-to-sale-stats?company=${encodeURIComponent(statsCompany)}&asset_type=${encodeURIComponent(statsAssetType)}`
      )
      if (response.ok) setStats((await response.json()) as TimeToSaleStats)
    } finally {
      setStatsLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          Both features here are pure data: your own stated willingness to discount for
          speed, and a read-only aggregate of how long real completed sales actually took.
          Neither computes, matches, or suggests a price — you and a buyer still agree your
          own price when creating a transaction.
        </p>
      </div>

      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Your Speed Discount Offers
        </p>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : offers.length === 0 ? (
          <p className="text-sm text-muted-foreground">You have no speed discount offers yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-6 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Listing</div>
              <div>Max Discount</div>
              <div>Floor Price</div>
              <div>Window (days)</div>
              <div>Status</div>
              <div>Actions</div>
            </div>
            {offers.map((o) => (
              <div key={o.id} className="grid grid-cols-6 items-center gap-4 py-3 text-sm">
                <div className="text-foreground">#{o.listing_id}</div>
                <div className="text-muted-foreground">{o.max_discount_percent ? `${o.max_discount_percent}%` : "-"}</div>
                <div className="text-muted-foreground">{o.floor_price ? formatMoney(o.floor_price) : "-"}</div>
                <div className="text-muted-foreground">{o.speed_window_days}</div>
                <div><StatusBadge status={o.status} /></div>
                <div>
                  {o.status === "active" && (
                    <Button size="sm" variant="outline" onClick={() => withdraw(o.id)}>
                      Withdraw
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Create a New Offer
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
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
                <option key={l.id} value={l.id}>
                  #{l.id} — {l.company} ({l.asset_type}), asking {formatMoney(l.asking_price)}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Max Discount Percent (optional)
              </label>
              <Input type="number" min="0" max="100" step="0.1" value={maxDiscountPercent} onChange={(e) => setMaxDiscountPercent(e.target.value)} />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Floor Price (optional)
              </label>
              <Input type="number" min="0" step="0.01" value={floorPrice} onChange={(e) => setFloorPrice(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Speed Window (days)
            </label>
            <Input type="number" min="1" value={speedWindowDays} onChange={(e) => setSpeedWindowDays(e.target.value)} required />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Notes (optional)
            </label>
            <Input value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
          {submitError && <p className="text-sm text-destructive">{submitError}</p>}
          <Button type="submit" disabled={submitting}>
            {submitting ? "Submitting..." : "Create Offer"}
          </Button>
        </form>
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Time-to-Sale Statistics
        </p>
        <form onSubmit={lookupStats} className="mb-4 flex flex-wrap gap-3">
          <Input placeholder="Company" value={statsCompany} onChange={(e) => setStatsCompany(e.target.value)} className="max-w-xs" />
          <Input placeholder="Asset Type" value={statsAssetType} onChange={(e) => setStatsAssetType(e.target.value)} className="max-w-xs" />
          <Button type="submit" disabled={statsLoading}>
            {statsLoading ? "Loading..." : "Look Up"}
          </Button>
        </form>
        {stats && stats.status === "insufficient_data" && (
          <p className="text-sm text-muted-foreground">{stats.message}</p>
        )}
        {stats && stats.status === "ok" && (
          <div className="grid grid-cols-3 gap-6 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Sample Size</p>
              <p className="mt-1 font-mono text-foreground">{stats.sample_size}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Average Days To Sale</p>
              <p className="mt-1 font-mono text-foreground">{stats.average_days_to_sale}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Median Days To Sale</p>
              <p className="mt-1 font-mono text-foreground">{stats.median_days_to_sale}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
