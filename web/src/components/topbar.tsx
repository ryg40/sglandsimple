import { useLocation } from "react-router-dom";
import { Search, LogIn } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { useAuth } from "@/components/auth-provider";
import { Badge } from "@/components/ui/badge";

const TITLES: Record<string, { title: string; subtitle: string }> = {
  "/": { title: "Overview", subtitle: "Enterprise data at a glance" },
  "/chat": { title: "Chat", subtitle: "Ask the agent — it dispatches MCP tools" },
  "/sheet": { title: "Sheet", subtitle: "Edit collections directly or in plain English" },
  "/wrangler": { title: "Wrangler", subtitle: "Build aggregation pipelines, stage by stage" },
};

/** Variant per auth mode for the mode badge. */
const MODE_VARIANT: Record<string, "default" | "outline" | "warning" | "success"> = {
  sso: "success",
  basic: "default",
  trusted_network: "warning",
  headers: "warning",
  ldap: "success",
  disabled: "outline",
};

export function Topbar() {
  const { pathname } = useLocation();
  const { me, isLoading, authenticated, roles, authMode } = useAuth();

  const meta = TITLES[pathname] ?? { title: "LanGarland", subtitle: "" };

  // Derive display name: prefer display_name, fall back to email username, else "anonymous".
  const displayName = authenticated && me?.user
    ? (me.user.display_name ?? me.user.email?.split("@")[0] ?? "unknown")
    : "anonymous";

  const modeVariant = MODE_VARIANT[authMode] ?? "outline";

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center gap-4 border-b border-border bg-background/80 px-5 backdrop-blur">
      <div className="min-w-0">
        <h1 className="truncate text-sm font-semibold leading-tight">{meta.title}</h1>
        <p className="truncate text-xs text-muted-foreground">{meta.subtitle}</p>
      </div>

      <div className="ml-auto hidden items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground md:flex">
        <Search className="size-4" />
        <span className="text-xs">Search…</span>
        <kbd className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium">⌘K</kbd>
      </div>

      {/* Auth identity section */}
      {!isLoading && (
        <div className="flex items-center gap-2">
          {authenticated ? (
            <>
              {/* Auth mode badge */}
              {authMode && (
                <Badge variant={modeVariant} className="hidden text-[10px] sm:inline-flex">
                  {authMode}
                </Badge>
              )}
              {/* Effective roles */}
              {roles.length > 0 && (
                <div className="hidden items-center gap-1 lg:flex">
                  {roles.map((r) => (
                    <Badge key={r} variant="outline" className="text-[10px]">
                      {r}
                    </Badge>
                  ))}
                </div>
              )}
              {/* Display name */}
              <span className="max-w-32 truncate text-xs font-medium text-foreground" title={me?.user?.email ?? displayName}>
                {displayName}
              </span>
            </>
          ) : (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <LogIn className="size-3.5" />
              {authMode === "basic"
                ? "Browser will prompt for login"
                : "Not signed in"}
            </div>
          )}
        </div>
      )}

      <ThemeToggle />
    </header>
  );
}
