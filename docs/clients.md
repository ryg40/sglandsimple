# Connecting external MCP clients

The MCP server at `mcp:8080/mcp` (host port `${MCP_PORT}`, default `5451`)
speaks JSON-RPC 2.0 over HTTP POST with an SSE keepalive on `GET /mcp`.
Stage 3 adds:

- A `Mcp-Session-Id` header returned on `initialize` and required on
  every subsequent request.
- Optional bearer auth via `MCP_AUTH_TOKEN`. If unset, the server logs a
  warning at startup and accepts unauthenticated requests.
- A per-session token-bucket rate limit (`MCP_RATE_PER_MIN`, default 60).

Set `MCP_AUTH_TOKEN` to a strong random value (e.g.
`openssl rand -hex 32`) before exposing the server beyond the LAN.

## Reachability

- LAN: `http://<your-host>:5451/mcp` — the host port.
- Public (after S3.expose.2 lands): one of
  - `https://${PUBLIC_HOSTNAME}/mcp` (path-routed on the existing host), or
  - `https://${MCP_PUBLIC_HOSTNAME}/mcp` (separate hostname).
  Decide and document in IMPLEMENT.md S3.expose.1.

## opencode

Add this entry to your opencode config (typically `~/.config/opencode/config.json`):

```json
{
  "mcp": {
    "sglandsimple": {
      "type": "remote",
      "url": "http://<your-host>:5451/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

If `MCP_AUTH_TOKEN` is unset on the server, omit the `headers` block.

## VS Code Chat / GitHub Copilot Chat

`settings.json`:

```json
{
  "mcp.servers": {
    "sglandsimple": {
      "type": "http",
      "url": "http://<your-host>:5451/mcp",
      "headers": {
        "Authorization": "Bearer <MCP_AUTH_TOKEN>"
      }
    }
  }
}
```

## PiAgent / generic Streamable-HTTP MCP client

Most generic Streamable-HTTP clients want:

- URL: `http://<your-host>:5451/mcp`
- Method: POST for requests; GET for the keepalive SSE stream
- Headers:
  - `Content-Type: application/json`
  - `Authorization: Bearer <MCP_AUTH_TOKEN>` (if set)
  - `Mcp-Session-Id: <id from initialize response>` on every call after
    the first `initialize` exchange

## Quick smoke test (curl)

```bash
# 1. initialize; grab the session id from the response header
SID=$(curl -sS -i http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer $MCP_AUTH_TOKEN' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  | awk '/^mcp-session-id:/ {print $2}' | tr -d '\r')

# 2. list tools using that session
curl -sS http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | jq '.result.tools | map(.name)'

# 3. call ask_data
curl -sS http://localhost:5451/mcp \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ask_data","arguments":{"question":"open tickets per priority"}}}'
```

## Notes

- The `GET /mcp` SSE stream currently emits only `event: ping` keepalives.
  Stage 3.2 (deferred) wires per-session response push for clients that
  prefer to receive responses on SSE rather than as the POST result.
- Streaming chat completions (`stream: true`) is not supported by the
  agent. MCP tool calls are non-streaming JSON-RPC and are unaffected.
