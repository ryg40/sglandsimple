import { Badge } from "./ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";
import { 
  Database, 
  Terminal, 
  Github, 
  Cloud, 
  Layers, 
  HelpCircle,
  Hash,
  BookOpen
} from "lucide-react";

interface BubbleProps {
  name: string;
  health: { status: string; detail?: string };
  summary: Record<string, any>;
  isSelected: boolean;
  onSelect: () => void;
}

export function ConnectionBubble({ name, health, summary, isSelected, onSelect }: BubbleProps) {
  // Pick color and icon based on Status
  const getStatusColor = (status: string) => {
    switch (status?.toLowerCase()) {
      case "healthy":
      case "ok":
        return "bg-success";
      case "degraded":
        return "bg-warning";
      case "disabled":
        return "bg-muted-foreground";
      case "error":
        return "bg-destructive";
      default:
        return "bg-secondary"; // placeholder / mock
    }
  };

  const getSystemIcon = (name: string) => {
    switch (name.toLowerCase()) {
      case "mongodb":
        return <Database className="h-5 w-5 text-success" />;
      case "jira":
        return <Terminal className="h-5 w-5 text-secondary" />;
      case "confluence":
        return <BookOpen className="h-5 w-5 text-secondary" />;
      case "github":
        return <Github className="h-5 w-5 text-foreground" />;
      case "aws":
        return <Cloud className="h-5 w-5 text-primary" />;
      case "servicenow":
        return <Layers className="h-5 w-5 text-secondary" />;
      case "snowflake":
        return <Hash className="h-5 w-5 text-secondary" />;
      default:
        return <HelpCircle className="h-5 w-5 text-muted-foreground" />;
    }
  };

  const status = health?.status || "disabled";
  const color = getStatusColor(status);

  // Render a compact descriptive label. Confluence keeps a seeded dry-run
  // sample even when the live Atlassian MCP gate is disabled, so show that
  // evidence instead of the generic "Not Connected" copy.
  const getMetricsSummary = () => {
    if (name === "confluence") {
      const pages = summary.pages_count || 0;
      return status === "disabled" ? `${pages} dry-run pages` : `${pages} pages synced`;
    }
    if (status === "disabled") return "Not Connected";
    if (name === "mongodb") return `${summary.collections?.length || 0} collections`;
    if (name === "jira") return `${summary.open_issues_count || 0} open issues`;
    if (name === "github") return `${summary.prs_count || 0} active PRs`;
    if (name === "aws") return `${summary.rds_instances_count || 0} DB instances`;
    if (name === "servicenow") return `${summary.open_incidents || 0} compliance incident tickets`;
    if (name === "snowflake") return `${(summary.audit_log_rows_count || 0).toLocaleString()} proofs rows`;
    return "Placeholder Status Active";
  };

  return (
    <Card 
      onClick={onSelect}
      className={`cursor-pointer transition-all duration-200 shadow-sm border ${
        isSelected ? "border-primary ring-2 ring-primary/20 bg-primary/5 shadow-md scale-[1.02]" : "hover:border-primary/50"
      }`}
    >
      <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
        <CardTitle className="text-sm font-semibold capitalize flex items-center gap-2">
          {getSystemIcon(name)}
          {name}
        </CardTitle>
        <span className={`h-2.5 w-2.5 rounded-full ${color} animate-pulse`} />
      </CardHeader>
      <CardContent>
        <div className="text-xs text-muted-foreground font-medium">
          {getMetricsSummary()}
        </div>
        <div className="flex gap-1.5 mt-2">
          <Badge variant="outline" className="text-[10px] uppercase font-mono py-0 px-1">
            {status}
          </Badge>
          {summary.status && (
            <Badge variant="outline" className="text-[10px] text-muted-foreground font-mono py-0 px-1">
              Active Sync
            </Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
