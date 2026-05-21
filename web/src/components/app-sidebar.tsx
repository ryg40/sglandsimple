import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  MessageSquare,
  Table2,
  Workflow,
  PanelLeftClose,
  PanelLeft,
  Activity,
  Shield,
  Clock,
  Network,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useCollections } from "@/lib/queries";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
}
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Workspace", items: [{ to: "/", label: "Overview", icon: LayoutDashboard, end: true }] },
  {
    group: "Tools",
    items: [
      { to: "/chat", label: "Chat", icon: MessageSquare },
      { to: "/sheet", label: "Sheet", icon: Table2 },
      { to: "/wrangler", label: "Wrangler", icon: Workflow },
      { to: "/hub", label: "Compliance Hub", icon: Shield },
      { to: "/architecture", label: "Architecture", icon: Network },
      { to: "/workflow", label: "Workflow Orchestrator", icon: Clock },
    ],
  },
];

export function AppSidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { data, isError } = useCollections();
  const total = data?.collections.reduce((s, c) => s + c.count, 0) ?? 0;

  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200",
        collapsed ? "w-16" : "w-60"
      )}
    >
      <div className="flex h-14 items-center gap-2 px-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground text-sm font-bold">
          sg
        </div>
        {!collapsed && <span className="font-semibold tracking-tight">sglandsimple</span>}
        <button
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="ml-auto rounded-md p-1.5 text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        >
          {collapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-2">
        {NAV.map((section) => (
          <div key={section.group} className="mb-3">
            {!collapsed && (
              <div className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                {section.group}
              </div>
            )}
            {section.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "mb-0.5 flex items-center gap-3 rounded-md px-2 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                    collapsed && "justify-center"
                  )
                }
                title={collapsed ? item.label : undefined}
              >
                <item.icon className="size-4 shrink-0" />
                {!collapsed && <span>{item.label}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      {!collapsed && (
        <div className="m-3 rounded-lg border border-sidebar-border bg-card/60 p-3">
          <div className="mb-1 flex items-center gap-2 text-xs font-medium">
            <Activity className={cn("size-3.5", isError ? "text-destructive" : "text-success")} />
            {isError ? "MCP unreachable" : "Connected"}
          </div>
          <div className="tnum text-2xl font-semibold">{total.toLocaleString()}</div>
          <div className="text-xs text-muted-foreground">records across collections</div>
        </div>
      )}
    </aside>
  );
}
