// Shared status-badge styling + label formatting, extracted from the
// per-page helpers first written in DealRoom.tsx/Transactions.tsx so new
// pages (Task #9 gap-closure build-out) don't re-duplicate them.

const STATUS_GREEN = new Set([
  "verified", "eligible", "clear", "known_complete", "active", "accepted",
  "approved", "completed", "closed", "settled", "matched", "funded",
  "transferable", "reviewed_ok", "resolved", "read", "open", "released",
])

const STATUS_RED = new Set([
  "blocked", "flagged", "known_incomplete", "rejected", "declined",
  "cancelled", "canceled", "defaulted", "withdrawn", "reviewed_flagged",
  "overdue", "expired", "retracted",
])

const STATUS_AMBER = new Set([
  "review", "pending", "required_but_unverified", "forming", "proposed",
  "requested", "not_reviewed", "pledged", "unread",
])

export function statusBadgeClasses(status: string): string {
  const s = status.toLowerCase()
  if (STATUS_GREEN.has(s)) return "bg-primary/10 text-primary border-primary/20"
  if (STATUS_RED.has(s)) return "bg-destructive/10 text-destructive border-destructive/20"
  if (STATUS_AMBER.has(s)) return "bg-[#F5E3BE] text-[#92672A] border-[#92672A]/20"
  return "bg-muted text-muted-foreground border-border"
}

export function formatLabel(value: string | null | undefined): string {
  if (!value) return "-"
  return value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
}
