import type { ReactNode } from "react"
import { Sidebar } from "./Sidebar"
import { Topbar } from "./Topbar"
import { useAuth } from "@/contexts/AuthContext"
import { getInitials, capitalize } from "@/lib/format"

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
        role: capitalize(user.role),
        initials: getInitials(user.name),
      }
    : undefined

  return (
    <div className="flex h-screen bg-background">
      <Sidebar user={displayUser} />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar title={title} user={displayUser} />
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  )
}
