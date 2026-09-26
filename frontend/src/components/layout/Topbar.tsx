import { Bell, Search } from "lucide-react"
import { useNavigate } from "react-router-dom"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useAuth } from "@/contexts/AuthContext"

type TopbarUser = {
  name: string
  role: string
  initials: string
}

const DEFAULT_USER: TopbarUser = {
  name: "Eze N.",
  role: "Admin",
  initials: "EN",
}

export function Topbar({
  title,
  user = DEFAULT_USER,
}: {
  title: string
  user?: TopbarUser
}) {
  const navigate = useNavigate()
  const { logout } = useAuth()

  function handleLogout() {
    logout()
    navigate("/login")
  }

  return (
    <header className="flex h-20 shrink-0 items-center justify-between border-b border-border bg-background px-8">
      <h1 className="font-heading text-2xl font-semibold text-foreground">
        {title}
      </h1>

      <div className="flex items-center gap-4">
        <button
          type="button"
          className="flex w-60 items-center gap-2 rounded-full border border-border bg-secondary px-4 py-2 text-sm text-muted-foreground transition-colors hover:border-primary/30"
        >
          <Search className="h-4 w-4 shrink-0" />
          <span className="flex-1 text-left">Jump to anything</span>
          <span className="rounded-md border border-border bg-background px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
            ⌘K
          </span>
        </button>

        <button
          type="button"
          aria-label="Notifications"
          className="relative flex h-10 w-10 items-center justify-center rounded-full border border-border bg-secondary text-muted-foreground transition-colors hover:border-primary/30"
        >
          <Bell className="h-[18px] w-[18px]" />
          <span className="absolute right-2.5 top-2.5 h-2 w-2 rounded-full bg-destructive" />
        </button>

        <DropdownMenu>
          <DropdownMenuTrigger className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
            {user.initials}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuLabel>
              <p className="text-sm font-medium">{user.name}</p>
              <p className="text-xs font-normal text-muted-foreground">{user.role}</p>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem>Profile</DropdownMenuItem>
            <DropdownMenuItem onClick={() => navigate("/settings")}>Settings</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              onClick={handleLogout}
            >
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
