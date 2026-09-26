import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { apiFetch, clearToken, getToken } from "@/lib/auth"

export type CurrentUser = {
  id: number
  name: string
  email: string
  role: string
  kyc_status: string | null
  jurisdiction: string
  account_type: string
}

type AuthState = {
  user: CurrentUser | null
  loading: boolean
  authenticated: boolean
  refresh: () => void
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function load() {
      const token = getToken()
      if (!token) {
        if (!cancelled) {
          setUser(null)
          setLoading(false)
        }
        return
      }

      setLoading(true)
      try {
        const response = await apiFetch("/me")
        if (response.status === 401) {
          clearToken()
          if (!cancelled) {
            setUser(null)
            setLoading(false)
          }
          return
        }
        if (!response.ok) {
          throw new Error("Failed to load profile")
        }
        const data = (await response.json()) as CurrentUser
        if (!cancelled) {
          setUser(data)
          setLoading(false)
        }
      } catch {
        if (!cancelled) {
          setUser(null)
          setLoading(false)
        }
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [version])

  function logout() {
    clearToken()
    setUser(null)
  }

  function refresh() {
    setVersion((v) => v + 1)
  }

  return (
    <AuthContext.Provider
      value={{ user, loading, authenticated: user !== null, refresh, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
