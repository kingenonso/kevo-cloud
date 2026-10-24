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
import { useAuth } from "@/contexts/AuthContext"
import { StatusBadge } from "@/components/shared/StatusBadge"

// M33B/M33C (first slices) - admin-only provisioning for both third-party
// API clients (M33B's Liquidity-as-a-Service) and Insights Dashboard
// subscriber accounts (M33C). Both follow the exact same admin-
// provisioned, no-self-serve-signup pattern already used for issuer
// accounts (M33) - this page is the admin console for both.

type ApiKeyRow = {
  id: number
  key_prefix: string
  created_at: string
  revoked_at: string | null
  last_used_at: string | null
}

type ApiClientRow = {
  id: number
  organization_name: string
  contact_email: string
  description: string | null
  active: boolean
  created_at: string
  revoked_at: string | null
  keys: ApiKeyRow[]
}

export function PlatformAccessPage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [clients, setClients] = useState<ApiClientRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [createClientOpen, setCreateClientOpen] = useState(false)
  const [orgName, setOrgName] = useState("")
  const [contactEmail, setContactEmail] = useState("")
  const [description, setDescription] = useState("")
  const [createClientError, setCreateClientError] = useState<string | null>(null)

  const [revealedKey, setRevealedKey] = useState<{ organization: string; key: string } | null>(null)

  const [createSubOpen, setCreateSubOpen] = useState(false)
  const [subName, setSubName] = useState("")
  const [subEmail, setSubEmail] = useState("")
  const [subPassword, setSubPassword] = useState("")
  const [subOrg, setSubOrg] = useState("")
  const [subType, setSubType] = useState("vc")
  const [createSubError, setCreateSubError] = useState<string | null>(null)
  const [createSubSuccess, setCreateSubSuccess] = useState<string | null>(null)

  async function loadClients() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/admin/api-clients")
      if (!response.ok) throw new Error()
      setClients((await response.json()) as ApiClientRow[])
    } catch {
      setError("Could not load API clients.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isAdmin) loadClients()
  }, [isAdmin])

  async function handleCreateClient(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateClientError(null)
    try {
      const response = await apiFetch("/admin/api-clients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          organization_name: orgName,
          contact_email: contactEmail,
          description: description || null,
        }),
      })
      const data = await response.json()
      if (!response.ok) {
        setCreateClientError(data.detail ?? "Could not create API client.")
        return
      }
      setRevealedKey({ organization: data.api_client.organization_name, key: data.api_key })
      setCreateClientOpen(false)
      setOrgName("")
      setContactEmail("")
      setDescription("")
      loadClients()
    } catch {
      setCreateClientError("Could not reach the server.")
    }
  }

  async function handleRevoke(clientId: number) {
    await apiFetch(`/admin/api-clients/${clientId}/revoke`, { method: "PUT" })
    loadClients()
  }

  async function handleRotateKey(clientId: number, organization: string) {
    const response = await apiFetch(`/admin/api-clients/${clientId}/keys`, { method: "POST" })
    const data = await response.json()
    if (response.ok) {
      setRevealedKey({ organization, key: data.api_key })
      loadClients()
    }
  }

  async function handleCreateSubscriber(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setCreateSubError(null)
    setCreateSubSuccess(null)
    try {
      const response = await apiFetch("/admin/insights-subscriber-accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: subName,
          email: subEmail,
          password: subPassword,
          organization_name: subOrg,
          subscriber_type: subType,
        }),
      })
      const data = await response.json()
      if (!response.ok) {
        setCreateSubError(data.detail ?? "Could not create insights subscriber account.")
        return
      }
      setCreateSubSuccess(`Created ${data.subscriber.organization_name} (${data.subscriber.email}).`)
      setCreateSubOpen(false)
      setSubName("")
      setSubEmail("")
      setSubPassword("")
      setSubOrg("")
      setSubType("vc")
    } catch {
      setCreateSubError("Could not reach the server.")
    }
  }

  if (!isAdmin) {
    return (
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="text-sm text-muted-foreground">Admin access required.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            API Clients (M33B — Liquidity-as-a-Service)
          </p>
          <Button onClick={() => setCreateClientOpen(true)}>New API Client</Button>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">
          Third-party integration partners, authenticated by API key over transferability,
          compliance-check, and ROFR-status endpoints only. The matching engine is deliberately
          not exposed to any API client — see the ApiClient model's docstring for the Rule 3b-16
          reasoning.
        </p>
        {error && <p className="mb-4 text-sm text-destructive">{error}</p>}
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : clients.length === 0 ? (
          <p className="text-sm text-muted-foreground">No API clients provisioned yet.</p>
        ) : (
          <div className="divide-y divide-border">
            {clients.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center justify-between gap-3 py-4">
                <div>
                  <p className="font-medium text-foreground">{c.organization_name}</p>
                  <p className="text-xs text-muted-foreground">{c.contact_email}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {c.keys.map((k) => `${k.key_prefix}…`).join(", ") || "no keys"}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <StatusBadge status={c.active ? "active" : "revoked"} />
                  {c.active && (
                    <>
                      <Button variant="outline" size="sm" onClick={() => handleRotateKey(c.id, c.organization_name)}>
                        Rotate Key
                      </Button>
                      <Button variant="outline" size="sm" onClick={() => handleRevoke(c.id)}>
                        Revoke
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Insights Subscribers (M33C — Private Market Data & Insights)
          </p>
          <Button onClick={() => setCreateSubOpen(true)}>New Subscriber Account</Button>
        </div>
        <p className="mb-4 text-sm text-muted-foreground">
          A VC, family office, or issuing company gets a login to the Insights Dashboard — the
          same aggregate data already public at /price-range, /demand-heatmap, /demand-curve,
          and /liquidity-aggregation, packaged into one view.
        </p>
        {createSubSuccess && <p className="text-sm text-emerald-500">{createSubSuccess}</p>}
      </div>

      <Dialog open={createClientOpen} onOpenChange={setCreateClientOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New API Client</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateClient} className="space-y-3">
            <Input placeholder="Organization name" value={orgName} onChange={(e) => setOrgName(e.target.value)} required />
            <Input placeholder="Contact email" type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} required />
            <Input placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
            {createClientError && <p className="text-sm text-destructive">{createClientError}</p>}
            <DialogFooter>
              <Button type="submit">Create</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={createSubOpen} onOpenChange={setCreateSubOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Insights Subscriber Account</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateSubscriber} className="space-y-3">
            <Input placeholder="Contact name" value={subName} onChange={(e) => setSubName(e.target.value)} required />
            <Input placeholder="Email" type="email" value={subEmail} onChange={(e) => setSubEmail(e.target.value)} required />
            <Input placeholder="Temporary password" type="password" value={subPassword} onChange={(e) => setSubPassword(e.target.value)} required />
            <Input placeholder="Organization name" value={subOrg} onChange={(e) => setSubOrg(e.target.value)} required />
            <select
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              value={subType}
              onChange={(e) => setSubType(e.target.value)}
            >
              <option value="vc">VC</option>
              <option value="family_office">Family Office</option>
              <option value="issuer">Issuer</option>
              <option value="other">Other</option>
            </select>
            {createSubError && <p className="text-sm text-destructive">{createSubError}</p>}
            <DialogFooter>
              <Button type="submit">Create</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!revealedKey} onOpenChange={() => setRevealedKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API key for {revealedKey?.organization}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This key is shown once and cannot be retrieved again. Copy it now and share it with
            the integration partner securely.
          </p>
          <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-3 text-xs">{revealedKey?.key}</pre>
          <DialogFooter>
            <Button onClick={() => setRevealedKey(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
