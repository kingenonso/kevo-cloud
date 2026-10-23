import { Badge } from "@/components/ui/badge"
import { formatLabel, statusBadgeClasses } from "@/lib/status"

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={statusBadgeClasses(status)}>
      {formatLabel(status)}
    </Badge>
  )
}
