"""Custom MCP server (streamable HTTP at /mcp) exposing the Agent Bricks Supervisor Agent
"agent-sru-syntax" (serving endpoint mas-c8629507-endpoint) as one MCP tool.

The same app also hosts the SRU syntax agent (agent.py), which uses this MCP server:
  POST /invocations and POST /responses  - OpenAI Responses-style request: {"input": [...] or "text"}
  GET  /health                           - liveness check
and a browser page for librarians:
  GET  /                                 - paste one correction title, get the SRU URL as a link
  POST /api/sru-url                      - JSON {"title": "..."} -> {"text": ..., "urls": [...]}
"""
import asyncio
import logging
import os
import re
import secrets
import uuid

import requests
import uvicorn
from databricks.sdk import WorkspaceClient
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

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


def _call_agent_retry_empty(title: str) -> str:
    """Call the agent; if the reply is empty, ask once more. Empty replies come back within a few
    seconds, so the retry costs little. In testing (2026-11-19) the 3 titles that got empty replies
    were empty on every try, so this only helps titles whose empty reply is intermittent.
    Errors (timeouts etc.) are not retried, so a slow failure never doubles the wait."""
    text = _call_agent(title)
    if not text.strip():
        log.info("empty_agent_reply retrying=1")
        text = _call_agent(title)
        log.info("empty_agent_reply retry_result=%s", "ok" if text.strip() else "empty")
    return text


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
        text = await asyncio.to_thread(_call_agent_retry_empty, correction_title)
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


# ---- Browser page for librarians (same app; Databricks Apps handles the login) ----

