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
        return "bg-emerald-500";
      case "degraded":
        return "bg-amber-500";
      case "disabled":
        return "bg-slate-400";
      case "error":
        return "bg-rose-500";
      default:
        return "bg-cyan-500"; // placeholder / mock
    }
  };

  const getSystemIcon = (name: string) => {
    switch (name.toLowerCase()) {
      case "mongodb":
        return <Database className="h-5 w-5 text-emerald-500" />;
      case "jira":
        return <Terminal className="h-5 w-5 text-blue-500" />;
      case "confluence":
        return <BookOpen className="h-5 w-5 text-cyan-500" />;
      case "github":
        return <Github className="h-5 w-5 text-slate-800" />;
      case "aws":
        return <Cloud className="h-5 w-5 text-amber-500" />;
      case "servicenow":
        return <Layers className="h-5 w-5 text-indigo-500" />;
      case "snowflake":
        return <Hash className="h-5 w-5 text-sky-400" />;
      default:
        return <HelpCircle className="h-5 w-5 text-slate-400" />;
    }
  };

  const status = health?.status || "disabled";
  const color = getStatusColor(status);

  // Render a compact descriptive label
  const getMetricsSummary = () => {
    if (status === "disabled") return "Not Connected";
    if (name === "mongodb") return `${summary.collections?.length || 0} collections`;
    if (name === "jira") return `${summary.open_issues_count || 0} open issues`;
    if (name === "confluence") return `${summary.pages_count || 0} pages synced`;
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
