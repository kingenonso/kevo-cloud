// Fix for a packaging gap found while verifying the build (2026-10-23):
// lucide-react@1.48.0's published npm tarball is missing the
// dist/lucide-react.d.ts file its own package.json points "typings" at
// (node_modules/lucide-react/dist/ only has cjs/ and esm/ JS, no .d.ts
// anywhere), so `tsc -b` fails on every file importing from it with
// TS7016/TS2709. Flagged to Eze separately since it will also break a
// from-scratch `npm install` on any other machine/CI pinned to this
// exact version until lucide-react re-publishes the missing file or the
// dependency is bumped/pinned differently.
//
// Rather than the blanket `declare module "lucide-react"` TS itself
// suggests (which breaks `type LucideIcon` imports - it stops being a
// usable type), this lists every icon actually imported anywhere in the
// app, typed the same way lucide-react's own .d.ts would type them, so
// nothing loses type-checking. Add a new icon's name here the first time
// it's imported.
declare module "lucide-react" {
  import type { ComponentType, SVGProps } from "react"

  export type LucideProps = SVGProps<SVGSVGElement> & {
    size?: string | number
    strokeWidth?: string | number
    absoluteStrokeWidth?: boolean
  }

  export type LucideIcon = ComponentType<LucideProps>

  export const ChevronRight: LucideIcon
  export const ChevronRightIcon: LucideIcon
  export const CheckIcon: LucideIcon
  export const XIcon: LucideIcon
  export const Bell: LucideIcon
  export const Search: LucideIcon
  export const LayoutDashboard: LucideIcon
  export const Wallet: LucideIcon
  export const Building2: LucideIcon
  export const ArrowLeftRight: LucideIcon
  export const Handshake: LucideIcon
  export const TrendingUp: LucideIcon
  export const ShieldCheck: LucideIcon
  export const Zap: LucideIcon
  export const Settings: LucideIcon
  export const Store: LucideIcon
  export const FileText: LucideIcon
  export const Calculator: LucideIcon
  export const Users: LucideIcon
  export const FileSignature: LucideIcon
  export const Landmark: LucideIcon
  export const BarChart3: LucideIcon
  export const Gauge: LucideIcon
  export const Radar: LucideIcon
  export const BellRing: LucideIcon
  export const CircleDollarSign: LucideIcon
  export const PlusCircle: LucideIcon
  export const Loader2: LucideIcon
  export const KeyRound: LucideIcon
}
