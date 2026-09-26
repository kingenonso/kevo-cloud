import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { apiFetch } from "@/lib/auth"
import { useAuth } from "@/contexts/AuthContext"
import { formatMoney } from "@/lib/format"

type Transaction = {
  id: number
  listing_id: number
  buyer_id: number
  seller_id: number
  quantity: number
  agreed_price: number
  status: string
  settlement_currency: string
}

function roleLabel(transaction: Transaction, myId: number | undefined): string {
  if (transaction.buyer_id === myId) return "Buyer"
  if (transaction.seller_id === myId) return "Seller"
  return "Admin View"
}

export function TransactionsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const response = await apiFetch("/transactions")
        if (!response.ok) throw new Error()
        const data = (await response.json()) as Transaction[]
        setTransactions(data)
      } catch {
        setError("Could not load your transactions.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
      <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
        Your Transactions
      </p>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : transactions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No transactions yet.</p>
      ) : (
        <div className="divide-y divide-border">
          <div className="grid grid-cols-6 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <div>ID</div>
            <div>Listing</div>
            <div>You Are</div>
            <div>Quantity</div>
            <div>Price</div>
            <div>Status</div>
          </div>
          {transactions.map((transaction) => (
            <button
              key={transaction.id}
              type="button"
              onClick={() => navigate(`/deal-room/${transaction.id}`)}
              className="grid w-full grid-cols-6 gap-4 py-3 text-left text-sm transition-colors hover:bg-secondary"
            >
              <div className="text-foreground">{transaction.id}</div>
              <div className="text-muted-foreground">{transaction.listing_id}</div>
              <div className="text-foreground">{roleLabel(transaction, user?.id)}</div>
              <div className="text-muted-foreground">{transaction.quantity}</div>
              <div className="text-foreground">
                {formatMoney(transaction.agreed_price, transaction.settlement_currency)}
              </div>
              <div className="text-muted-foreground">{transaction.status}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
