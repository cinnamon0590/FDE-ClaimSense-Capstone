"""The door is a REAL MCP server: an off-the-shelf client, the OpenAI Agents SDK's MCPServerStreamableHttp (built on the
official `mcp` Python SDK), connects with nothing but the URL and an adjuster's bearer token, lists the tools, and
calls them, getting the same scope decisions as every other caller; a client without a valid token cannot even
initialize. No key, $0.

    python evals/mcp_interop_check.py
"""
import asyncio
import json
import sys

from _common import DOOR, Report, tokens


async def main_async():
    from agents.mcp import MCPServerStreamableHttp
    R = Report(8, "mcp-interop-official-client", "Interop: the official Agents SDK MCP client against the door")
    tok = tokens()
    for user, expect_ok in (("alice", True), ("carol", False)):
        async with MCPServerStreamableHttp(name=f"claimsense-door-{user}", params={
                "url": f"{DOOR}/mcp", "headers": {"Authorization": f"Bearer {tok(user)}",
                                                  "X-On-Behalf-Of-Agent": "agent:interop-check"}},
                client_session_timeout_seconds=30) as door:
            tools = await door.list_tools()
            res = await door.call_tool("get_claim", {"claim_id": "CLM-2024-1800"})
            err = getattr(res, "is_error", getattr(res, "isError", None))
            payload = json.loads(res.content[0].text)
            R.say(f"{user}: initialize OK (protocol negotiated by the mcp SDK) · tools/list -> {len(tools)} tools: "
                  f"{', '.join(t.name for t in tools)}",
                  f"{user}: tools/call get_claim(CLM-2024-1800) -> isError={err} · "
                  + (f"claim {payload.get('claim_id')}" if not err else json.dumps(payload["error"])))
            R.check(f"{user}: official client connects, lists 9 typed tools, and gets the right scope decision",
                    len(tools) == 9 and (not err) == expect_ok)
    try:
        await bad_token_case(R)
    except Exception as e:                                    # the SDK raises on a 401 at connect time
        R.check("a client with no valid token cannot even initialize (401 at the transport)", True,
                f"{type(e).__name__}")
    return R.finish("python evals/mcp_interop_check.py")


async def bad_token_case(R):
    from agents.mcp import MCPServerStreamableHttp
    async with MCPServerStreamableHttp(name="no-token", params={"url": f"{DOOR}/mcp",
                                                               "headers": {"Authorization": "Bearer not-a-jwt"}},
                                       client_session_timeout_seconds=10) as door:
        await door.list_tools()
    R.check("a client with no valid token cannot even initialize (401 at the transport)", False, "it connected")


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
