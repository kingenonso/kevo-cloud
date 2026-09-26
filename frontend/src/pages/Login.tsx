import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { setToken } from "@/lib/auth"
import { useAuth } from "@/contexts/AuthContext"

export function LoginPage() {
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setLoading(true)

    try {
      const response = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      })

      if (response.ok) {
        const data = await response.json()
        setToken(data.access_token)
        refresh()
        navigate("/")
        return
      }

      if (response.status === 401) {
        setError("Incorrect email or password.")
      } else if (response.status === 423) {
        setError("Account temporarily locked due to repeated failed attempts. Try again later.")
      } else if (response.status === 429) {
        setError("Too many attempts. Please wait a moment and try again.")
      } else {
        setError("Something went wrong. Please try again.")
      }
    } catch {
      setError("Could not reach the server. Please check your connection.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-3xl border border-border bg-card p-8 shadow-sm">
        <div className="mb-8">
          <span className="font-heading text-2xl font-semibold tracking-tight text-foreground">
            KEVO
          </span>
          <p className="mt-1 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
            Private Markets
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="email"
              className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground"
            >
              Email
            </label>
            <Input
              id="email"
              name="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-muted-foreground"
            >
              Password
            </label>
            <Input
              id="password"
              name="password"
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          {error && (
            <div className="rounded-xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          <Button type="submit" disabled={loading} className="w-full">
            {loading ? "Logging in…" : "Log In"}
          </Button>
        </form>

        <div className="mt-6 space-y-2 text-center">
          <a href="/app/signup.html" className="block text-xs text-muted-foreground transition-colors hover:text-foreground">Don't have an account? Sign up</a>
          <a href="/app/forgot-password.html" className="block text-xs text-muted-foreground transition-colors hover:text-foreground">Forgot password?</a>
        </div>
      </div>
    </div>
  )
}
