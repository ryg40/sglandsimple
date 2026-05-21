"""AWS RDS connector client."""

from __future__ import annotations

import os
from typing import Any

from .base import Connector


class AWSConnector:
    """Connector for AWS RDS."""

    name = "aws"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.mcp_url = os.environ.get("AWS_MCP_URL", "")
        self.mcp_token = os.environ.get("AWS_MCP_TOKEN", "")

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        if not self.mcp_url:
            return {"status": "degraded", "error": "Missing AWS_MCP_URL"}
        return {"status": "healthy", "url": self.mcp_url}

    # Mock cloud inventory spanning multiple services so the Hub pane reads like
    # an AWS console. One prod RDS row deliberately has audit logging disabled —
    # the topology surfaces it as a weak-spot.
    _SAMPLE = [
        {"account_id": "418274916532", "account_alias": "compliance-prod", "region": "us-east-1",
         "resource_id": "rds-mysql-prod-01", "service": "RDS", "resource_type": "db.r6g.xlarge",
         "status": "available", "env": "prod", "audit_logging": "enabled"},
        {"account_id": "418274916532", "account_alias": "compliance-prod", "region": "us-east-1",
         "resource_id": "rds-postgres-prod-02", "service": "RDS", "resource_type": "db.r6g.large",
         "status": "available", "env": "prod", "audit_logging": "disabled"},
        {"account_id": "418274916532", "account_alias": "compliance-prod", "region": "eu-west-1",
         "resource_id": "rds-mariadb-prod-03", "service": "RDS", "resource_type": "db.r6g.large",
         "status": "available", "env": "prod", "audit_logging": "enabled"},
        {"account_id": "771045820013", "account_alias": "compliance-stage", "region": "us-west-2",
         "resource_id": "rds-postgres-stg-01", "service": "RDS", "resource_type": "db.t4g.medium",
         "status": "available", "env": "staging", "audit_logging": "enabled"},
        {"account_id": "418274916532", "account_alias": "compliance-prod", "region": "us-east-1",
         "resource_id": "audit-logs-archive-prod", "service": "S3", "resource_type": "bucket (object-lock)",
         "status": "active", "env": "prod", "audit_logging": "enabled"},
        {"account_id": "418274916532", "account_alias": "compliance-prod", "region": "us-east-1",
         "resource_id": "compliance-org-trail", "service": "CloudTrail", "resource_type": "multi-region trail",
         "status": "logging", "env": "prod", "audit_logging": "enabled"},
        {"account_id": "418274916532", "account_alias": "compliance-prod", "region": "us-east-1",
         "resource_id": "alias/rds-audit-cmk", "service": "KMS", "resource_type": "symmetric CMK",
         "status": "enabled", "env": "prod", "audit_logging": "n/a"},
        {"account_id": "418274916532", "account_alias": "compliance-prod", "region": "us-east-1",
         "resource_id": "alb-compliance-edge", "service": "ELB", "resource_type": "application LB",
         "status": "active", "env": "prod", "audit_logging": "enabled"},
        {"account_id": "418274916532", "account_alias": "compliance-prod", "region": "global",
         "resource_id": "role/RDSAuditPublisher", "service": "IAM", "resource_type": "service role",
         "status": "active", "env": "prod", "audit_logging": "n/a"},
    ]

    async def summary(self) -> dict:
        rds = sum(1 for r in self._SAMPLE if r["service"] == "RDS")
        base = {
            "schema": "aws_resources",
            "rds_instances_count": rds,
            "resources_count": len(self._SAMPLE),
            "logging_gaps": sum(1 for r in self._SAMPLE if r["audit_logging"] == "disabled"),
            "sample_data": self._SAMPLE,
        }
        if not self.enabled:
            return {"status": "disabled", **base}
        return {"status": "healthy", **base}

    def tools(self) -> list[dict]:
        return [
            {
                "name": "aws_list_rds_instances",
                "description": "List AWS RDS instances.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "aws_describe_instance",
                "description": "Describe an AWS RDS instance.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "db_instance_identifier": {"type": "string"},
                    },
                    "required": ["db_instance_identifier"],
                },
            },
        ]

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "content": [{"type": "text", "text": f"AWS connector is disabled. Tool '{name}' returned generic stub payload."}],
                "isError": False,
            }

        if name == "aws_list_rds_instances":
            return {"content": [{"type": "text", "text": '{"instances": ["rds-mysql-production", "rds-postgres-staging"]}'}], "isError": False}
        if name == "aws_describe_instance":
            ident = args.get("db_instance_identifier", "db-instance")
            return {"content": [{"type": "text", "text": f'{{"DBInstanceIdentifier": "{ident}", "DBInstanceStatus": "available", "Engine": "mysql"}}'}], "isError": False}

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
