# sru-syntax-mcp

Converts erratum/correction notice titles into NAL Alma production SRU search URLs for the original article.

**Librarians:** see [`LIBRARIAN_QUICKSTART.md`](LIBRARIAN_QUICKSTART.md) for the four ways to get a URL
from a title (Supervisor Agent chat, Genie Code with the MCP tool, the app's agent endpoint, and the
`build_sru_url` SQL function for lists), with the access each needs.

This folder is a Declarative Automation Bundle with one Databricks App and one MLflow experiment.
The workspace is at its 100-app limit, so the MCP server and the agent share the `mcp-sru-syntax` app:

| Endpoint | Code | What it does |
| --- | --- | --- |
| `/mcp` | `mcp_server/app.py` | MCP server (streamable HTTP) with one tool, `build_sru_search_url`: runs `users.amanda_xu.build_sru_url` on a SQL warehouse first (about 4 s) and falls back to the agent-sru-syntax Supervisor Agent endpoint `mas-c8629507-endpoint` |
| `POST /invocations`, `POST /responses` | `mcp_server/agent.py` | OpenAI Agents SDK agent that uses the `/mcp` tool over localhost |
| `GET /health` | `mcp_server/app.py` | Liveness check |

Agent traces go to the experiment `/Users/amanda.xu@usda.gov/sru-syntax-agent-uc-experiment`
(ID `131270370350843`), which stores them in Unity Catalog tables `users.amanda_xu.sru_syntax_agent_*`.

## Layout

```
sru-syntax-mcp/
  databricks.yml                     bundle: app, experiment, variables
  mcp_server/                        the deployed app
    app.py                           MCP server + agent HTTP routes
    agent.py                         agent, local MCP connection, MLflow tracing
    app.yaml, requirements.txt       env from app resources; dependencies
  uc_functions/build_sru_url.sql     the UC function the tool runs (tools and functions: deploy/databricks/README.md)
  agent/                             standalone agent app version (not deployed; use if app capacity frees up)
  setup/create_uc_backed_experiment.py  optional: experiment with traces in Unity Catalog
```

## App resources

The app gets these through `valueFrom` in `mcp_server/app.yaml`:

* `serving-endpoint` -> `SERVING_ENDPOINT`: Supervisor Agent endpoint, `CAN_QUERY`
* `model-service` -> `MODEL_SERVICE`: Unity Gateway model service (default `models.ai.gpt-5-6-luna`), `EXECUTE`
* `app-experiment` -> `MLFLOW_EXPERIMENT_ID`: Unity Catalog-backed experiment (`var.trace_experiment_id`), `CAN_EDIT`
* `trace-annotations`, `trace-logs`, `trace-metrics`, `trace-spans`: the four `users.amanda_xu.sru_syntax_agent_otel_*` tables, `MODIFY` (includes `SELECT`)

## Deploy

The live `mcp-sru-syntax` app is deployed from the `prod` target of the bundle in
AmandaZXu-USDA/mcp-hackathon-demo-sru, not from this folder. Since 2026-11-22 this bundle
does not manage the app (it was unbound), so only one bundle can change it. To ship a
change: edit `mcp_server/` here, copy it with `scripts/sync_to_fork.py`, then in the
hackathon repo run `databricks bundle validate --strict -t prod`,
`databricks bundle deploy -t prod` and `databricks bundle run sru_syntax_mcp -t prod`
(see its `deploy/databricks/README.md`).

Do not bind `sru_syntax_mcp` here again, and do not `bundle deploy` this bundle: with no
binding it would try to create a second `mcp-sru-syntax` app and fail (the name is taken
and the workspace is at its 100-app limit). `databricks bundle validate --strict -t dev`
is still a useful check of the app definition.

## Test the agent

```bash
curl -X POST "https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/invocations" \
  -H "Authorization: Bearer <OAUTH_TOKEN>" -H "Content-Type: application/json" \
  -d '{"input": [{"role": "user", "content": "Correction: <article title>"}]}'
```

Apps require an OAuth token (`databricks auth token`); personal access tokens are not accepted.
The tool itself answers in about 4 seconds (SQL function first); with the agent's own model calls a title
takes about 7-10 seconds (live test 2026-11-21: 6.6-10.1 s), and a bare or issue-level notice about 1 second.
The agent uses the Databricks-hosted model endpoint `databricks-gpt-5-6-luna` (`AGENT_MODEL` in `app.yaml`).

## Tracing

`mlflow.openai.autolog()` traces every model and MCP tool call automatically. `run_agent` adds an
`AGENT` span plus a `preprocessing` child span.

Traces are stored in Unity Catalog under `users.amanda_xu`:

* `sru_syntax_agent_otel_spans`, `_otel_logs`, `_otel_metrics`, `_otel_annotations` (tables)
* `sru_syntax_agent_trace_unified`, `sru_syntax_agent_trace_metadata` (views)

`setup/create_uc_backed_experiment.py` created the experiment and tables (already run once). To use a
different location, run it with new names and set `trace_experiment_id` / `trace_table_prefix` in
`databricks.yml`. The original workspace-backed `sru-syntax-agent-experiment` is kept for its earlier trace.
