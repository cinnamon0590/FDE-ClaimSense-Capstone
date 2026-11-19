"""ClaimSense M3: the governed door (MCP server + RBAC + audit) over AutoSure's four systems of record.

  grants.py     deny-by-default action grants (grants.json)
  door.py       GrantedBoundary: grants -> entitlement -> data, audit on every call; escalations; webhook events
  mcp.py        the MCP protocol (JSON-RPC 2.0, spec 2025-06-18): tools/list, tools/call, transport-agnostic
  http.py       streamable-HTTP transport (OAuth 2.1 resource server) + the signed ticketing webhook receiver
  stdio.py      stdio transport (Claude Code / IDEs) + --selftest
  ticketing.py  client for the 4th backend: idempotent, retry/backoff, circuit breaker
"""
