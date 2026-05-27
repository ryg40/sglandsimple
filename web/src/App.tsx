import { useState, lazy, Suspense } from "react";
import { Loader2 } from "lucide-react";
import { Routes, Route, useLocation } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppSidebar } from "@/components/app-sidebar";
import { Topbar } from "@/components/topbar";
import { AuthProvider } from "@/components/auth-provider";
import { RequireCapability, Capability } from "@/components/auth-provider";
import { Forbidden } from "@/components/forbidden";
// GlobalAssistant is a floating widget that pulls react-markdown/highlight.js
// (~100KB gz). Lazy-load it so that vendor-markdown stays off the cold path —
// it mounts after first paint inside the route <Suspense>.
const GlobalAssistant = lazy(() =>
  import("@/components/chat-assistant").then((m) => ({ default: m.GlobalAssistant })),
);
// Landing route stays eager so "/" paints without a chunk round-trip.
import Overview from "@/routes/overview";
// Every other route is code-split (React.lazy) so a fresh session only
// downloads the shell + the route it lands on, instead of one ~1.7MB bundle
// containing React Flow (architecture), Recharts, and markdown/highlight.js.
const Chat = lazy(() => import("@/routes/chat"));
const Sheet = lazy(() => import("@/routes/sheet"));
const Wrangler = lazy(() => import("@/routes/wrangler"));
const Hub = lazy(() => import("@/routes/hub"));
const Workflow = lazy(() => import("@/routes/workflow"));
const Architecture = lazy(() => import("@/routes/architecture"));
const DocsWiki = lazy(() => import("@/routes/docs"));
const Standup = lazy(() => import("@/routes/standup"));
const Agents = lazy(() => import("@/routes/agents"));
const AuthAdmin = lazy(() => import("@/routes/auth-admin"));

function RouteFallback() {
  return (
    <div className="flex h-full items-center justify-center p-10 text-muted-foreground">
      <Loader2 className="mr-2 size-5 animate-spin" />
      Loading…
    </div>
  );
}

export default function App() {
  const [collapsed, setCollapsed] = useState(false);
  const { pathname } = useLocation();
  const showGlobalAssistant = pathname !== "/chat";

  return (
    // AuthProvider is outside TooltipProvider so Topbar/Sidebar can call useAuth().
    // It wraps the full app tree — including AppSidebar and Topbar — so that
    // S19.frontend.2 can gate sidebar items and topbar actions without re-lifting state.
    <AuthProvider>
      <TooltipProvider delayDuration={200}>
        <div className="flex h-screen overflow-hidden">
          <AppSidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
          <div className="flex min-w-0 flex-1 flex-col">
            <Topbar />
            <main className={showGlobalAssistant ? "flex-1 overflow-auto pb-24" : "flex-1 overflow-auto"}>
              <Suspense fallback={<RouteFallback />}>
              <Routes>
                {/* Open to all authenticated (and unauthenticated in disabled/trusted_network mode) */}
                <Route path="/" element={<Overview />} />
                <Route path="/chat" element={<Chat />} />
                <Route path="/architecture" element={<Architecture />} />
                <Route path="/docs" element={<DocsWiki />} />
                <Route path="/hub" element={<Hub />} />
                <Route path="/standup" element={<Standup />} />
                <Route
                  path="/agents"
                  element={
                    <RequireCapability capability={Capability.CAN_RUN_WORKFLOW}>
                      <Agents />
                    </RequireCapability>
                  }
                />

                {/*
                 * /sheet and /wrangler: left OPEN at the route level.
                 * Rationale: read access is useful to viewers; canEditData gates
                 * mutations (insert, delete, NL apply, save pipeline) which
                 * S19.frontend.2 will disable at the action/button level.
                 * Hard-gating the route would break the read-only use case.
                 */}
                <Route path="/sheet" element={<Sheet />} />
                <Route path="/wrangler" element={<Wrangler />} />

                {/*
                 * /workflow: hard-gated — this route exclusively triggers
                 * multi-system write workflows (Jira create, PR open, Confluence
                 * push). Viewers have no meaningful read-only view here.
                 */}
                <Route
                  path="/workflow"
                  element={
                    <RequireCapability capability={Capability.CAN_RUN_WORKFLOW}>
                      <Workflow />
                    </RequireCapability>
                  }
                />

                {/*
                 * /auth-admin: hard-gated — diagnostics for the auth subsystem;
                 * only sg_sec_admin (canAdminAuth) should ever reach this page.
                 */}
                <Route
                  path="/auth-admin"
                  element={
                    <RequireCapability capability={Capability.CAN_ADMIN_AUTH}>
                      <AuthAdmin />
                    </RequireCapability>
                  }
                />

                {/* Dedicated 403 page (also used inline by RequireCapability) */}
                <Route path="/forbidden" element={<Forbidden />} />
              </Routes>
              </Suspense>
            </main>
            {showGlobalAssistant && (
              <Suspense fallback={null}>
                <GlobalAssistant />
              </Suspense>
            )}
          </div>
        </div>
      </TooltipProvider>
    </AuthProvider>
  );
}
