import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { apiFetch } from "@/lib/auth"
import { formatMoney } from "@/lib/format"

type WalletBalance = {
  kevoUserId: number
  currency: string
  status: string
  available: number
  pending: number
  locked: number
  withdrawalPending: number
  total: number
}

type BankAccount = {
  id: number
  accountHolderName: string
  bankName: string
  lastFour: string
  status: "UNVERIFIED" | "VERIFIED" | "DISABLED"
  createdAt: string
}

function newIdempotencyKey(): string {
  return crypto.randomUUID()
}

function capitalizeStatus(status: string): string {
  return status
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
}

function bankAccountStatusClasses(status: BankAccount["status"]): string {
  if (status === "VERIFIED") return "bg-primary/10 text-primary border-primary/20"
  if (status === "DISABLED") return "bg-muted text-muted-foreground border-border"
  return "bg-[#F5E3BE] text-[#92672A] border-[#92672A]/20"
}

export function WalletPage() {
  const [wallet, setWallet] = useState<WalletBalance | null>(null)
  const [walletLoading, setWalletLoading] = useState(true)
  const [walletError, setWalletError] = useState<string | null>(null)

  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([])
  const [bankAccountsLoading, setBankAccountsLoading] = useState(true)

  const [depositOpen, setDepositOpen] = useState(false)
  const [depositAmount, setDepositAmount] = useState("")
  const [depositKey, setDepositKey] = useState(newIdempotencyKey())
  const [depositSubmitting, setDepositSubmitting] = useState(false)
  const [depositError, setDepositError] = useState<string | null>(null)

  const [withdrawOpen, setWithdrawOpen] = useState(false)
  const [withdrawAmount, setWithdrawAmount] = useState("")
  const [withdrawBankAccountId, setWithdrawBankAccountId] = useState<number | null>(null)
  const [withdrawKey, setWithdrawKey] = useState(newIdempotencyKey())
  const [withdrawSubmitting, setWithdrawSubmitting] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)
  const [withdrawNotice, setWithdrawNotice] = useState<string | null>(null)

  const [addAccountOpen, setAddAccountOpen] = useState(false)
  const [holderName, setHolderName] = useState("")
  const [bankName, setBankName] = useState("")
  const [accountNumber, setAccountNumber] = useState("")
  const [addAccountSubmitting, setAddAccountSubmitting] = useState(false)
  const [addAccountError, setAddAccountError] = useState<string | null>(null)

  const [accountActionId, setAccountActionId] = useState<number | null>(null)

  async function loadWallet() {
    setWalletLoading(true)
    setWalletError(null)
    try {
      const response = await apiFetch("/me/funds")
      if (!response.ok) throw new Error()
      const data = (await response.json()) as WalletBalance
      setWallet(data)
    } catch {
      setWalletError("Could not load your wallet balance.")
    } finally {
      setWalletLoading(false)
    }
  }

  async function loadBankAccounts() {
    setBankAccountsLoading(true)
    try {
      const response = await apiFetch("/me/bank-accounts")
      if (!response.ok) throw new Error()
      const data = (await response.json()) as BankAccount[]
      setBankAccounts(data)
    } catch {
      // silent - the bank accounts section simply stays empty
    } finally {
      setBankAccountsLoading(false)
    }
  }

  useEffect(() => {
    loadWallet()
    loadBankAccounts()
  }, [])

  async function handleDeposit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setDepositError(null)
    const amount = Number(depositAmount)
    if (!amount || amount <= 0) {
      setDepositError("Enter a valid amount.")
      return
    }
    setDepositSubmitting(true)
    try {
      const response = await apiFetch("/me/funds/deposit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount, currency: "USD", idempotency_key: depositKey }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setDepositError(data?.detail ?? "Deposit failed. Please try again.")
        return
      }
      setDepositOpen(false)
      setDepositAmount("")
      setDepositKey(newIdempotencyKey())
      await loadWallet()
    } catch {
      setDepositError("Could not reach the server. Please check your connection.")
    } finally {
      setDepositSubmitting(false)
    }
  }

  async function handleWithdraw(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setWithdrawError(null)
    setWithdrawNotice(null)
    const amount = Number(withdrawAmount)
    if (!amount || amount <= 0) {
      setWithdrawError("Enter a valid amount.")
      return
    }
    if (!withdrawBankAccountId) {
      setWithdrawError("Select a verified bank account.")
      return
    }
    setWithdrawSubmitting(true)
    try {
      const response = await apiFetch("/me/funds/withdraw", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          amount,
          currency: "USD",
          bank_account_id: withdrawBankAccountId,
          idempotency_key: withdrawKey,
        }),
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        setWithdrawError(data?.detail ?? "Withdrawal failed. Please try again.")
        return
      }
      if (data?.status === "CONFIRMATION_REQUIRED") {
        setWithdrawNotice(data.message ?? "Check your email to confirm this withdrawal.")
        setWithdrawKey(newIdempotencyKey())
        return
      }
      setWithdrawOpen(false)
      setWithdrawAmount("")
      setWithdrawKey(newIdempotencyKey())
      await loadWallet()
    } catch {
      setWithdrawError("Could not reach the server. Please check your connection.")
    } finally {
      setWithdrawSubmitting(false)
    }
  }

  async function handleAddAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAddAccountError(null)
    if (!holderName.trim() || !bankName.trim() || !accountNumber.trim()) {
      setAddAccountError("Fill in all fields.")
      return
    }
    setAddAccountSubmitting(true)
    try {
      const response = await apiFetch("/me/bank-accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_holder_name: holderName,
          bank_name: bankName,
          account_number: accountNumber,
        }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setAddAccountError(data?.detail ?? "Could not add this account.")
        return
      }
      setAddAccountOpen(false)
      setHolderName("")
      setBankName("")
      setAccountNumber("")
      await loadBankAccounts()
    } catch {
      setAddAccountError("Could not reach the server. Please check your connection.")
    } finally {
      setAddAccountSubmitting(false)
    }
  }

  async function handleVerify(accountId: number) {
    setAccountActionId(accountId)
    try {
      await apiFetch(`/me/bank-accounts/${accountId}/verify`, { method: "POST" })
      await loadBankAccounts()
    } finally {
      setAccountActionId(null)
    }
  }

  async function handleDisable(accountId: number) {
    setAccountActionId(accountId)
    try {
      await apiFetch(`/me/bank-accounts/${accountId}/disable`, { method: "POST" })
      await loadBankAccounts()
    } finally {
      setAccountActionId(null)
    }
  }

  const verifiedAccounts = bankAccounts.filter((account) => account.status === "VERIFIED")
  const currency = wallet?.currency ?? "USD"

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm lg:col-span-2">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Total Balance
          </p>
          <p className="mt-3 font-heading text-4xl font-semibold text-foreground">
            {walletLoading ? "..." : wallet ? formatMoney(wallet.total, currency) : "-"}
          </p>

          <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div>
              <p className="text-xs text-muted-foreground">Available</p>
              <p className="mt-1 text-sm font-medium text-foreground">
                {wallet ? formatMoney(wallet.available, currency) : "-"}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Pending</p>
              <p className="mt-1 text-sm font-medium text-foreground">
                {wallet ? formatMoney(wallet.pending, currency) : "-"}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Locked</p>
              <p className="mt-1 text-sm font-medium text-foreground">
                {wallet ? formatMoney(wallet.locked, currency) : "-"}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Withdrawal Pending</p>
              <p className="mt-1 text-sm font-medium text-foreground">
                {wallet ? formatMoney(wallet.withdrawalPending, currency) : "-"}
              </p>
            </div>
          </div>

          {walletError && <p className="mt-4 text-sm text-destructive">{walletError}</p>}

          <div className="mt-8 flex gap-3">
            <Button onClick={() => setDepositOpen(true)}>Deposit</Button>
            <Button variant="outline" onClick={() => setWithdrawOpen(true)}>
              Withdraw
            </Button>
          </div>
        </div>

        <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Wallet Status
          </p>
          <p className="mt-3 text-2xl font-semibold text-foreground">
            {wallet ? capitalizeStatus(wallet.status) : "-"}
          </p>
          <p className="mt-2 text-sm text-muted-foreground">
            {wallet?.status === "ACTIVE"
              ? "Your wallet is active and able to send and receive funds."
              : "Your wallet currently has restrictions on it."}
          </p>
        </div>
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Bank Accounts
          </p>
          <Button variant="outline" size="sm" onClick={() => setAddAccountOpen(true)}>
            Add Bank Account
          </Button>
        </div>

        {bankAccountsLoading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : bankAccounts.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No bank accounts on file yet. Add one to enable withdrawals.
          </p>
        ) : (
          <div className="divide-y divide-border">
            {bankAccounts.map((account) => (
              <div key={account.id} className="flex items-center justify-between py-3">
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {account.bankName} •••• {account.lastFour}
                  </p>
                  <p className="text-xs text-muted-foreground">{account.accountHolderName}</p>
                </div>
                <div className="flex items-center gap-3">
                  <Badge variant="outline" className={bankAccountStatusClasses(account.status)}>
                    {capitalizeStatus(account.status)}
                  </Badge>
                  {account.status === "UNVERIFIED" && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={accountActionId === account.id}
                      onClick={() => handleVerify(account.id)}
                    >
                      Verify
                    </Button>
                  )}
                  {account.status !== "DISABLED" && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-muted-foreground"
                      disabled={accountActionId === account.id}
                      onClick={() => handleDisable(account.id)}
                    >
                      Disable
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Dialog open={depositOpen} onOpenChange={setDepositOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deposit funds</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleDeposit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Amount (USD)
              </label>
              <Input
                type="number"
                min="0"
                step="0.01"
                value={depositAmount}
                onChange={(e) => setDepositAmount(e.target.value)}
                required
              />
            </div>
            {depositError && <p className="text-sm text-destructive">{depositError}</p>}
            <DialogFooter>
              <Button type="submit" disabled={depositSubmitting} className="w-full">
                {depositSubmitting ? "Depositing..." : "Deposit"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={withdrawOpen}
        onOpenChange={(open) => {
          setWithdrawOpen(open)
          if (!open) setWithdrawNotice(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Withdraw funds</DialogTitle>
          </DialogHeader>
          {withdrawNotice ? (
            <p className="text-sm text-foreground">{withdrawNotice}</p>
          ) : (
            <form onSubmit={handleWithdraw} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Amount (USD)
                </label>
                <Input
                  type="number"
                  min="0"
                  step="0.01"
                  value={withdrawAmount}
                  onChange={(e) => setWithdrawAmount(e.target.value)}
                  required
                />
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Bank Account
                </label>
                {verifiedAccounts.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    You need a verified bank account before you can withdraw.
                  </p>
                ) : (
                  <select
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                    value={withdrawBankAccountId ?? ""}
                    onChange={(e) => setWithdrawBankAccountId(Number(e.target.value))}
                    required
                  >
                    <option value="" disabled>
                      Select an account
                    </option>
                    {verifiedAccounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.bankName} •••• {account.lastFour}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              {withdrawError && <p className="text-sm text-destructive">{withdrawError}</p>}

              <DialogFooter>
                <Button
                  type="submit"
                  disabled={withdrawSubmitting || verifiedAccounts.length === 0}
                  className="w-full"
                >
                  {withdrawSubmitting ? "Submitting..." : "Withdraw"}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={addAccountOpen} onOpenChange={setAddAccountOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add bank account</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleAddAccount} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Account Holder Name
              </label>
              <Input value={holderName} onChange={(e) => setHolderName(e.target.value)} required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Bank Name
              </label>
              <Input value={bankName} onChange={(e) => setBankName(e.target.value)} required />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Account Number
              </label>
              <Input
                value={accountNumber}
                onChange={(e) => setAccountNumber(e.target.value)}
                required
              />
            </div>
            {addAccountError && <p className="text-sm text-destructive">{addAccountError}</p>}
            <DialogFooter>
              <Button type="submit" disabled={addAccountSubmitting} className="w-full">
                {addAccountSubmitting ? "Adding..." : "Add Account"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
