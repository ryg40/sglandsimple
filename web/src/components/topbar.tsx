import { useLocation } from "react-router-dom";
import { Search } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";

const TITLES: Record<string, { title: string; subtitle: string }> = {
  "/": { title: "Overview", subtitle: "Enterprise data at a glance" },
  "/chat": { title: "Chat", subtitle: "Ask the agent — it dispatches MCP tools" },
  "/sheet": { title: "Sheet", subtitle: "Edit collections directly or in plain English" },
  "/wrangler": { title: "Wrangler", subtitle: "Build aggregation pipelines, stage by stage" },
};

export function Topbar() {
  const { pathname } = useLocation();
  const meta = TITLES[pathname] ?? { title: "sglandsimple", subtitle: "" };
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
      <ThemeToggle />
    </header>
  );
}
