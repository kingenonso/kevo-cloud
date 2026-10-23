import { useEffect, useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch, getToken } from "@/lib/auth"
import { apiFetchQuery } from "@/lib/api"
import { useAuth } from "@/contexts/AuthContext"
import { StatusBadge } from "@/components/shared/StatusBadge"
import { formatLabel } from "@/lib/status"

type EvidenceRecord = {
  id: number
  user_id: number
  listing_id: number | null
  transaction_id: number | null
  ownership_record_id: number | null
  evidence_type: string
  description: string
  file_reference: string | null
  file_hash: string | null
  verification_status: string
  source_reference: string | null
}

export function EvidencePage() {
  const { user } = useAuth()
  const isAdmin = user?.account_type === "admin"

  const [records, setRecords] = useState<EvidenceRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const [evidenceType, setEvidenceType] = useState("")
  const [description, setDescription] = useState("")
  const [listingId, setListingId] = useState("")
  const [transactionId, setTransactionId] = useState("")
  const [ownershipRecordId, setOwnershipRecordId] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const fileInputs = useRef<Record<number, HTMLInputElement | null>>({})

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await apiFetch("/evidence")
      if (!response.ok) throw new Error()
      setRecords((await response.json()) as EvidenceRecord[])
    } catch {
      setError("Could not load evidence records.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitError(null)
    if (!user || !evidenceType.trim() || !description.trim()) {
      setSubmitError("Fill in all required fields.")
      return
    }
    setSubmitting(true)
    try {
      const response = await apiFetch("/evidence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.id,
          evidence_type: evidenceType,
          description,
          listing_id: listingId ? Number(listingId) : null,
          transaction_id: transactionId ? Number(transactionId) : null,
          ownership_record_id: ownershipRecordId ? Number(ownershipRecordId) : null,
        }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setSubmitError(data?.detail ?? "Could not create this evidence record.")
        return
      }
      setEvidenceType("")
      setDescription("")
      setListingId("")
      setTransactionId("")
      setOwnershipRecordId("")
      await load()
    } catch {
      setSubmitError("Could not reach the server.")
    } finally {
      setSubmitting(false)
    }
  }

  async function verify(id: number, status: "verified" | "rejected") {
    setActionError(null)
    const response = await apiFetchQuery(`/evidence/${id}/verify`, "PUT", { status })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not update verification status.")
      return
    }
    await load()
  }

  async function uploadFile(id: number) {
    const input = fileInputs.current[id]
    const file = input?.files?.[0]
    if (!file) return
    setActionError(null)
    const formData = new FormData()
    formData.append("file", file)
    const token = getToken()
    const response = await fetch(`/evidence/${id}/upload-file`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: formData,
    })
    if (!response.ok) {
      const data = await response.json().catch(() => null)
      setActionError(data?.detail ?? "Could not upload this file.")
      return
    }
    if (input) input.value = ""
    await load()
  }

  function downloadFile(id: number) {
    window.open(`/evidence/${id}/file`, "_blank")
  }

  return (
    <div className="space-y-6">
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          {isAdmin ? "All Evidence Records" : "Your Evidence Records"}
        </p>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : records.length === 0 ? (
          <p className="text-sm text-muted-foreground">No evidence records yet.</p>
        ) : (
          <div className="space-y-3">
            {records.map((r) => (
              <div key={r.id} className="rounded-xl border border-border p-4 text-sm">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-medium text-foreground">{formatLabel(r.evidence_type)}</p>
                    <p className="text-xs text-muted-foreground">{r.description}</p>
                  </div>
                  <StatusBadge status={r.verification_status} />
                </div>
                <div className="mb-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
                  {r.listing_id && <span>Listing #{r.listing_id}</span>}
                  {r.transaction_id && <span>Transaction #{r.transaction_id}</span>}
                  {r.ownership_record_id && <span>Ownership #{r.ownership_record_id}</span>}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {r.file_reference ? (
                    <Button size="sm" variant="outline" onClick={() => downloadFile(r.id)}>
                      Download File
                    </Button>
                  ) : (
                    r.verification_status !== "verified" && (
                      <>
                        <input
                          type="file"
                          ref={(el) => {
                            fileInputs.current[r.id] = el
                          }}
                          className="text-xs"
                        />
                        <Button size="sm" variant="outline" onClick={() => uploadFile(r.id)}>
                          Upload
                        </Button>
                      </>
                    )
                  )}
                  {isAdmin && r.verification_status === "pending" && (
                    <>
                      <Button size="sm" variant="outline" onClick={() => verify(r.id, "verified")}>
                        Verify
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => verify(r.id, "rejected")}>
                        Reject
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
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Submit New Evidence
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Evidence Type
              </label>
              <Input value={evidenceType} onChange={(e) => setEvidenceType(e.target.value)} placeholder="e.g. proof_of_ownership" required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Description
              </label>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} required />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Listing ID (optional)
              </label>
              <Input type="number" value={listingId} onChange={(e) => setListingId(e.target.value)} />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Transaction ID (optional)
              </label>
              <Input type="number" value={transactionId} onChange={(e) => setTransactionId(e.target.value)} />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Ownership Record ID (optional)
              </label>
              <Input type="number" value={ownershipRecordId} onChange={(e) => setOwnershipRecordId(e.target.value)} />
            </div>
          </div>
          {submitError && <p className="text-sm text-destructive">{submitError}</p>}
          <Button type="submit" disabled={submitting}>
            {submitting ? "Submitting..." : "Submit"}
          </Button>
        </form>
      </div>
    </div>
  )
}
