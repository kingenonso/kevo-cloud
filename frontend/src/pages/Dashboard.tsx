import { useState } from "react"
import { useAuth } from "@/contexts/AuthContext"
import { apiFetch } from "@/lib/auth"
import { capitalize, formatRoles } from "@/lib/format"

const KYC_STYLES: Record<string, string> = {
  verified: "bg-primary/10 text-primary border-primary/20",
  pending: "bg-[#F5E3BE] text-[#92672A] border-[#92672A]/20",
  rejected: "bg-destructive/10 text-destructive border-destructive/20",
}

function kycBadgeClasses(status: string | null): string {
  if (!status) {
    return "bg-muted text-muted-foreground border-border"
  }
  return KYC_STYLES[status] ?? "bg-muted text-muted-foreground border-border"
}

function kycLabel(status: string | null): string {
  if (!status) return "Not Started"
  return status
    .split("_")
    .map((word) => capitalize(word))
    .join(" ")
}

const ALL_ROLES = ["seller", "buyer"] as const

export function DashboardPage() {
  const { user, refresh } = useAuth()
  const [switchingRole, setSwitchingRole] = useState<string | null>(null)
  const [switchError, setSwitchError] = useState<string | null>(null)

  if (!user) {
    return null
  }

  const missingRoles = ALL_ROLES.filter((role) => !user.roles.includes(role))
  const isVerified = user.kyc_status === "verified"

  async function handleAddRole(role: string) {
    setSwitchError(null)
    setSwitchingRole(role)
    try {
      const response = await apiFetch("/me/roles/switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setSwitchError(data?.detail ?? "Could not switch roles. Please try again.")
        return
      }
      refresh()
    } catch {
      setSwitchError("Could not reach the server. Please check your connection.")
    } finally {
      setSwitchingRole(null)
    }
  }

  const fields: { label: string; value: string }[] = [
    { label: "Name", value: user.name },
    { label: "Email", value: user.email },
    { label: "Account Type", value: capitalize(user.account_type) },
    { label: "Jurisdiction", value: user.jurisdiction },
  ]

  return (
    <div className="mx-auto max-w-xl">
      <div className="rounded-3xl border border-border bg-card p-8 shadow-sm">
        <p className="mb-6 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
          Profile
        </p>

        <dl className="divide-y divide-border">
          <div className="py-3">
            <div className="flex items-center justify-between">
              <dt className="text-sm text-muted-foreground">Role</dt>
              <dd className="text-sm font-medium text-foreground">{formatRoles(user.roles)}</dd>
            </div>

            {missingRoles.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {missingRoles.map((role) => (
                  <button
                    key={role}
                    type="button"
                    disabled={!isVerified || switchingRole === role}
                    onClick={() => handleAddRole(role)}
                    className="rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {switchingRole === role ? "Adding..." : `Also become a ${capitalize(role)}`}
                  </button>
                ))}
              </div>
            )}

            {!isVerified && missingRoles.length > 0 && (
              <p className="mt-2 text-xs text-muted-foreground">
                Complete KYC verification to switch or add roles.
              </p>
            )}

            {switchError && <p className="mt-2 text-xs text-destructive">{switchError}</p>}
          </div>

          {fields.map((field) => (
            <div key={field.label} className="flex items-center justify-between py-3">
              <dt className="text-sm text-muted-foreground">{field.label}</dt>
              <dd className="text-sm font-medium text-foreground">{field.value}</dd>
            </div>
          ))}

          <div className="flex items-center justify-between py-3">
            <dt className="text-sm text-muted-foreground">KYC Status</dt>
            <dd>
              <span
                className={`rounded-full border px-3 py-1 text-xs font-medium ${kycBadgeClasses(user.kyc_status)}`}
              >
                {kycLabel(user.kyc_status)}
              </span>
            </dd>
          </div>
        </dl>
      </div>

      <p className="mt-4 text-sm text-muted-foreground">
        This is KEVO's web app, showing your real account data pulled live from the API. More of
        the platform surfaces here as pages are rebuilt in the new interface.
      </p>
    </div>
  )
}
