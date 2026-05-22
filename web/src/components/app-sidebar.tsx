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
  ShieldCheck,
  Clock,
  Network,
  BookText,
  UsersRound,
  Lock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useCollections } from "@/lib/queries";
import { useAuth, Capability } from "@/components/auth-provider";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import bannerMark from "@/assets/d6057657-40c7-4112-85fa-06322881a692.png";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
  /** Capability required to navigate this item. Missing cap = disabled + tooltip. */
  requiresCap?: string;
  /** Tooltip message when cap is missing. */
  capTooltip?: string;
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
      {
        to: "/workflow",
        label: "Workflow Orchestrator",
        icon: Clock,
        requiresCap: Capability.CAN_RUN_WORKFLOW,
        capTooltip: "Requires canRunWorkflow (app_user, audit_user, or admin role)",
      },
      { to: "/docs", label: "Docs Wiki", icon: BookText },
      { to: "/standup", label: "Standup", icon: UsersRound },
    ],
  },
  {
    group: "Admin",
    items: [
      {
        to: "/auth-admin",
        label: "Auth Admin",
        icon: ShieldCheck,
        requiresCap: Capability.CAN_ADMIN_AUTH,
        capTooltip: "Requires canAdminAuth (sg_sec_admin role)",
      },
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
  const { hasCapability } = useAuth();

  return (
    <aside
      className={cn(
        "flex h-screen flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200",
        collapsed ? "w-16" : "w-60"
      )}
    >
      <div className="flex h-16 items-center gap-2 px-3">
        <div className={cn("shrink-0 overflow-hidden rounded-xl border border-sidebar-border bg-sidebar-accent shadow-sm", collapsed ? "size-10" : "h-11 w-36")}>
          <img
            src={bannerMark}
            alt="LanGarland Fleet Dispatch"
            className="h-full w-full object-cover"
          />
        </div>
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
            {section.items.map((item) => {
              const allowed = !item.requiresCap || hasCapability(item.requiresCap);
              const tooltip = item.capTooltip ?? "Insufficient permissions";

              const linkCls = cn(
                "mb-0.5 flex items-center gap-3 rounded-md px-2 py-2 text-sm font-medium transition-colors",
                allowed
                  ? "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
                  : "cursor-not-allowed text-sidebar-foreground/40",
                collapsed && "justify-center"
              );

              const inner = (
                <>
                  <item.icon className="size-4 shrink-0" />
                  {!collapsed && <span className="flex-1">{item.label}</span>}
                  {!collapsed && !allowed && <Lock className="size-3 shrink-0 text-muted-foreground" />}
                </>
              );

              if (allowed) {
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      cn(
                        linkCls,
                        isActive && "bg-sidebar-accent text-sidebar-accent-foreground"
                      )
                    }
                    title={collapsed ? item.label : undefined}
                  >
                    {inner}
                  </NavLink>
                );
              }

              // Disabled: show as a non-navigable element with a tooltip.
              return (
                <Tooltip key={item.to}>
                  <TooltipTrigger asChild>
                    <span
                      className={linkCls}
                      aria-disabled="true"
                      title={collapsed ? item.label : undefined}
                    >
                      {inner}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="right">{tooltip}</TooltipContent>
                </Tooltip>
              );
            })}
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
