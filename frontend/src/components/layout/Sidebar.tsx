import { useState } from "react"
import { NavLink as RouterNavLink } from "react-router-dom"
import { ChevronRight, type LucideIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  pinnedTopNav,
  groupedNav,
  pinnedBottomNav,
  type NavGroup,
} from "@/lib/nav-config"

type SidebarUser = {
  name: string
  role: string
  initials: string
}

const DEFAULT_USER: SidebarUser = {
  name: "Eze N.",
  role: "Admin",
  initials: "EN",
}

function SidebarLink({
  href,
  label,
  icon: Icon,
}: {
  href: string
  label: string
  icon: LucideIcon
}) {
  return (
    <RouterNavLink
      to={href}
      end={href === "/"}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
          isActive
            ? "bg-sidebar-accent text-sidebar-accent-foreground"
            : "text-sidebar-foreground/70 hover:bg-white/5 hover:text-sidebar-foreground"
        )
      }
    >
      <Icon className="h-[18px] w-[18px] shrink-0" />
      <span>{label}</span>
    </RouterNavLink>
  )
}

function SidebarGroup({ group }: { group: NavGroup }) {
  const [open, setOpen] = useState(group.key === "capitalMarkets")
  const Icon = group.icon

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-sidebar-foreground/70 transition-colors hover:bg-white/5 hover:text-sidebar-foreground"
        aria-expanded={open}
      >
        <Icon className="h-[18px] w-[18px] shrink-0" />
        <span className="flex-1 text-left">{group.label}</span>
        <ChevronRight
          className={cn(
            "h-4 w-4 shrink-0 transition-transform",
            open && "rotate-90"
          )}
        />
      </button>
      {open && (
        <div className="ml-[21px] mt-1 flex flex-col gap-0.5 border-l border-sidebar-border pl-4">
          {group.items.map((item) => (
            <RouterNavLink
              key={item.href}
              to={item.href}
              className={({ isActive }) =>
                cn(
                  "rounded-lg px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/60 hover:bg-white/5 hover:text-sidebar-foreground"
                )
              }
            >
              {item.label}
            </RouterNavLink>
          ))}
        </div>
      )}
    </div>
  )
}

export function Sidebar({ user = DEFAULT_USER }: { user?: SidebarUser }) {
  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col bg-sidebar px-4 py-6 text-sidebar-foreground">
      <div className="px-2 pb-8">
        <span className="font-heading text-2xl font-semibold tracking-tight">
          KEVO
        </span>
        <p className="mt-0.5 text-[11px] font-medium uppercase tracking-[0.14em] text-sidebar-foreground/40">
          Private Markets
        </p>
      </div>

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto">
        {pinnedTopNav.map((item) => (
          <SidebarLink key={item.href} href={item.href} label={item.label} icon={item.icon} />
        ))}

        <div className="my-3 border-t border-sidebar-border" />

        <div className="flex flex-col gap-1">
          {groupedNav.map((group) => (
            <SidebarGroup key={group.key} group={group} />
          ))}
        </div>

        <div className="my-3 border-t border-sidebar-border" />

        {pinnedBottomNav.map((item) => (
          <SidebarLink key={item.href} href={item.href} label={item.label} icon={item.icon} />
        ))}
      </nav>

      <div className="mt-4 flex items-center gap-3 rounded-xl bg-white/5 px-3 py-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-sm font-semibold text-sidebar-accent-foreground">
          {user.initials}
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-sidebar-foreground">
            {user.name}
          </p>
          <p className="truncate text-xs text-sidebar-foreground/50">
            {user.role}
          </p>
        </div>
      </div>
    </aside>
  )
}
