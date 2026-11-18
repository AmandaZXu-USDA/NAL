"""HTTP server for the SRU syntax agent on Databricks Apps.

Endpoints:
  POST /invocations and POST /responses  - OpenAI Responses-style request: {"input": [...] or "text"}
  GET  /health                           - liveness check
"""
import os
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from agent_server.agent import run_agent

app = FastAPI(title="sru-syntax-agent")


class ResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    input: list[dict[str, Any]] | str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/invocations")
@app.post("/responses")
async def invocations(request: ResponsesRequest) -> dict:
    try:
        text = await run_agent(request.input)
    except Exception as e:  # surface agent/MCP failures as a 502 with a short message
        raise HTTPException(status_code=502, detail=f"Agent error: {e}"[:1000])
    return {
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


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("DATABRICKS_APP_PORT", "8000")))


if __name__ == "__main__":
    main()
