import { useState, useEffect } from "react";
import { WorkflowStepper } from "../components/workflow-stepper";
import { RelatePanel } from "../components/relate-panel";
import { Button } from "../components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "../components/ui/card";
import { useWorkflowRun } from "../lib/queries";
import { api } from "../lib/api";
import { 
  Play, 
  CheckCircle, 
  XSquare, 
  FileDown, 
  Clock, 
  ShieldAlert,
  Loader2,
  AlertCircle
} from "lucide-react";
import { toast } from "sonner";

export default function Workflow() {
  const [findingId, setFindingId] = useState("");
  const [findingsList, setByFindingsList] = useState<any[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(false);

  // Workflow run state
  const [runState, setRunState] = useState<any>(null);
  const [checkpointId, setCheckpointId] = useState("");

  const runMutation = useWorkflowRun();

  // Load findings from MongoDB audit_findings collection
  const loadFindingsList = async () => {
    setIsLoadingList(true);
    try {
      // Hits sheets proxy endpoint to unwrap list
      const res = await api.get<any>("/api/sheet/rows?collection=audit_findings&limit=20");
      setByFindingsList(res.rows || []);
      if (res.rows && res.rows.length > 0) {
        setFindingId(res.rows[0]._id);
      }
    } catch (e) {
      console.error("Failed to load audit findings:", e);
      toast.error("Failed to query audit checklist findings from DB.");
    } finally {
      setIsLoadingList(false);
    }
  };

  useEffect(() => {
    loadFindingsList();
  }, []);

  const handleRunWorkflow = () => {
    if (!findingId) return;

    toast.loading("Spawning Stage 9 compliance subagent run daemon...", { id: "workflow" });
    runMutation.mutate(
      { finding_id: findingId },
      {
        onSuccess: (data) => {
          setRunState(data);
          setCheckpointId(data.run_id);
          toast.success("Subagent spawned successfully! Workflow compiled.", { id: "workflow" });
        },
        onError: (err) => {
          toast.error("Subagent workflow error " + String(err), { id: "workflow" });
        }
      }
    );
  };

  const handleApproveGate = (decision: "approve" | "reject") => {
    if (!findingId || !checkpointId) return;

    toast.loading(`Filing HIL approval checkpoint: ${decision.toUpperCase()}...`, { id: "workflow" });
    runMutation.mutate(
      { finding_id: findingId, resume_decision: decision, checkpoint_id: checkpointId },
      {
        onSuccess: (data) => {
          setRunState(data);
          toast.success("Gate completed! Resuming compliance graph workflow node pipeline.", { id: "workflow" });
        },
        onError: (err) => {
          toast.error("HIL resume approval gate failed: " + String(err), { id: "workflow" });
        }
      }
    );
  };

  const handleDownloadReport = (format: "pdf" | "ppt") => {
    if (!findingId) return;
    const url = `/api/reports/download?finding_id=${findingId}&format=${format}`;
    window.open(url, "_blank");
    toast.success(`Export request submitted for ${format.toUpperCase()} compliance artifact.`);
  };

  const isExecuting = runMutation.isPending;
  const currentStep = runState?.step_index || 0;
  const status = runState?.status || "idle";

  return (
    <div className="flex-1 space-y-6 p-8 pt-6">
      <div>
        <h2 className="text-3xl font-bold tracking-tight flex items-center gap-2">
          Compliance Control Lifecycle Orchestrator
        </h2>
        <p className="text-muted-foreground">
          Step audit deficiencies through Best-Practice ticketing, secure branch review requests, re-publishing summaries and compiling evidence archives.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-4">
        {/* Sidebar Selector Card */}
        <Card className="md:col-span-1 border-muted-foreground/10 h-fit">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold">1. Select GRC Target</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs text-slate-500 font-mono">Checklist Finding</label>
              {isLoadingList ? (
                <div className="h-9 flex items-center text-xs text-muted-foreground gap-2">
                  <Loader2 className="h-3 w-3 animate-spin" /> Load GRC register...
                </div>
              ) : (
                <select
                  className="w-full h-9 rounded border border-input px-3 bg-white text-xs"
                  value={findingId}
                  onChange={(e) => {
                    setFindingId(e.target.value);
                    setRunState(null); // Reset runner context
                  }}
                >
                  {findingsList.map((f) => (
                    <option key={f._id} value={f._id}>
                      {f.regulation} - {f._id.slice(0, 12)}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <Button
              className="w-full text-xs shrink-0 flex items-center"
              size="sm"
              disabled={isExecuting || !findingId}
              onClick={handleRunWorkflow}
            >
              {isExecuting ? (
                <Loader2 className="h-3.5 w-3.5 mr-2 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5 mr-2" />
              )}
              Spawn Compliance Flow
            </Button>
          </CardContent>
        </Card>

        {/* Workspace Stepper Lane */}
        <div className="md:col-span-3 space-y-6">
          <Card className="border-muted-foreground/10">
            <CardHeader className="flex flex-row items-center justify-between pb-3 space-y-0">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <Clock className="h-4.5 w-4.5 text-slate-500" />
                Active subagent Execution Workspace Line
              </CardTitle>
              {status !== "idle" && (
                <span className={`text-[10px] font-bold uppercase rounded border px-1.5 py-0.5 ${
                  status === "completed" ? "bg-emerald-50 border-emerald-200 text-emerald-700" :
                  status === "waiting_approval" ? "bg-amber-50 border-amber-200 text-amber-700 animate-pulse" :
                  "bg-blue-50 border-blue-200 text-blue-700"
                }`}>
                  {status}
                </span>
              )}
            </CardHeader>
            <CardContent className="space-y-6">
              {status === "idle" ? (
                <div className="p-8 border border-dashed rounded-lg border-slate-200 text-center text-muted-foreground flex flex-col items-center justify-center">
                  <ShieldAlert className="h-8 w-8 mb-2 text-slate-400" />
                  <p className="text-xs font-semibold">Compliance Runner Inactive</p>
                  <p className="text-[11px] mt-1">Select a checklist finding item and click 'Spawn' above to step compliance controls.</p>
                </div>
              ) : (
                <WorkflowStepper
                  currentStep={currentStep}
                  status={status}
                  artifacts={runState?.artifacts}
                />
              )}

              {/* Approval Interruption Gating Panels */}
              {status === "waiting_approval" && (
                <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div className="space-y-1">
                    <h5 className="font-semibold text-xs text-amber-800 flex items-center gap-1.5">
                      <AlertCircle className="h-4 w-4" />
                      Human-Gate Gate: Compliance Approvals Audit Required
                    </h5>
                    <p className="text-[11.5px] text-amber-700 font-serif leading-relaxed">
                      {runState?.next_action_preview?.message || "Verify the compiled control change records evidence catalog before finalizing writes."}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" className="text-emerald-700 hover:bg-emerald-50 border-emerald-200 text-xs shrink-0 h-8" onClick={() => handleApproveGate("approve")}>
                      <CheckCircle className="h-3.5 w-3.5 mr-1" />
                      Approve & Run
                    </Button>
                    <Button variant="outline" size="sm" className="text-rose-700 hover:bg-rose-50 border-rose-200 text-xs shrink-0 h-8" onClick={() => handleApproveGate("reject")}>
                      <XSquare className="h-3.5 w-3.5 mr-1" />
                      Reject Gaps
                    </Button>
                  </div>
                </div>
              )}

              {/* PDF/PPT Exports Stage Button actions */}
              {status === "completed" && (
                <div className="flex flex-col sm:flex-row gap-2 border-t pt-4">
                  <Button variant="outline" size="sm" className="text-xs shrink-0 flex items-center" onClick={() => handleDownloadReport("pdf")}>
                    <FileDown className="h-3.5 w-3.5 mr-2 text-emerald-600" />
                    Download PDF Compliance Report
                  </Button>
                  <Button variant="outline" size="sm" className="text-xs shrink-0 flex items-center" onClick={() => handleDownloadReport("ppt")}>
                    <FileDown className="h-3.5 w-3.5 mr-2 text-orange-500" />
                    Download Executive PPT Slide Deck
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Relate Cross-linked Entity records panels */}
          {runState?.artifacts && (
            <RelatePanel artifacts={runState.artifacts} />
          )}
        </div>
      </div>
    </div>
  );
}
