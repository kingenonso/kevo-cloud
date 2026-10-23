import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { apiFetch } from "@/lib/auth"

type Transaction = {
  id: number
  status: string
}

export function DealRoomIndexPage() {
  const navigate = useNavigate()
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const response = await apiFetch("/transactions")
        if (response.ok) setTransactions((await response.json()) as Transaction[])
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
      <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
        Deal Room
      </p>
      <p className="mb-6 text-sm text-muted-foreground">
        The Deal Room is scoped to a specific transaction. Pick one below, or open it from
        your Transactions list.
      </p>
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : transactions.length === 0 ? (
        <p className="text-sm text-muted-foreground">You have no transactions yet.</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {transactions.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => navigate(`/deal-room/${t.id}`)}
              className="rounded-full border border-border px-4 py-2 text-sm text-foreground hover:bg-secondary"
            >
              Transaction #{t.id} ({t.status})
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
