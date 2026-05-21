import { useState } from "react";
import { ConnectionBubble } from "../components/connection-bubble";
import { useConnectors } from "../lib/queries";
import { Skeleton } from "../components/ui/skeleton";
import { AlertCircle, HelpCircle, Shield, RefreshCw, Terminal, ArrowRight, Table, Server, Key } from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { SCHEMA_COLUMNS, fallbackColumns } from "../components/hub-columns";

export default function Hub() {
  const { data, isLoading, isError, error, refetch, isRefetching } = useConnectors();
  const [selectedConnectorName, setSelectedConnectorName] = useState<string>("jira");

  const selectedConnector = data?.connectors?.find((c: any) => c.name === selectedConnectorName);

  // Fallback / standard tools list if none returned or connector properties
  const getConnectorTools = (name: string) => {
    switch (name) {
      case "jira":
        return [
          { name: "jira_search_issues", description: "Search issues using JQL strings.", required: ["jql"] },
          { name: "jira_create_issue", description: "Create a new issue/stub in Jira board.", required: ["project", "summary", "description"] },
          { name: "jira_get_epic", description: "Retrieve hierarchy and checklist alignment metrics.", required: ["epic_key"] }
        ];
      case "github":
        return [
          { name: "github_search_repos", description: "Search matching repository locations.", required: ["query"] },
          { name: "github_create_branch", description: "Create branch for stage development controls.", required: ["repo", "branch"] },
          { name: "github_open_pr", description: "Open a secure PR audit checklist backplane.", required: ["repo", "title", "head"] },
          { name: "github_list_checks", description: "Validate compliance automation scanners on ref.", required: ["repo", "ref"] }
        ];
      case "confluence":
        return [
          { name: "confluence_search_pages", description: "Scan and coordinate runbook manuals.", required: ["query"] },
          { name: "confluence_create_page", description: "Publish new formatted compliance checklist.", required: ["title", "space", "body"] }
        ];
      case "snowflake":
        return [
          { name: "snowflake_query", description: "Perform read-only compliance query on the secure database log warehouse.", required: ["query"] }
        ];
      default:
        return [
          { name: `${name}_get_status`, description: `Perform basic health analysis and fetch active status parameters for ${name}.`, required: [] },
          { name: `${name}_sync_records`, description: `Synchronize audit structures and schema records with ${name}.`, required: [] }
        ];
    }
  };

  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Shield className="h-8 w-8 text-primary" />
            Compliance Connections Hub
          </h2>
          <p className="text-muted-foreground">
            Monitor, explore and inspect direct configurations, sample mock data, and tool definitions across active compliance directory targets.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isLoading || isRefetching}>
            <RefreshCw className={`h-4 w-4 mr-2 ${isRefetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full rounded-xl" />
          ))}
        </div>
      ) : isError ? (
        <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-6 flex flex-col items-center justify-center text-center max-w-xl mx-auto">
          <AlertCircle className="h-10 w-10 text-destructive mb-3" />
          <h4 className="font-semibold text-lg text-destructive">Failed to Load Compliance Connectors</h4>
          <p className="text-muted-foreground text-sm mt-1">
            Ensure the FastAPI web service has robust JSON-RPC connections loaded with the mcp backend.
          </p>
          <pre className="mt-4 p-2 bg-slate-900 rounded font-mono text-[11px] text-slate-300 max-w-full overflow-x-auto">
            {error instanceof Error ? error.message : String(error)}
          </pre>
          <Button variant="outline" size="sm" className="mt-4" onClick={() => refetch()}>
            Retry Connection Request
          </Button>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Quick select selector bar grid of panes */}
          <div className="grid gap-4 grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-8">
            {data?.connectors?.map((conn: any) => (
              <ConnectionBubble
                key={conn.name}
                name={conn.name}
                health={conn.health}
                summary={conn.summary}
                isSelected={selectedConnectorName === conn.name}
                onSelect={() => setSelectedConnectorName(conn.name)}
              />
            ))}
          </div>

          {/* Interactive detail pane containing both subagent tool definitions & mock database lists */}
          {selectedConnector && (
            <div className="grid gap-6 md:grid-cols-3">
              {/* Left Pane: Config & Tools */}
              <Card className="md:col-span-1 border-muted-foreground/10 bg-slate-50/50 dark:bg-slate-900/10">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg font-bold capitalize flex items-center gap-2">
                      {selectedConnectorName} Configuration
                    </CardTitle>
                    <Badge variant={selectedConnector.health?.status === "healthy" ? "success" : "default"} className="uppercase font-mono text-[10px]">
                      {selectedConnector.health?.status || "disabled"}
                    </Badge>
                  </div>
                  <CardDescription>
                    Direct environment variables and metadata constraints for this integration.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <div className="flex justify-between items-center text-xs border-b pb-1">
                      <span className="text-muted-foreground">Connector Name:</span>
                      <span className="font-semibold font-mono">{selectedConnector.name}</span>
                    </div>
                    <div className="flex justify-between items-center text-xs border-b pb-1">
                      <span className="text-muted-foreground">Target Endpoint Address:</span>
                      <span className="font-mono text-[11px] truncate max-w-[180px]" title={selectedConnector.health?.url || "placeholder-stub"}>
                        {selectedConnector.health?.url || "mcp::stub_loopback"}
                      </span>
                    </div>
                    <div className="flex justify-between items-center text-xs border-b pb-1">
                      <span className="text-muted-foreground">Development Gating:</span>
                      <Badge variant="outline" className="text-[10px]">
                        {selectedConnector.health?.status === "disabled" ? "Dry-Run Failback" : "Live Webhook Trigger"}
                      </Badge>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <h4 className="text-sm font-semibold flex items-center gap-1">
                      <Key className="h-4 w-4 text-primary" /> Registered Subagent Tools
                    </h4>
                    <div className="space-y-2 max-h-[300px] overflow-y-auto pr-1">
                      {getConnectorTools(selectedConnectorName).map((tool) => (
                        <div key={tool.name} className="p-2.5 rounded border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-mono font-bold text-slate-800 dark:text-slate-200">{tool.name}</span>
                            <span className="text-[10.5px] font-mono text-muted-foreground">MCP</span>
                          </div>
                          <p className="text-[11px] text-muted-foreground leading-tight">
                            {tool.description}
                          </p>
                          {tool.required.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {tool.required.map((req) => (
                                <Badge key={req} variant="outline" className="text-[9px] lowercase font-mono py-0 px-1 font-normal">
                                  {req}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Right/Middle Pane: Sample data simulation views */}
              <Card className="md:col-span-2 border-muted-foreground/10">
                <CardHeader>
                  <CardTitle className="text-lg font-bold flex items-center gap-2">
                    <Table className="h-5 w-5 text-primary" />
                    Interactive Compliance Proof Explorer ({selectedConnectorName})
                  </CardTitle>
                  <CardDescription>
                    Below live data views simulate records from {selectedConnectorName} when triggered during audit workflows.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {(() => {
                    const rows: any[] = selectedConnector.summary?.sample_data ?? [];
                    const schema: string | undefined = selectedConnector.summary?.schema;
                    const sprint = selectedConnector.summary?.active_sprint;
                    const columns = (schema && SCHEMA_COLUMNS[schema]) || fallbackColumns(rows);
                    if (rows.length === 0) {
                      return (
                        <div className="p-8 border border-dashed rounded-lg text-center text-muted-foreground flex flex-col items-center justify-center">
                          <Server className="h-8 w-8 mb-2 text-slate-400" />
                          <p className="text-xs font-semibold">No simulation records loaded</p>
                          <p className="text-[11px] mt-1">This connector has not published sample records for the current state.</p>
                        </div>
                      );
                    }
                    return (
                      <>
                        {/* Jira active-sprint header */}
                        {schema === "jira_sprint" && sprint && (
                          <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-blue-200/60 bg-blue-50/50 dark:border-blue-900/40 dark:bg-blue-950/20 px-3 py-2 text-xs">
                            <span className="font-semibold text-blue-700 dark:text-blue-300">{sprint.name}</span>
                            <Badge variant="outline" className="text-[9px] uppercase">{sprint.state}</Badge>
                            <span className="text-muted-foreground">{sprint.startDate} → {sprint.endDate}</span>
                            <span className="ml-auto font-mono text-muted-foreground">{sprint.completed}/{sprint.committed} pts done</span>
                            {sprint.goal && <span className="w-full text-[11px] text-muted-foreground italic">🎯 {sprint.goal}</span>}
                          </div>
                        )}
                        <div className="overflow-x-auto rounded border border-slate-200 dark:border-slate-800">
                          <table className="w-full text-left border-collapse text-xs">
                            <thead>
                              <tr className="bg-slate-100 dark:bg-slate-800/50 border-b border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 font-semibold">
                                {columns.map((c) => (
                                  <th key={c.header} className={`p-3 ${c.align === "right" ? "text-right" : ""}`}>{c.header}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                              {rows.map((row: any, idx: number) => (
                                <tr key={idx} className="hover:bg-slate-50/50 dark:hover:bg-slate-900/50 transition-colors">
                                  {columns.map((c) => (
                                    <td key={c.header} className={`p-3 ${c.align === "right" ? "text-right" : ""}`}>{c.cell(row)}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    );
                  })()}

                  {/* Flow Orchestrator Direct Cross-Link Shortcut */}
                  <div className="mt-4 p-4 rounded-lg bg-primary/5 border border-primary/10 flex items-center justify-between">
                    <div className="space-y-0.5">
                      <h4 className="font-semibold text-xs text-primary flex items-center gap-1.5">
                        <Terminal className="h-4 w-4" />
                        Trigger Subagent Compliance Workflows on Selected Systems
                      </h4>
                      <p className="text-[11px] text-muted-foreground">
                        Ready to run simulated checks? Transition seamlessly from inspecting connectors to running the compliance checklist.
                      </p>
                    </div>
                    <Button 
                      onClick={() => window.location.href = "/workflow"}
                      variant="outline" 
                      size="sm" 
                      className="text-xs group hover:bg-primary hover:text-white transition-all duration-200"
                    >
                      Workspace Orchestrator
                      <ArrowRight className="h-3 w-3 ml-2 group-hover:translate-x-1 transition-transform" />
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      )}

      <div className="rounded-xl border border-muted-foreground/10 bg-muted/40 p-6 flex items-start gap-4">
        <HelpCircle className="h-6 w-6 text-primary shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h4 className="font-semibold text-sm">How connection states translate to audit log tracking</h4>
          <p className="text-xs text-muted-foreground leading-relaxed">
            By default, all external connectors remain in <strong>disabled / placeholder</strong> state during development and testing. 
            When disabled, the backend automatically intercepts change commands (e.g. PR filing, Confluence page mutations, Jira tickets) 
            and generates standard compliant <strong>dry-run stubs</strong>. Transition to live triggers is handled by mounting environmental credentials in <code>.env.local</code>.
          </p>
        </div>
      </div>
    </div>
  );
}
