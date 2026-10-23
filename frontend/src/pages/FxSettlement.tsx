import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/auth"
import { useAuth } from "@/contexts/AuthContext"

type Transaction = {
  id: number
  listing_id: number
  buyer_id: number
  seller_id: number
  settlement_currency: string
}

export function FxSettlementPage() {
  const { user } = useAuth()
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
        setTransactions((await response.json()) as Transaction[])
      } catch {
        setError("Could not load your transactions.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          How KEVO Handles Cross-Currency Settlement
        </p>
        <p className="text-sm text-muted-foreground">
          Every transaction on KEVO settles in a single, fixed currency (USD) rather than
          attempting any cross-currency conversion itself — the same approach the one real
          comparable precedent in this market (EquityZen) already uses. If you're outside
          the US, any currency conversion you need happens entirely at your own bank,
          outside KEVO. This is a deliberate design choice: KEVO does not quote exchange
          rates, hold foreign currency, or perform any FX conversion.
        </p>
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Your Transactions &amp; Settlement Currency
        </p>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : transactions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No transactions yet.</p>
        ) : (
          <div className="divide-y divide-border">
            <div className="grid grid-cols-3 gap-4 pb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <div>Transaction</div>
              <div>You Are</div>
              <div>Settlement Currency</div>
            </div>
            {transactions.map((t) => (
              <div key={t.id} className="grid grid-cols-3 items-center gap-4 py-3 text-sm">
                <div className="text-foreground">#{t.id}</div>
                <div className="text-muted-foreground">
                  {t.buyer_id === user?.id ? "Buyer" : t.seller_id === user?.id ? "Seller" : "Admin View"}
                </div>
                <div className="font-mono text-foreground">{t.settlement_currency}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
