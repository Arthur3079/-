import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Users,
  Globe,
  Flame,
  Search,
  MessageSquare,
  Heart,
  BarChart3,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSidebarStore } from "@/stores/sidebar-store";
import { Button } from "@/components/ui/button";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/accounts", label: "Accounts", icon: Users },
  { to: "/proxies", label: "Proxies", icon: Globe },
  { to: "/warming", label: "Warming", icon: Flame },
  { to: "/parsers", label: "Parsers", icon: Search },
  { to: "/commenting", label: "Commenting", icon: MessageSquare },
  { to: "/reactions", label: "Reactions", icon: Heart },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
] as const;

export function Sidebar() {
  const collapsed = useSidebarStore((s) => s.collapsed);
  const toggle = useSidebarStore((s) => s.toggle);

  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r border-sidebar-border bg-sidebar transition-all duration-200",
        collapsed ? "w-16" : "w-64",
      )}
    >
      <div className="flex h-14 items-center justify-between border-b border-sidebar-border px-4">
        {!collapsed && (
          <span className="text-lg font-semibold text-sidebar-foreground">
            Combine
          </span>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          className="ml-auto text-sidebar-foreground hover:bg-sidebar-accent"
        >
          {collapsed ? (
            <PanelLeft className="h-5 w-5" />
          ) : (
            <PanelLeftClose className="h-5 w-5" />
          )}
        </Button>
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                collapsed && "justify-center px-0",
              )
            }
          >
            <Icon className="h-5 w-5 shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-sidebar-border p-4">
        {!collapsed && (
          <p className="text-xs text-muted-foreground">
            Combine v0.1.0
          </p>
        )}
      </div>
    </aside>
  );
}
