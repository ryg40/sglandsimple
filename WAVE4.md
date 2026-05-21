# Wave 4 — Reporting: PDF/PPT Artifacts

**Goal:** Server-side report generation that aggregates a finding's full graph into audience-tuned outputs.

---

## Wave 4.1 — S9.report.1: Pick libraries + report data aggregator

**Files:** `mcp/requirements.txt`, `mcp/report/aggregate.py`, `mcp/report/__init__.py`

1. Add to `mcp/requirements.txt`:
   - `weasyprint` or `fpdf2` for PDF generation.
   - `python-pptx` for PPTX generation.
2. `aggregate.py`:
   ```python
   async def aggregate_report(finding_id: str) -> ReportModel:
       # Pull from all collections
       finding = await find_workflow("audit_findings", finding_id)
       epic = await find_workflow("epics", finding["epic_id"])
       work_items = await db.find_many("work_items", {"finding_id": finding_id})
       prs = await db.find_many("pr_records", {"work_item_id": {"$in": [...]}})
       docs = await db.find_many("doc_records", {"epic_id": epic["_id"]})
       logs = await db.find_many("log_samples", {"finding_id": finding_id})
       return ReportModel(finding=finding, epic=epic, work_items=work_items, prs=prs, docs=docs, logs=logs)
   ```
3. `ReportModel` is a Pydantic model with all nested data.

---

## Wave 4.2 — S9.report.2: `report_pdf` + `report_ppt` MCP tools

**Files:** `mcp/report/pdf.py`, `mcp/report/ppt.py`, `mcp/server.py`

1. **`report_pdf`**
   - Aggregates the full graph.
   - Generates a narrative compliance artifact:
     - Cover page: Finding title + regulation + date.
     - Section 1: Regulatory requirement.
     - Section 2: Implementation evidence (epic, tickets, PRs).
     - Section 3: Real log excerpts (from `log_samples`) proving control.
     - Section 4: Links and references.
   - Writes to `REPORT_OUTPUT_DIR / <finding_id>_<timestamp>.pdf`.
   - Returns `{content: [{text: markdown summary}, {text: json with path}]} }`.

2. **`report_ppt`**
   - Same aggregation.
   - Generates an executive summary deck:
     - Slide 1: Title + status.
     - Slide 2: Status overview (green/yellow/red per step).
     - Slide 3: Coverage matrix (DB engine × platform).
     - Slide 4: What the logs prove (3 sample excerpts).
     - Slide 5: Next steps / open items.
   - Writes to `REPORT_OUTPUT_DIR / <finding_id>_<timestamp>.pptx`.

3. Register both tools in `mcp/server.py`.

---

## Commit checkpoint

```bash
git add .
git commit -m "S9 Wave 4: PDF/PPT report generation tools"
docker compose build mcp
```
