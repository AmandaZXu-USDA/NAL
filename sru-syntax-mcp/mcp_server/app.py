"""Custom MCP server (streamable HTTP at /mcp) exposing the Agent Bricks Supervisor Agent
"agent-sru-syntax" (serving endpoint mas-c8629507-endpoint) as one MCP tool.

The same app also hosts the SRU syntax agent (agent.py), which uses this MCP server:
  POST /invocations and POST /responses  - OpenAI Responses-style request: {"input": [...] or "text"}
  GET  /health                           - liveness check
"""
import asyncio
import logging
import os
import uuid

import requests
import uvicorn
from databricks.sdk import WorkspaceClient
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

ENDPOINT = os.environ.get("SERVING_ENDPOINT", "mas-c8629507-endpoint")
TIMEOUT_S = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "300"))
EMPTY_MSG = (
    "agent-sru-syntax returned an empty reply for this title. This happens for some titles "
    "(for example, ones about inhibiting virus replication). Use the Unity Catalog function "
    "users.amanda_xu.build_sru_url directly for this title."
)

_ws = WorkspaceClient()  # app service principal credentials from the Apps environment

# Server-side logs carry only allowlisted fields (error id, category, status code, exception class).
# Upstream bodies, headers, URLs, titles and exception text are never logged or returned to clients.
logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines include request URLs
log = logging.getLogger("mcp_sru_syntax")


class UpstreamError(Exception):
    """Failure calling the Supervisor Agent, with a stable category safe to show clients."""

    MESSAGES = {
        "timeout": "The SRU syntax agent did not respond in time. Try again later.",
        "unavailable": "The SRU syntax agent is unavailable. Try again later.",
        "rate_limited": "The SRU syntax agent is busy. Wait a moment and try again.",
        "permission_denied": "This app is not allowed to call the SRU syntax agent. Contact the app owner.",
        "bad_response": "The SRU syntax agent returned an unexpected response. Try again later.",
    }

    def __init__(self, category: str, status_code: int | None = None):
        self.category = category
        self.status_code = status_code
        self.error_id = uuid.uuid4().hex[:12]
        super().__init__(category)

    def client_message(self) -> str:
        return f"{self.MESSAGES[self.category]} (error {self.category}, id {self.error_id})"


def _category_for_status(status: int) -> str:
    if status in (401, 403):
        return "permission_denied"
    if status == 429:
        return "rate_limited"
    if status in (408, 504):
        return "timeout"
    return "unavailable"

mcp = FastMCP(
    "mcp-sru-syntax",
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
    try:
        r = requests.post(
            f"{_ws.config.host}/serving-endpoints/{ENDPOINT}/invocations",
            headers=headers,
            json={"input": [{"role": "user", "content": title}]},  # title passed through unchanged
            timeout=TIMEOUT_S,
            allow_redirects=False,
        )
    except requests.Timeout:
        raise UpstreamError("timeout") from None
    except requests.RequestException:
        raise UpstreamError("unavailable") from None
    if r.status_code != 200:
        raise UpstreamError(_category_for_status(r.status_code), r.status_code)
    try:
        return _final_text(r.json())
    except ValueError:
        raise UpstreamError("bad_response", r.status_code) from None


@mcp.tool(
    annotations=ToolAnnotations(
        title="Build NAL Alma SRU search URL",
        readOnlyHint=True,  # only reads; creates or changes nothing
        destructiveHint=False,
        idempotentHint=True,  # same title, same intent; safe to retry
        openWorldHint=False,  # calls only this workspace's Supervisor Agent endpoint
    )
)
async def build_sru_search_url(correction_title: str) -> str:
    """Send an erratum/correction notice title (e.g. 'Correction: <title>', 'Correction to “<title>”',
    'Corrigendum: ...') to the agent-sru-syntax agent and return its reply, which contains the
    NAL Alma production SRU searchRetrieve URL for the original article. Pass the full title exactly
    as given. Replies can take 60-90 seconds.

    Errors are returned as a short message with a stable category (timeout, unavailable, rate_limited,
    permission_denied, bad_response) and an error id for the app owner."""
    try:
        text = await asyncio.to_thread(_call_agent, correction_title)
    except UpstreamError as e:
        log.warning("tool_error error_id=%s category=%s status=%s", e.error_id, e.category, e.status_code)
        raise ToolError(e.client_message()) from None
    except Exception as e:  # anything unexpected (e.g. auth setup): never expose its text
        err = UpstreamError("unavailable")
        log.warning("tool_error error_id=%s category=unexpected exception=%s", err.error_id, type(e).__name__)
        raise ToolError(err.client_message()) from None
    return text or EMPTY_MSG


app = mcp.streamable_http_app()  # serves the MCP endpoint at /mcp


class NoGetStreamMiddleware:
    """Answer GET /mcp with 405 right away. In stateless mode the server offers no standalone SSE stream,
    so a GET would otherwise hang; the MCP spec allows 405 here, and clients then use POST only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "GET" and scope["path"].rstrip("/") == "/mcp":
            response = JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Method Not Allowed"}},
                status_code=405,
                headers={"Allow": "POST, DELETE"},
            )
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def _allowed_origins() -> list[str]:
    """The workspace URL (Genie Code calls /mcp from the browser), plus any extra in ALLOWED_ORIGINS."""
    host = (_ws.config.host or os.environ.get("DATABRICKS_HOST", "")).rstrip("/")
    if host and not host.startswith("http"):
        host = f"https://{host}"
    extra = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return [o for o in [host, *extra] if o]


app.add_middleware(NoGetStreamMiddleware)
app.add_middleware(  # added last, so it runs first and answers CORS preflight (OPTIONS) requests
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["mcp-session-id", "mcp-protocol-version"],
)


# ---- SRU syntax agent endpoints (same app) ----

async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def invocations(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be JSON"}, status_code=400)
    messages = body.get("input") if isinstance(body, dict) else None
    if not isinstance(messages, (str, list)) or not messages:
        return JSONResponse({"error": "Body must include 'input' (a string or a list of messages)"}, status_code=400)
    try:
        from agent import run_agent  # imported lazily so the MCP tool keeps working if agent setup fails

        text = await run_agent(messages)
    except Exception as e:
        error_id = uuid.uuid4().hex[:12]
        log.warning("agent_error error_id=%s exception=%s", error_id, type(e).__name__)
        return JSONResponse(
            {"error": f"The SRU syntax agent could not complete the request. Try again later. (error agent_failed, id {error_id})"},
            status_code=502,
        )
    return JSONResponse(
        {
            "id": f"resp_{uuid.uuid4().hex}",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": f"msg_{uuid.uuid4().hex}",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text or "", "annotations": []}],
                }
            ],
        }
    )


app.add_route("/health", health, methods=["GET"])
app.add_route("/invocations", invocations, methods=["POST"])
app.add_route("/responses", invocations, methods=["POST"])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
