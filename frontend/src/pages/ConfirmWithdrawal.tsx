import { useEffect, useState } from "react"
import { useSearchParams, Link } from "react-router-dom"
import { apiFetch } from "@/lib/auth"

export function ConfirmWithdrawalPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get("token")
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading")
  const [message, setMessage] = useState("")

  useEffect(() => {
    if (!token) {
      setStatus("error")
      setMessage("This confirmation link is missing its token.")
      return
    }

    async function confirm() {
      try {
        const response = await apiFetch("/me/funds/withdraw/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        })
        const data = await response.json().catch(() => null)
        if (!response.ok) {
          setStatus("error")
          setMessage(data?.detail ?? "This confirmation link is invalid or has expired.")
          return
        }
        setStatus("success")
        setMessage("Your withdrawal has been confirmed and processed.")
      } catch {
        setStatus("error")
        setMessage("Could not reach the server. Please check your connection.")
      }
    }

    confirm()
  }, [token])

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-3xl border border-border bg-card p-8 text-center shadow-sm">
        <span className="font-heading text-2xl font-semibold tracking-tight text-foreground">
          KEVO
        </span>
        <p className="mt-6 text-sm text-foreground">
          {status === "loading" ? "Confirming your withdrawal..." : message}
        </p>
        {status !== "loading" && (
          <Link
            to="/wallet"
            className="mt-6 inline-block text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Back to Wallet
          </Link>
        )}
      </div>
    </div>
  )
}
