import { useState } from "react";
import { Routes, Route } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AppSidebar } from "@/components/app-sidebar";
import { Topbar } from "@/components/topbar";
import Overview from "@/routes/overview";
import Chat from "@/routes/chat";
import Sheet from "@/routes/sheet";
import Wrangler from "@/routes/wrangler";

export default function App() {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-screen overflow-hidden">
        <AppSidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <main className="flex-1 overflow-auto">
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/sheet" element={<Sheet />} />
              <Route path="/wrangler" element={<Wrangler />} />
            </Routes>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
