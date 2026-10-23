import { useEffect, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { apiFetch, clearToken } from "@/lib/auth"
import { useAuth } from "@/contexts/AuthContext"
import { useNavigate } from "react-router-dom"

type BankAccount = Record<string, unknown>

export function SettingsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordSubmitting, setPasswordSubmitting] = useState(false)

  const [bankAccounts, setBankAccounts] = useState<BankAccount[]>([])
  const [bankLoading, setBankLoading] = useState(true)
  const [bankError, setBankError] = useState<string | null>(null)

  const [addOpen, setAddOpen] = useState(false)
  const [holderName, setHolderName] = useState("")
  const [bankName, setBankName] = useState("")
  const [accountNumber, setAccountNumber] = useState("")
  const [addError, setAddError] = useState<string | null>(null)
  const [addSubmitting, setAddSubmitting] = useState(false)

  const [revokeMessage, setRevokeMessage] = useState<string | null>(null)

  async function loadBankAccounts() {
    setBankLoading(true)
    setBankError(null)
    try {
      const response = await apiFetch("/me/bank-accounts")
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setBankError(data?.detail ?? "Could not load bank accounts.")
        return
      }
      setBankAccounts((await response.json()) as BankAccount[])
    } catch {
      setBankError("Could not reach the server.")
    } finally {
      setBankLoading(false)
    }
  }

  useEffect(() => {
    loadBankAccounts()
  }, [])

  async function handleChangePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPasswordError(null)
    setPasswordMessage(null)
    setPasswordSubmitting(true)
    try {
      const response = await apiFetch("/change-password", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setPasswordError(data?.detail ?? "Could not change your password.")
        return
      }
      setPasswordMessage("Password changed successfully.")
      setCurrentPassword("")
      setNewPassword("")
    } catch {
      setPasswordError("Could not reach the server.")
    } finally {
      setPasswordSubmitting(false)
    }
  }

  async function handleAddBankAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAddError(null)
    if (!holderName.trim() || !bankName.trim() || !accountNumber.trim()) {
      setAddError("Fill in all fields.")
      return
    }
    setAddSubmitting(true)
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
        setAddError(data?.detail ?? "Could not add this bank account.")
        return
      }
      setAddOpen(false)
      setHolderName("")
      setBankName("")
      setAccountNumber("")
      await loadBankAccounts()
    } catch {
      setAddError("Could not reach the server.")
    } finally {
      setAddSubmitting(false)
    }
  }

  async function verifyAccount(id: unknown) {
    const response = await apiFetch(`/me/bank-accounts/${id}/verify`, { method: "POST" })
    if (response.ok) await loadBankAccounts()
  }

  async function disableAccount(id: unknown) {
    const response = await apiFetch(`/me/bank-accounts/${id}/disable`, { method: "POST" })
    if (response.ok) await loadBankAccounts()
  }

  async function handleRevokeTokens() {
    setRevokeMessage(null)
    const response = await apiFetch("/users/me/revoke-tokens", { method: "POST" })
    if (response.ok) {
      clearToken()
      navigate("/login")
    } else {
      setRevokeMessage("Could not revoke tokens.")
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Account
        </p>
        <dl className="divide-y divide-border">
          <div className="flex items-center justify-between py-3">
            <dt className="text-sm text-muted-foreground">Name</dt>
            <dd className="text-sm font-medium text-foreground">{user?.name}</dd>
          </div>
          <div className="flex items-center justify-between py-3">
            <dt className="text-sm text-muted-foreground">Email</dt>
            <dd className="text-sm font-medium text-foreground">{user?.email}</dd>
          </div>
        </dl>
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Change Password
        </p>
        <form onSubmit={handleChangePassword} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Current Password
            </label>
            <Input type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground">
              New Password
            </label>
            <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
          </div>
          {passwordError && <p className="text-sm text-destructive">{passwordError}</p>}
          {passwordMessage && <p className="text-sm text-primary">{passwordMessage}</p>}
          <Button type="submit" disabled={passwordSubmitting}>
            {passwordSubmitting ? "Changing..." : "Change Password"}
          </Button>
        </form>
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-6 flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Bank Accounts
          </p>
          <Button size="sm" onClick={() => setAddOpen(!addOpen)}>
            {addOpen ? "Cancel" : "Add Bank Account"}
          </Button>
        </div>

        {addOpen && (
          <form onSubmit={handleAddBankAccount} className="mb-6 space-y-4 rounded-xl border border-border p-4">
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
              <Input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} required />
            </div>
            {addError && <p className="text-sm text-destructive">{addError}</p>}
            <Button type="submit" disabled={addSubmitting} className="w-full">
              {addSubmitting ? "Adding..." : "Add Account"}
            </Button>
          </form>
        )}

        {bankLoading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : bankError ? (
          <p className="text-sm text-destructive">{bankError}</p>
        ) : bankAccounts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No bank accounts on file yet.</p>
        ) : (
          <div className="space-y-3">
            {bankAccounts.map((acct, i) => {
              const id = (acct as { id?: unknown }).id ?? i
              const status = (acct as { status?: unknown }).status
              return (
                <div key={String(id)} className="rounded-xl border border-border p-4 text-sm">
                  <div className="mb-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {Object.entries(acct).map(([key, value]) => (
                      <div key={key}>
                        <p className="text-xs text-muted-foreground">{key}</p>
                        <p className="font-mono text-foreground">{String(value)}</p>
                      </div>
                    ))}
                  </div>
                  <div className="flex gap-2">
                    {status !== "VERIFIED" && (
                      <Button size="sm" variant="outline" onClick={() => verifyAccount(id)}>
                        Verify
                      </Button>
                    )}
                    {status !== "DISABLED" && (
                      <Button size="sm" variant="outline" onClick={() => disableAccount(id)}>
                        Disable
                      </Button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-4 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Security
        </p>
        <p className="mb-4 text-sm text-muted-foreground">
          Revoke every session token issued before now, on every device, including this one.
          You'll need to log in again afterward.
        </p>
        {revokeMessage && <p className="mb-2 text-sm text-destructive">{revokeMessage}</p>}
        <Button variant="outline" onClick={handleRevokeTokens}>
          Log Out Everywhere
        </Button>
      </div>
    </div>
  )
}
