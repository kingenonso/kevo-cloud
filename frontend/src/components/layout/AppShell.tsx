import type { ReactNode } from "react"
import { Sidebar } from "./Sidebar"
import { Topbar } from "./Topbar"
import { useAuth } from "@/contexts/AuthContext"
import { getInitials } from "@/lib/format"

export function AppShell({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  const { user } = useAuth()

  const displayUser = user
    ? {
        name: user.name,
        initials: getInitials(user.name),
      }
    : undefined

  return (
    <div className="relative flex h-screen bg-background">
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-50 h-[2px]"
        style={{
          background:
            "linear-gradient(90deg, transparent 0%, var(--primary) 50%, transparent 100%)",
        }}
      />
      <Sidebar user={displayUser} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar title={title} user={displayUser} />
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  )
}
