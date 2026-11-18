"""Custom MCP server (streamable HTTP at /mcp) exposing the Agent Bricks Supervisor Agent
"agent-sru-syntax" (serving endpoint mas-c8629507-endpoint) as one MCP tool.
"""
import asyncio
import os

import requests
import uvicorn
from databricks.sdk import WorkspaceClient
from mcp.server.fastmcp import FastMCP

ENDPOINT = os.environ.get("SERVING_ENDPOINT", "mas-c8629507-endpoint")
TIMEOUT_S = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "300"))
EMPTY_MSG = (
    "agent-sru-syntax returned an empty reply for this title. This happens for some titles "
    "(for example, ones about inhibiting virus replication). Use the Unity Catalog function "
    "users.amanda_xu.build_sru_url directly for this title."
)

_ws = WorkspaceClient()  # app service principal credentials from the Apps environment

mcp = FastMCP(
    "sru-syntax-mcp",
    instructions="Converts erratum/correction notice titles into NAL Alma production SRU search URLs "
    "for the original article, using the agent-sru-syntax agent.",
    host="0.0.0.0",  # behind the Apps proxy; avoids localhost-only Host-header checks
    stateless_http=True,
    json_response=True,
)


def _final_text(resp: dict) -> str:
    texts = []
    for item in resp.get("output") or []:
        for c in item.get("content") or []:
            if isinstance(c, dict) and c.get("text"):
                texts.append(c["text"])
    return texts[-1].strip() if texts else ""


def _call_agent(title: str) -> str:
    headers = _ws.config.authenticate()
    headers["Content-Type"] = "application/json"
    r = requests.post(
        f"{_ws.config.host}/serving-endpoints/{ENDPOINT}/invocations",
        headers=headers,
        json={"input": [{"role": "user", "content": title}]},  # title passed through unchanged
        timeout=TIMEOUT_S,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Agent endpoint {ENDPOINT} returned HTTP {r.status_code}: {r.text[:500]}")
    return _final_text(r.json())


@mcp.tool()
async def build_sru_search_url(correction_title: str) -> str:
    """Send an erratum/correction notice title (e.g. 'Correction: <title>', 'Correction to “<title>”',
    'Corrigendum: ...') to the agent-sru-syntax agent and return its reply, which contains the
    NAL Alma production SRU searchRetrieve URL for the original article. Pass the full title exactly
    as given. Replies can take 60-90 seconds."""
    text = await asyncio.to_thread(_call_agent, correction_title)
    return text or EMPTY_MSG


app = mcp.streamable_http_app()  # serves the MCP endpoint at /mcp

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
