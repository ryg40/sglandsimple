# Stage 9 Compliance Hub Manual Verification Steps

Follow these validation guidelines to step through end-to-end user evaluation of the built compliance orchestrator system stack.

## Stacks Boot Probes

1. Rebuild and launch the stack container daemon:
   ```bash
   docker compose up --build -d
   ```
2. Verify all 4 microservices report a healthy state:
   ```bash
   docker compose ps
   ```

## Workflow Walkthrough Checklist

1. Open the Compliance connections grid at **`http://localhost:5452/hub`**:
   - Verify that all 8 connection bubbles are rendered successfully.
   - Click each bubble and confirm the details panel pops up.
   - Status indicators should remain in generic **disabled / placeholder** status when environmental tokens are absent, showing gray or orange badges.

2. Open the lifecycle orchestrator at **`http://localhost:5452/workflow`**:
   - The top selector panel should populate with seeded deficiency findings (such as `SOX-404`).
   - Choose a finding and click **"Spawn Compliance Flow"**.
   - Monitor the progress lane horizontal stepper. It should transition through Discovery, Epic Link, Jira payloader, and Branch mapping before stopping at an Interruption Gate waiting for reviewer checks.

3. Complete Human Approval Checks:
   - Click **"Approve & Run"** to satisfy Gate-1. The stepper advances successfully to submit secure PRs.
   - Click **"Approve & Run"** again to satisfy Gate-2. The stepper resumes to re-publish wiki-documents.

4. Formulate Compliance Evidence Catalog downloads:
   - When the workflow completes successfully (Status: `COMPLETED`), click **"Download PDF Compliance Report"**.
   - Confirm a fully styled verification report is compiled and downloads successfully.
   - Examine report parameters. It should aggregate change ticket numbers, branches, wiki references, and list direct auditable proof rows showing access queries.

5. Validate Audit Logs:
   - Open **`http://localhost:5452/overview`** (or go to Recent activity log listings).
   - Verify several audit log events exist showing `source="workflow_*"` details, representing fully backauditable tracking proof.
