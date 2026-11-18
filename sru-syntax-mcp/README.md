# sru-syntax-mcp

Converts erratum/correction notice titles into NAL Alma production SRU search URLs for the original article.

This folder is a Declarative Automation Bundle with two Databricks Apps and one MLflow experiment:

| Resource | Source | What it does |
| --- | --- | --- |
| `sru-syntax-mcp` app | `app.py`, `app.yaml`, `requirements.txt` | MCP server (streamable HTTP at `/mcp`) with one tool, `build_sru_search_url`, that calls the agent-sru-syntax Supervisor Agent endpoint `mas-c8629507-endpoint` |
| `sru-syntax-agent` app | `agent/` | OpenAI Agents SDK agent that uses the MCP server's tool; serves `POST /invocations` and `POST /responses` |
| `sru-syntax-agent-experiment` | `databricks.yml` | MLflow experiment that receives the agent's traces |

## Layout

```
sru-syntax-mcp/
  databricks.yml                     bundle: apps, experiment, variables
  app.py, app.yaml, requirements.txt MCP server app
  agent/
    app.yaml                         env from app resources; runs `uv run start-server`
    pyproject.toml                   dependencies + start-server entry point
    agent_server/agent.py            agent, MCP connection, MLflow tracing
    agent_server/start_server.py     FastAPI server
  setup/create_uc_backed_experiment.py  optional: experiment with traces in Unity Catalog
```

## App resources

The agent app gets these through `valueFrom` in `agent/app.yaml`:

* `model-service` -> `MODEL_SERVICE`: Unity Gateway model service (default `models.ai.gpt-5-6-luna`), `EXECUTE`
* `app-experiment` -> `MLFLOW_EXPERIMENT_ID`: bundle experiment, `CAN_EDIT`
* `mcp-server-app` -> `MCP_SERVER_APP`: the MCP server app, `CAN_USE` (the agent resolves its URL and appends `/mcp`)

The MCP server app gets `serving-endpoint` -> `SERVING_ENDPOINT` with `CAN_QUERY`.

## Deploy

Run from this folder (the bundle root):

```bash
databricks bundle validate --strict -t dev

# One time: the sru-syntax-mcp app already exists, so let the bundle manage it
databricks bundle deployment bind sru_syntax_mcp sru-syntax-mcp -t dev

databricks bundle deploy -t dev
databricks bundle run sru_syntax_mcp -t dev
databricks bundle run sru_syntax_agent -t dev
```

Override any variable with `--var`, for example `--var model_service=models.ai.gpt-5-6-sol`.

## Test the agent

```bash
curl -X POST "<AGENT_APP_URL>/invocations" \
  -H "Authorization: Bearer <OAUTH_TOKEN>" -H "Content-Type: application/json" \
  -d '{"input": [{"role": "user", "content": "Correction: <article title>"}]}'
```

Apps require an OAuth token (`databricks auth token`); personal access tokens are not accepted.
Each title can take 60-90 seconds because the Supervisor Agent does the lookup.

## Tracing

`mlflow.openai.autolog()` traces every model and MCP tool call automatically. `run_agent` adds an
`AGENT` span plus a `preprocessing` child span. To keep traces in Unity Catalog
(`users.amanda_xu`), run `setup/create_uc_backed_experiment.py` once and point the agent app's
`app-experiment` resource at the printed experiment ID.
