import { Card, CardHeader, CardTitle, CardContent } from "./ui/card";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "./ui/tooltip";
import { 
  ShieldCheck, 
  Map, 
  CheckSquare, 
  GitBranch, 
  GitPullRequest, 
  FileText, 
  Download
} from "lucide-react";

interface StepperProps {
  currentStep: number;
  status: string;
  artifacts?: Record<string, any>;
}

export function WorkflowStepper({ currentStep, status, artifacts = {} }: StepperProps) {
  const steps = [
    { title: "Deficiency Finding", icon: ShieldCheck, key: "finding", desc: "Retrieve GRC audit gap details." },
    { title: "Link Strategic Epic", icon: Map, key: "epic", desc: "Map to RDS / regulatory priority tracker." },
    { title: "Jira Compliance Story", icon: CheckSquare, key: "jira", desc: "Build Story payload & sync ticket." },
    { title: "Compliance Branch", icon: GitBranch, key: "branch", desc: "Formulate strategic code branch formats." },
    { title: "Filing Pull Request", icon: GitPullRequest, key: "pr", desc: "Submit code change & security scan checkers." },
    { title: "Confluence Epic-Log", icon: FileText, key: "wiki", desc: "Render compiled compliance doc catalog logs." },
    { title: "Audience-Tuned Report", icon: Download, key: "report", desc: "Generate PDF narrative & Slide Decks." }
  ];

  const getStepStatus = (index: number) => {
    const idx = index + 1;
    if (idx < currentStep) return "completed";
    if (idx === currentStep) {
      if (status === "failed") return "failed";
      if (status === "waiting_approval") return "interrupted";
      return "running";
    }
    return "pending";
  };

  return (
    <TooltipProvider>
      <div className="flex flex-col space-y-4">
        <div className="relative flex justify-between w-full">
          {/* Connector bar background */}
          <div className="absolute top-1/2 left-0 right-0 h-0.5 bg-slate-200 -translate-y-1/2 z-0" />

          {steps.map((s, index) => {
            const stepState = getStepStatus(index);
            const Icon = s.icon;

            let bubbleColor = "bg-slate-100 text-slate-400 border-slate-200";
            if (stepState === "completed") bubbleColor = "bg-emerald-100 text-emerald-600 border-emerald-300";
            else if (stepState === "running") bubbleColor = "bg-primary/10 text-primary border-primary animate-pulse";
            else if (stepState === "interrupted") bubbleColor = "bg-amber-100 text-amber-600 border-amber-300";
            else if (stepState === "failed") bubbleColor = "bg-rose-100 text-rose-600 border-rose-300";

            return (
              <div key={index} className="flex flex-col items-center select-none z-10">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className={`h-11 w-11 rounded-full flex items-center justify-center border-2 ${bubbleColor} bg-white shadow-sm font-semibold text-sm cursor-help`}>
                      <Icon className="h-5 w-5" />
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <div className="space-y-1">
                      <p className="font-semibold text-xs">{s.title}</p>
                      <p className="text-[10px] text-muted-foreground">{s.desc}</p>
                    </div>
                  </TooltipContent>
                </Tooltip>
                <div className="text-center mt-2 max-w-[80px]">
                  <p className="text-[10px] font-semibold text-slate-800 leading-tight truncate">{s.title}</p>
                </div>
              </div>
            );
          })}
        </div>

        {/* Selected Artifact Preview Grid Panel */}
        <Card className="border-muted-foreground/10 fill-muted/30">
          <CardHeader className="py-2.5">
            <CardTitle className="text-xs font-mono uppercase text-muted-foreground">Compliance Step Evidence Metadata Tracker</CardTitle>
          </CardHeader>
          <CardContent className="text-xs space-y-2.5 font-mono py-2.5">
            {currentStep >= 1 && artifacts.finding && (
              <div>
                <span className="text-emerald-600 font-bold">[FINDING]</span> Severity: {artifacts.finding.severity?.toUpperCase()} | {artifacts.finding.requirement}
              </div>
            )}
            {currentStep >= 2 && artifacts.epic && (
              <div>
                <span className="text-emerald-600 font-bold">[EPIC]</span> Title: {artifacts.epic.title} ({artifacts.epic.jira_key})
              </div>
            )}
            {currentStep >= 3 && artifacts.ticket_key && (
              <div>
                <span className="text-emerald-600 font-bold">[TICKET]</span> Jira Ticket Key Linked: <a href="https://jira.internal" target="_blank" rel="noreferrer" className="underline text-blue-500">{artifacts.ticket_key}</a>
              </div>
            )}
            {currentStep >= 4 && artifacts.branch_name && (
              <div>
                <span className="text-emerald-600 font-bold">[BRANCH]</span> Code base Branch format: <code>{artifacts.branch_name}</code>
              </div>
            )}
            {currentStep >= 5 && artifacts.pr_url && (
              <div>
                <span className="text-emerald-600 font-bold">[PULL_REQUEST]</span> GitHub PR: <a href={artifacts.pr_url} target="_blank" rel="noreferrer" className="underline text-blue-500">#{artifacts.pr_number}</a>
              </div>
            )}
            {currentStep >= 6 && artifacts.confluence_url && (
              <div>
                <span className="text-emerald-600 font-bold">[CONFLUENCE]</span> Published compliance logs on Wiki: <a href={artifacts.confluence_url} target="_blank" rel="noreferrer" className="underline text-blue-500">{artifacts.confluence_url}</a>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </TooltipProvider>
  );
}
