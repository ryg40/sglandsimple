import { ConnectionBubble } from "../components/connection-bubble";
import { useConnectors } from "../lib/queries";
import { Skeleton } from "../components/ui/skeleton";
import { AlertCircle, HelpCircle, Shield, RefreshCw } from "lucide-react";
import { Button } from "../components/ui/button";

export default function Hub() {
  const { data, isLoading, isError, error, refetch, isRefetching } = useConnectors();

  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            <Shield className="h-8 w-8 text-primary" />
            Compliance Connections Hub
          </h2>
          <p className="text-muted-foreground">
            Monitor and administer health parameters of external compliance ledger directories, SQL secure log vaults and code branches.
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
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {data?.connectors?.map((conn: any) => (
            <ConnectionBubble
              key={conn.name}
              name={conn.name}
              health={conn.health}
              summary={conn.summary}
            />
          ))}
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
