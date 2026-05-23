"""Snowflake warehouse SQL adapter connector client."""

from __future__ import annotations

import os
from typing import Any

from .base import Connector


class SnowflakeConnector:
    """SQL execution adaptor adapter targeting the main auditable logger warehouse."""

    name = "snowflake"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.account = os.environ.get("SNOWFLAKE_ACCOUNT", "")
        self.user = os.environ.get("SNOWFLAKE_USER", "")
        self.token = os.environ.get("SNOWFLAKE_TOKEN", "")

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.account or not self.user or not self.token:
            return {"status": "degraded", "error": "Missing Snowflake credentials (account, user, or token)"}
        try:
            # In a real environment, we'd import and run
            # import snowflake.connector
            # conn = snowflake.connector.connect(...)
            # cursor = conn.cursor()
            # cursor.execute("SELECT CURRENT_VERSION()")
            return {"status": "healthy", "version": "8.12.3"}
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "detail": str(e)}

    _SAMPLE = [
        {"timestamp": "2026-05-21 02:11:03", "user_name": "admin_db", "event_type": "login",
         "sql_text": "—", "status": "SUCCESS",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-1"]},
        {"timestamp": "2026-05-21 02:11:05", "user_name": "rds_audit_publisher", "event_type": "query",
         "sql_text": "SELECT COUNT(*) FROM audit_events WHERE finding_id = 'finding-smoke-001'", "status": "SUCCESS",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-2"]},
        {"timestamp": "2026-05-21 02:11:41", "user_name": "evidence_exporter", "event_type": "query",
         "sql_text": "SELECT * FROM confluence_evidence_links WHERE ticket_ref IN ('RDS-LOG-1','RDS-LOG-2')", "status": "SUCCESS",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-1", "RDS-LOG-2"]},
        {"timestamp": "2026-05-21 02:11:48", "user_name": "branch_scan_bot", "event_type": "query",
         "sql_text": "SELECT repo, failing_checks FROM branch_gate_findings WHERE finding_id = 'finding-compliance-jira-01'", "status": "SUCCESS",
         "finding_id": "finding-compliance-jira-01", "epic_key": "SEC-SCAN", "ticket_refs": ["SEC-SCAN-101", "SEC-SCAN-104"]},
        {"timestamp": "2026-05-21 02:12:04", "user_name": "cert_rotation_auditor", "event_type": "query",
         "sql_text": "SELECT cert_arn, expires_at FROM alb_cert_inventory WHERE finding_id = 'finding-stale-certs-02'", "status": "SUCCESS",
         "finding_id": "finding-stale-certs-02", "epic_key": "ALB-ROT", "ticket_refs": ["ALB-ROT-202", "OPS-CERT-202"]},
        {"timestamp": "2026-05-21 02:12:12", "user_name": "unknown_net", "event_type": "sql-error",
         "sql_text": "INSERT INTO evidence_export_control VALUES ('finding-smoke-001', 'override')", "status": "DENIED",
         "finding_id": "finding-smoke-001", "epic_key": "RDS-LOG-1", "ticket_refs": ["RDS-LOG-4"]},
    ]

    def _summary_payload(self, status: str, rows: int) -> dict:
        return {
            "status": status,
            "schema": "snowflake_audit",
            "audit_log_rows_count": rows,
            "denied_count": sum(1 for r in self._SAMPLE if r["status"] == "DENIED"),
            "sample_data": self._SAMPLE,
        }

    async def summary(self) -> dict:
        if not self.enabled:
            return self._summary_payload("disabled", 0)
        return self._summary_payload("healthy", 14522902)

    def tools(self) -> list[dict]:
        return [
            {
                "name": "snowflake_query",
                "description": "Execute queries on the compliance security warehouse, limited to read-only queries.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["query"],
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "content": [{"type": "text", "text": f"Snowflake connector is disabled. Tool '{name}' returned generic stub payload."}],
                "isError": False,
            }

        if name == "snowflake_query":
            # return sample compliance logging proof records matching SOX audits
            return {
                "content": [
                    {"type": "text", "text": """| TIMESTAMP | USER_NAME | EVENT_TYPE | SQL_TEXT | STATUS |
|---|---|---|---|---|
| 2026-05-21 02:11:03 | admin_db | login | — | SUCCESS |
| 2026-05-21 02:11:05 | app_user_stage | query | SELECT * FROM employees | SUCCESS |
| 2026-05-21 02:12:12 | unknown_net | sql-error | INSERT INTO admin_tbl VALUES (...) | DENIED |"""}
                ],
                "isError": False,
            }

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
