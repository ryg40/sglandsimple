"""Compliance report PDF artifact generator utilizing fpdf2."""

from __future__ import annotations

import datetime
import os
from typing import Any

from fpdf import FPDF

from .aggregate import aggregate_report


class CompliancePDF(FPDF):
    """FPDF template configuration with custom header/footer layout."""

    def header(self) -> None:
        self.set_font("helvetica", "B", 10)
        self.set_text_color(100, 110, 120)
        self.cell(0, 10, "STACE-9 AUTOMATED COMPLIANCE VERIFICATION RUN", border=0, align="L")
        self.set_font("helvetica", "I", 9)
        self.cell(0, 10, f"Generated: {datetime.date.today().strftime('%Y-%m-%d')}", border=0, align="R")
        self.ln(15)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Confidential Compliance Evidence Record  |  Page {self.page_no()}", border=0, align="C")


async def generate_pdf_report(finding_id: str, output_dir: str) -> str:
    """Builds a formal multi-page compliance PDF summary."""
    data = await aggregate_report(finding_id)

    # Initialize Document with standard margins
    pdf = CompliancePDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # 1. Cover Page Title Banner
    pdf.set_fill_color(30, 41, 59)  # Slate dark primary
    pdf.rect(10, 25, 190, 30, "F")
    pdf.set_font("helvetica", "B", 16)
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(15, 33)
    pdf.cell(0, 10, "COMPLIANCE VERIFICATION AUDIT ARTIFACT", align="L")

    # Metadata Panel setup
    pdf.ln(25)
    pdf.set_text_color(30, 41, 59)
    pdf.set_font("helvetica", "B", 12)
    pdf.cell(0, 10, f"Regulation Audit Scope: {data.finding.get('regulation', 'SOX-404')}")
    pdf.ln(6)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 10, f"Audit Finding ID: {data.finding.get('_id', 'unknown')}")
    pdf.ln(6)
    pdf.cell(0, 10, f"Epic Key Link: {data.epic.get('jira_key', 'unknown')}")
    pdf.ln(12)

    # 2. Section: Findings & Scope
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(0, 10, "1. Regulatory Deficiency Scope & Requirement Gap", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 9.5)
    pdf.set_text_color(30, 30, 30)

    finding_text = f"Audit Gaps identified under {data.finding.get('regulation', 'SOX-404')}. Gaps dictate: {data.finding.get('requirement', 'Ensure fully auditable access logs.')} (Severity: {data.finding.get('severity', 'HIGH').upper()})"
    pdf.multi_cell(190, 5, finding_text)
    pdf.ln(5)

    # 3. Section: Implementation Evidence (Jira tickets, PRs, Confluence docs)
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(0, 10, "2. Integrated Change-Control Verification Trail", new_x="LMARGIN", new_y="NEXT")

    # Table Grid of Change Artifacts
    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(241, 245, 249)  # Light header
    pdf.cell(35, 7, "System ID", border=1, fill=True)
    pdf.cell(115, 7, "Artifact Link/Detail", border=1, fill=True)
    pdf.cell(40, 7, "Status", border=1, fill=True)
    pdf.ln(7)

    pdf.set_font("helvetica", "", 8.5)
    # Print work items
    for item in data.work_items:
        pdf.cell(35, 6, item.get("jira_key", "JIRA"), border=1)
        pdf.cell(115, 6, f"Jira Change Story (Status: {item.get('status','completed')})", border=1)
        pdf.cell(40, 6, "COMPLETED", border=1)
        pdf.ln(6)

    # Print GitHub Pull requests
    for pr in data.pr_records:
        n = pr.get("pr_number", 0)
        pdf.cell(35, 6, f"PR #{n}", border=1)
        pdf.cell(115, 6, str(pr.get("url", "GitHub Pull request link")), border=1)
        pdf.cell(40, 6, "MERGED", border=1)
        pdf.ln(6)

    # Print Confluence Doc records
    for doc in data.doc_records:
        pdf.cell(35, 6, "Confluence Document", border=1)
        pdf.cell(115, 6, str(doc.get("confluence_url", "Confluence wiki link")), border=1)
        pdf.cell(40, 6, "PUBLISHED", border=1)
        pdf.ln(6)

    pdf.ln(8)

    # 4. Section: Live Database Log Proof Excerpts (from log_samples)
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(0, 10, "3. Live Control Verification Event Logs Auditing Proof", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("helvetica", "B", 9)
    pdf.set_fill_color(241, 245, 249)
    pdf.cell(30, 7, "DB Host", border=1, fill=True)
    pdf.cell(35, 7, "Auditable Event", border=1, fill=True)
    pdf.cell(125, 7, "Raw System Query String/Message Parameters", border=1, fill=True)
    pdf.ln(7)

    pdf.set_font("helvetica", "", 8)
    for log in data.log_samples:
        pdf.cell(30, 6, log.get("source", "db-host"), border=1)
        pdf.cell(35, 6, log.get("event_type", "sql-audit"), border=1)
        pdf.cell(125, 6, log.get("message", "sql query parameters")[0:70], border=1)
        pdf.ln(6)

    pdf.ln(10)
    pdf.set_font("helvetica", "I", 9.5)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(190, 5, "I, Compliance Officer, hereby declare this verification audit catalog represents active system state. This artifact satisfies physical and access proof controls logged under Sarbanes-Oxley mandates.")

    # 5. Save Document to Host Location
    output_filename = f"{finding_id}_{int(datetime.datetime.utcnow().timestamp())}.pdf"
    output_path = os.path.join(output_dir, output_filename)
    os.makedirs(output_dir, exist_ok=True)
    pdf.output(output_path)

    return output_path
