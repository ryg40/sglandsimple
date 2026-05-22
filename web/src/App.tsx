import { useState } from "react";
import { Routes, Route, useLocation } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppSidebar } from "@/components/app-sidebar";
import { Topbar } from "@/components/topbar";
import { AuthProvider } from "@/components/auth-provider";
import { RequireCapability, Capability } from "@/components/auth-provider";
import { Forbidden } from "@/components/forbidden";
import { GlobalAssistant } from "@/components/chat-assistant";
import Overview from "@/routes/overview";
import Chat from "@/routes/chat";
import Sheet from "@/routes/sheet";
import Wrangler from "@/routes/wrangler";
import Hub from "@/routes/hub";
import Workflow from "@/routes/workflow";
import Architecture from "@/routes/architecture";
import DocsWiki from "@/routes/docs";
import Standup from "@/routes/standup";
import AuthAdmin from "@/routes/auth-admin";

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
              <Routes>
                {/* Open to all authenticated (and unauthenticated in disabled/trusted_network mode) */}
                <Route path="/" element={<Overview />} />
                <Route path="/chat" element={<Chat />} />
                <Route path="/architecture" element={<Architecture />} />
                <Route path="/docs" element={<DocsWiki />} />
                <Route path="/hub" element={<Hub />} />
                <Route path="/standup" element={<Standup />} />

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
            </main>
            {showGlobalAssistant && <GlobalAssistant />}
          </div>
        </div>
      </TooltipProvider>
    </AuthProvider>
  );
}
