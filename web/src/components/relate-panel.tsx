import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";
import { Badge } from "./ui/badge";
import { FileText, Shield } from "lucide-react";

interface RelateProps {
  artifacts: Record<string, any>;
}

export function RelatePanel({ artifacts }: RelateProps) {
  const finding = artifacts.finding || {};
  const epic = artifacts.epic || {};

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Finding scope Card */}
      <Card className="border-muted-foreground/10 h-full">
        <CardHeader className="flex flex-row items-center gap-2 pb-2">
          <Shield className="h-4.5 w-4.5 text-destructive" />
          <CardTitle className="text-sm font-semibold">Deficiency Scope Target</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs">
          <div className="flex gap-2 items-center">
            <span className="font-semibold text-muted-foreground font-mono">Regulation:</span>
            <Badge variant="outline" className="font-mono text-[10px]">{finding.regulation || "SOX-404"}</Badge>
          </div>
          <div>
            <span className="font-semibold text-muted-foreground font-mono">Requirement:</span>
            <p className="mt-1 text-foreground leading-relaxed">{finding.requirement || "Wait for compliance scan details."}</p>
          </div>
          <div className="flex justify-between items-center bg-muted/50 p-2.5 rounded border font-mono">
            <span>Severity: <strong className="text-destructive">{finding.severity?.toUpperCase() || "HIGH"}</strong></span>
            <span>Status: <strong>{finding.status?.toUpperCase() || "OPEN"}</strong></span>
          </div>
        </CardContent>
      </Card>

      {/* Epic details Card */}
      <Card className="border-muted-foreground/10 h-full">
        <CardHeader className="flex flex-row items-center gap-2 pb-2">
          <FileText className="h-4.5 w-4.5 text-secondary" />
          <CardTitle className="text-sm font-semibold">Strategic Mapping Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-xs">
          <div className="flex gap-2 items-center">
            <span className="font-semibold text-muted-foreground font-mono">Jira Key:</span>
            <Badge variant="outline" className="font-mono">{epic.jira_key || "RDS-LOG-1"}</Badge>
          </div>
          <div className="flex gap-2 items-center">
            <span className="font-semibold text-muted-foreground font-mono">Epic Title:</span>
            <span className="text-foreground font-medium">{epic.title || "RDS Database Audit Logging Policy"}</span>
          </div>
          <div>
            <span className="font-semibold text-muted-foreground font-mono block mb-1">Target Engine Combos:</span>
            <div className="flex flex-wrap gap-1">
              {(epic.db_platform_combos || ["RDS MySQL", "RDS PostgreSQL"]).map((c: string) => (
                <Badge key={c} variant="outline" className="font-mono text-[9px] py-0 px-1">{c}</Badge>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
