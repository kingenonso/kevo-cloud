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
import { formatLabel } from "@/lib/status"

type Signal = {
  id: number
  company: string
  asset_type: string
  event_type: string
  description: string
  source_url: string
  source_disclosed_at: string
  status: string
  published_at: string | null
  retracted_at: string | null
  disclaimer: string
}

const EVENT_TYPES = ["funding_round_announced", "ipo_s1_filed", "tender_offer_announced", "ma_transaction_announced"]

export function LiquidityEventRadarPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [company, setCompany] = useState("")
  const [assetType, setAssetType] = useState("")
  const [eventType, setEventType] = useState(EVENT_TYPES[0])
  const [description, setDescription] = useState("")
  const [sourceUrl, setSourceUrl] = useState("")
  const [sourceDisclosedAt, setSourceDisclosedAt] = useState("")
  const [createError, setCreateError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/liquidity-event-signals")
      if (!response.ok) throw new Error()
      setSignals((await response.json()) as Signal[])
    } catch {
      setError("Could not load liquidity event signals.")
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
    if (!company.trim() || !assetType.trim() || !description.trim() || !sourceUrl.trim() || !sourceDisclosedAt) {
      setCreateError("Fill in all required fields.")
      return
    }
    const response = await apiFetchQuery("/liquidity-event-signals", "POST", {
      company,
      asset_type: assetType,
      event_type: eventType,
      description,
      source_url: sourceUrl,
      source_disclosed_at: new Date(sourceDisclosedAt).toISOString(),
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setCreateError(data?.detail ?? "Could not create this signal.")
      return
    }
    setCreateOpen(false)
    setCompany("")
    setAssetType("")
    setDescription("")
    setSourceUrl("")
    setSourceDisclosedAt("")
    await load()
  }

  async function publish(id: number) {
    setActionError(null)
    const response = await apiFetchQuery(`/liquidity-event-signals/${id}/publish`, "PUT")
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not publish this signal.")
      return
    }
    await load()
  }

  async function retract(id: number) {
    setActionError(null)
    const notes = window.prompt("Retraction notes (optional):") ?? undefined
    const response = await apiFetchQuery(`/liquidity-event-signals/${id}/retract`, "PUT", { retraction_notes: notes })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not retract this signal.")
      return
    }
    await load()
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">
          Signals reflect already publicly disclosed events only — a closed funding round, an
          IPO/S-1 filing, a publicly announced tender offer or M&amp;A transaction. Never a
          prediction or inferred signal about a not-yet-public event, and never investment
          advice.
        </p>
      </div>

      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Liquidity Event Signals
          </p>
          {isAdmin && (
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              New Signal
            </Button>
          )}
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : signals.length === 0 ? (
          <p className="text-sm text-muted-foreground">No published signals yet.</p>
        ) : (
          <div className="space-y-3">
            {signals.map((s) => (
              <div key={s.id} className="rounded-xl border border-border p-4 text-sm">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium text-foreground">
                    {s.company} ({s.asset_type}) — {formatLabel(s.event_type)}
                  </p>
                  <StatusBadge status={s.status} />
                </div>
                <p className="mb-2 text-muted-foreground">{s.description}</p>
                <p className="mb-2 text-xs text-muted-foreground">
                  Source: <a href={s.source_url} target="_blank" rel="noreferrer" className="underline">{s.source_url}</a>
                  {" "}— disclosed {new Date(s.source_disclosed_at).toLocaleDateString()}
                </p>
                {isAdmin && (
                  <div className="flex gap-2">
                    {s.status === "draft" && (
                      <Button size="sm" variant="outline" onClick={() => publish(s.id)}>
                        Publish
                      </Button>
                    )}
                    {s.status === "published" && (
                      <Button size="sm" variant="outline" onClick={() => retract(s.id)}>
                        Retract
                      </Button>
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
            <DialogTitle>Create a liquidity event signal</DialogTitle>
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
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Event Type</label>
              <select
                value={eventType}
                onChange={(e) => setEventType(e.target.value)}
                className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
              >
                {EVENT_TYPES.map((t) => (
                  <option key={t} value={t}>{formatLabel(t)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Description</label>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">Source URL</label>
              <Input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Source Disclosed At
              </label>
              <Input type="datetime-local" value={sourceDisclosedAt} onChange={(e) => setSourceDisclosedAt(e.target.value)} required />
            </div>
            {createError && <p className="text-sm text-destructive">{createError}</p>}
            <DialogFooter>
              <Button type="submit" className="w-full">Create Signal</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