SRU_PREFIX = "https://nal.alma.exlibrisgroup.com/view/sru/"
MAX_TITLE_CHARS = 1000
_SRU_URL_RE = re.compile(re.escape(SRU_PREFIX) + r"[^\s<>\"'`]+")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAL SRU search URL from a correction title</title>
<style nonce="__NONCE__">
  body { font-family: system-ui, -apple-system, "Segoe UI", Arial, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; color: #1b1b1b; line-height: 1.5; }
  h1 { font-size: 1.5rem; margin-bottom: .25rem; }
  label { font-weight: 600; display: block; margin: 1rem 0 .25rem; }
  textarea { width: 100%; box-sizing: border-box; font: inherit; padding: .5rem; min-height: 5rem; }
  button { font: inherit; padding: .45rem 1rem; margin-top: .5rem; cursor: pointer; }
  #status { margin-top: 1rem; color: #4a4a4a; }
  #result { margin-top: .5rem; }
  .url { word-break: break-all; display: block; margin: .25rem 0; }
  .error { color: #b50909; }
  .hint { color: #4a4a4a; font-size: .92rem; }
</style>
</head>
<body>
<h1>SRU search URL from a correction title</h1>
<p class="hint">Paste one erratum or correction notice title, for example
<em>Correction: Effects of drought stress on maize grain yield and quality</em>. You get the NAL Alma
production SRU searchRetrieve URL for the original article. Open it to see the matching Alma record.</p>
<form id="f">
  <label for="title">Correction title</label>
  <textarea id="title" name="title" maxlength="__MAX__" required></textarea>
  <button type="submit" id="go">Get SRU URL</button>
</form>
<div id="status" role="status" aria-live="polite"></div>
<div id="result"></div>
<p class="hint">Replies usually take 15-60 seconds. One title per request; for long lists, use the SQL
function <code>users.amanda_xu.build_sru_url</code>. Copy URLs as they are; do not edit the encoding.</p>
<script nonce="__NONCE__">
(function () {
  var PREFIX = "__PREFIX__";
  var form = document.getElementById("f"), btn = document.getElementById("go");
  var statusEl = document.getElementById("status"), out = document.getElementById("result");
  function para(text, cls) { var p = document.createElement("p"); p.textContent = text; if (cls) p.className = cls; return p; }
  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var title = document.getElementById("title").value.trim();
    if (!title) return;
    btn.disabled = true; out.replaceChildren(); statusEl.textContent = "Working... this usually takes 15-60 seconds.";
    var started = Date.now(), ctrl = new AbortController(), timer = setTimeout(function () { ctrl.abort(); }, 300000);
    try {
      var r = await fetch("api/sru-url", { method: "POST", credentials: "same-origin", signal: ctrl.signal,
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title }) });
      var data = null; try { data = await r.json(); } catch (e) { data = null; }
      if (!data) { out.append(para("Your sign-in may have expired. Reload the page and try again.", "error")); return; }
      if (!r.ok) { out.append(para(data.error || ("Request failed (HTTP " + r.status + ")."), "error")); return; }
      var urls = (data.urls || []).filter(function (u) { return typeof u === "string" && u.indexOf(PREFIX) === 0; });
      if (urls.length) {
        urls.forEach(function (u) {
          var a = document.createElement("a"); a.href = u; a.textContent = u; a.className = "url";
          a.target = "_blank"; a.rel = "noopener noreferrer"; out.append(a);
          var c = document.createElement("button"); c.type = "button"; c.textContent = "Copy URL";
          c.addEventListener("click", function () { navigator.clipboard.writeText(u).then(function () { c.textContent = "Copied"; }); });
          out.append(c);
        });
      } else {
        out.append(para(data.text || "No SRU URL in the reply. Try again, or use the SQL function."));
      }
    } catch (e) {
      out.append(para(e && e.name === "AbortError" ? "No reply after 5 minutes. Try again later."
        : "Could not reach the app. Your sign-in may have expired; reload the page and try again.", "error"));
    } finally {
      clearTimeout(timer); btn.disabled = false;
      statusEl.textContent = "Done in " + Math.round((Date.now() - started) / 1000) + " s.";
    }
  });
})();
</script>
</body>
</html>
"""


async def index(request: Request) -> HTMLResponse:
    nonce = secrets.token_urlsafe(16)
    html = (
        PAGE.replace("__NONCE__", nonce).replace("__PREFIX__", SRU_PREFIX).replace("__MAX__", str(MAX_TITLE_CHARS))
    )
    return HTMLResponse(
        html,
        headers={
            # only this page's own inline script and style may run; it may only call this app
            "Content-Security-Policy": (
                f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                "connect-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'"
            ),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        },
    )


async def sru_url_api(request: Request) -> JSONResponse:
    """JSON API behind the page: {"title": "..."} -> {"text": agent reply, "urls": [SRU URLs in it]}."""
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        # also blocks plain cross-site HTML form posts, which cannot send application/json
        return JSONResponse({"error": "Send JSON: {\"title\": \"...\"}"}, status_code=415)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be JSON"}, status_code=400)
    title = body.get("title") if isinstance(body, dict) else None
    if not isinstance(title, str) or not title.strip():
        return JSONResponse({"error": "Body must include 'title' (the correction title)"}, status_code=400)
    if len(title) > MAX_TITLE_CHARS:
        return JSONResponse({"error": f"Title is longer than {MAX_TITLE_CHARS} characters"}, status_code=400)
    try:
        text = await asyncio.to_thread(_call_agent_retry_empty, title.strip())
    except UpstreamError as e:
        log.warning("page_error error_id=%s category=%s status=%s", e.error_id, e.category, e.status_code)
        return JSONResponse({"error": e.client_message()}, status_code=504 if e.category == "timeout" else 502)
    except Exception as e:  # never expose unexpected exception text
        err = UpstreamError("unavailable")
        log.warning("page_error error_id=%s category=unexpected exception=%s", err.error_id, type(e).__name__)
        return JSONResponse({"error": err.client_message()}, status_code=502)
    urls = [u.rstrip(").,;") for u in _SRU_URL_RE.findall(text or "")]
    return JSONResponse({"text": text or EMPTY_MSG, "urls": list(dict.fromkeys(urls))})


app.add_route("/", index, methods=["GET"])
app.add_route("/api/sru-url", sru_url_api, methods=["POST"])
app.add_route("/health", health, methods=["GET"])
app.add_route("/invocations", invocations, methods=["POST"])
app.add_route("/responses", invocations, methods=["POST"])

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
