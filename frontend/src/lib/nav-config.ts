import {
  LayoutDashboard,
  Wallet,
  Building2,
  ArrowLeftRight,
  Handshake,
  TrendingUp,
  ShieldCheck,
  Zap,
  Settings,
  Store,
  Landmark,
  KeyRound,
  type LucideIcon,
} from "lucide-react"

export type NavLink = {
  type: "link"
  label: string
  href: string
  icon: LucideIcon
}

export type NavGroup = {
  type: "group"
  key: string
  label: string
  icon: LucideIcon
  items: { label: string; href: string }[]
}

export type NavEntry = NavLink | NavGroup

export const pinnedTopNav: NavLink[] = [
  { type: "link", label: "Dashboard", href: "/", icon: LayoutDashboard },
  { type: "link", label: "Wallet", href: "/wallet", icon: Wallet },
  { type: "link", label: "My Listings", href: "/listings", icon: Building2 },
  { type: "link", label: "Transactions", href: "/transactions", icon: ArrowLeftRight },
  { type: "link", label: "Deal Room", href: "/deal-room", icon: Handshake },
]

export const groupedNav: NavGroup[] = [
  {
    type: "group",
    key: "marketplace",
    label: "Marketplace",
    icon: Store,
    items: [
      { label: "Browse", href: "/browse" },
      { label: "Evidence", href: "/evidence" },
      { label: "Cost Calculator", href: "/cost-calculator" },
    ],
  },
  {
    type: "group",
    key: "capitalMarkets",
    label: "Capital Markets",
    icon: TrendingUp,
    items: [
      { label: "Lending", href: "/lending" },
      { label: "FX Settlement", href: "/fx-settlement" },
      { label: "Option Funding", href: "/option-funding" },
      { label: "Tender Offers", href: "/tender-offers" },
      { label: "SPV Pools", href: "/spv-pools" },
      { label: "Forward Sale Contracts", href: "/forward-sale-contracts" },
      { label: "Seller Financing", href: "/seller-financing" },
    ],
  },
  {
    type: "group",
    key: "compliance",
    label: "Compliance",
    icon: ShieldCheck,
    items: [
      { label: "Compliance Ledger", href: "/compliance-ledger" },
      { label: "KYC & AML", href: "/kyc" },
      { label: "ROFR", href: "/rofr" },
      { label: "Eligibility", href: "/eligibility" },
      { label: "Withdrawal Review", href: "/admin/withdrawal-review" },
    ],
  },
  {
    type: "group",
    key: "issuer",
    label: "Issuer",
    icon: Landmark,
    items: [
      { label: "Issuer Portal", href: "/issuer-portal" },
    ],
  },
  {
    type: "group",
    key: "insights",
    label: "Insights",
    icon: Zap,
    items: [
      { label: "Deal Alerts", href: "/deal-alerts" },
      { label: "Rule-Change Alerts", href: "/rule-change-alerts" },
      { label: "Risk Radar", href: "/risk-radar" },
      { label: "Liquidity Roadmap", href: "/liquidity-roadmap" },
      { label: "Market Intelligence", href: "/market-intelligence" },
      { label: "Liquidity Event Radar", href: "/liquidity-event-radar" },
      { label: "Speed Discount", href: "/speed-discount" },
      { label: "Insights Dashboard", href: "/insights-dashboard" },
    ],
  },
  {
    type: "group",
    key: "platform",
    label: "Platform",
    icon: KeyRound,
    items: [
      { label: "API & Insights Access", href: "/admin/platform-access" },
      { label: "Audit Log", href: "/admin/audit-log" },
    ],
  },
]

export const pinnedBottomNav: NavLink[] = [
  { type: "link", label: "Settings", href: "/settings", icon: Settings },
]
