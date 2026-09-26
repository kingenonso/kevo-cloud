import { useAuth } from "@/contexts/AuthContext"
import { capitalize } from "@/lib/format"

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

export function DashboardPage() {
  const { user } = useAuth()

  if (!user) {
    return null
  }

  const fields: { label: string; value: string }[] = [
    { label: "Name", value: user.name },
    { label: "Email", value: user.email },
    { label: "Role", value: capitalize(user.role) },
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
