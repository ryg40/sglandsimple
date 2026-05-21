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

    async def health(self) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        return {"status": "healthy", "url": self.mcp_url}

    async def summary(self) -> dict:
        if not self.enabled:
            return {"status": "disabled", "rds_instances_count": 0}
        return {"status": "healthy", "rds_instances_count": 4}

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
