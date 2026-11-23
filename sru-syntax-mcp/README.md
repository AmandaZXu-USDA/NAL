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

## Playground demo: both MCP apps on one correction notice

Judges can repeat this demo in the Databricks **AI Playground**. Both prompts use the same correction notice:
MMS ID `9917175652607426` (Sample 1, row 42). Its title has a Unicode hyphen (U+2010) in "Climate‐driven".
Paste each prompt as written. Both were checked on November 23, 2026: each reply matched the ground truth in
`Correction-Sample1-53-annotated.csv`.

| Step | App | Playground pane (serving endpoint) | Tool called | Time |
| --- | --- | --- | --- | --- |
| 1 | `mcp-sru-syntax` | `agent-sru-syntax` (`mas-c8629507-endpoint`) | `users__amanda_xu__build_sru_url` | 50 s |
| 2 | `mcp-erratum-note` | `agent-erratum-annotator` (`mas-c341c0aa-endpoint`) | `process_sru_file` (MCP) | 13 s |

**Prompt 1 (`mcp-sru-syntax`, build the SRU search URL):**

```text
Build the Alma SRU search URL for correction notice MMS ID 9917175652607426. Correction notice title: Correction to: Climate‐driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture
```

Expected: the reply gives this URL (it matches the ground-truth `sru_url` character for character):

```text
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22Climate-driven%20insect%20pest%20outbreaks%20and%20food%20security%20risks%3A%20a%20review%20of%20adaptive%20strategies%20for%20resilient%20agriculture%22%20and%20alma.local_field_912%3D%22Article%22
```

**Prompt 2 (`mcp-erratum-note`, annotate the original title from the saved SRU response):**

```text
Annotate the original article for correction notice MMS ID 9917175652607426. Correction notice title: Correction to: Climate‐driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture. The saved SRU response file is Sample1-Row42-9917175652607426.xml. Return the annotated original title, the erratum note, the original MMS ID, and whether it needs manual review.
```

Expected:

* Annotated title: `Climate-driven insect pest outbreaks and food security risks: a review of adaptive strategies for resilient agriculture [Erratum: Sept. 2026, v. 99, no. 3, 111, 10.1007/s10340-026-02069-3]`
* Original MMS ID: `9917015258907426`
* Needs manual review: No

**Second example (video demo): MMS ID `9917175553207426` (Sample 1, row 45).** Checked on November 23, 2026 with the same two
panes side by side. Its title has an en dash in "flour–epoxy": step 1 changes it to a plain hyphen for the SRU URL, and step 2 keeps the en dash in the annotated title.

| Step | Tool called | Time | Result |
| --- | --- | --- | --- |
| 1 | `users__amanda_xu__build_sru_url` | 39 s | URL matches the ground-truth `sru_url` exactly |
| 2 | `process_sru_file` (MCP) | 13 s | Annotated title and original MMS ID match the ground truth; no manual review |

Prompt 1:

```text
Build the Alma SRU search URL for correction notice MMS ID 9917175553207426. Correction notice title: Correction: Optimization of material and extrusion parameters for wood flour–epoxy composites with potential additive-manufacturing applications in construction
```

Expected URL:

```text
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods&query=alma.title%3D%22Optimization%20of%20material%20and%20extrusion%20parameters%20for%20wood%20flour-epoxy%20composites%20with%20potential%20additive-manufacturing%20applications%20in%20construction%22%20and%20alma.local_field_912%3D%22Article%22
```

Prompt 2:

```text
Annotate the original article for correction notice MMS ID 9917175553207426. Correction notice title: Correction: Optimization of material and extrusion parameters for wood flour–epoxy composites with potential additive-manufacturing applications in construction. The saved SRU response file is Sample1-Row45-9917175553207426.xml. Return the annotated original title, the erratum note, the original MMS ID, and whether it needs manual review.
```

Expected:

* Annotated title: `Optimization of material and extrusion parameters for wood flour–epoxy composites with potential additive-manufacturing applications in construction [Erratum: Aug. 2026, v. 84, no. 4, 103, 10.1007/s00107-026-02464-8]`
* Original MMS ID: `9917046021407426`
* Needs manual review: No

Notes:

* The two steps run in order. Prompt 1 gives the SRU URL. The librarian runs that URL in Alma and saves the response.
  For this notice the response is already saved as
  `/Volumes/users/amanda_xu/erratum_files/sru_responses/Sample1-Row42-9917175652607426.xml`. Prompt 2 reads that file.
* In pane 2, approve the `mcp-erratum-note` tool call when the Playground asks. The reply arrives after approval.
* Pane 1 talks to `agent-sru-syntax`, the Supervisor Agent behind the `mcp-sru-syntax` tool `build_sru_search_url`. It calls the same rules function
  (`users.amanda_xu.build_sru_url`) that the tool calls first. To call the MCP app itself, open a model pane, choose
  **Tools > MCP servers > Databricks Apps**, add `mcp-sru-syntax` (and `mcp-erratum-note` for step 2), then send the same prompt.

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
