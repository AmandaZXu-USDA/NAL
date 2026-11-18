# Databricks offline MLflow evaluation: sru-syntax-mcp

Evaluates the SRU syntax agent while it uses the **deployed** `sru-syntax-mcp` MCP server
(a Databricks App), scored by MLflow GenAI judges plus a deterministic URL check. Adapted from
the template kit in [`mcp-hackathon/eval/databricks/`](../../../mcp-hackathon/eval/databricks/README.md).

Each dataset row is an erratum/correction notice title. The agent should return the NAL Alma
production SRU URL for the original article, or no URL when the notice names no single article.

## What's in this kit

| File | What it is |
|------|------------|
| `agent_eval_offline.py` | The eval script. Runs `mlflow.genai.evaluate` over the dataset with a `predict_fn` that calls the agent. |
| `eval_auth.py` | Auth shim. Patches the agent's `ws` client and `mcp_url()` at runtime so it reaches the OAuth-gated app as a service principal. `agent/agent_server/agent.py` stays unmodified. |
| `datasets/sru-eval-0.csv` | 11 rows: one per `extraction_rule` value in the source spreadsheet, including a bare notice (`Correction`) and an issue-level notice. |

Differences from the template:

* **The agent is ours, not Playground-generated.** The script imports `sru-syntax-mcp/agent/agent_server/agent.py`
  (the standalone agent version), so there is no export step and `eval_auth.py` sits next to the script.
* **No copy of `setup-eval-sp.sh`.** Use the template script with this app's names (Step 1).
* **Scorers fit the task:** a deterministic `sru_url_match` is the primary metric; the built-in
  `RelevanceToQuery` is replaced by a domain-aware guideline (it reads "Correction to: <title>" as a
  request to correct the article).
* **No `mlflow.tracing.set_destination(...)`.** The experiment stores traces in Unity Catalog; setting
  an experiment destination bypasses those tables, so assessments are not logged. A SQL warehouse ID
  is set instead, which UC trace reads require.

## Why a service principal is required

The app is OAuth-gated. An offline notebook eval cannot reach it with the notebook's identity: runtime
auth cannot mint an OAuth token, and personal access tokens are rejected. A **service principal using
OAuth M2M** with `CAN_USE` on the app is the identity that works. See the template README for the full
explanation and diagram.

## Step 1 — Provision the service principal (one time)

You must be a workspace admin. From a machine with the Databricks CLI and `jq`, at the repo root:

```bash
bash mcp-hackathon/eval/databricks/setup-eval-sp.sh \
  --app-name sru-syntax-mcp \
  --sp-name sp-sru-syntax-eval \
  --scope sru-syntax-eval-secrets
```

The script creates the SP, grants `workspace-access` and `CAN_USE` on the app, and stores `sp_id` and
`sp_secret` in the secret scope. Minting the OAuth secret is an **account-level** action; if the script
cannot do it, it prints the account console step, then re-run it with `--oauth-secret '<value>'`.

The workspace already has an `sp-mcp-eval` SP and `mcp-eval-secrets` scope, but you cannot read that scope,
so create a dedicated SP for this app.

## Step 2 — Run the eval in a notebook

Open a notebook in this folder (`sru-syntax-mcp/eval/databricks/`).

**Cell 1** (run alone, first):

```python
%pip install "openai-agents>=0.25" "databricks-openai>=0.17" "mlflow[databricks]>=3.14"
%restart_python
```

**Cell 2:** paste the contents of `agent_eval_offline.py` and run it. The `CONFIG` block already
points at this app; each value can also be set with an environment variable:

| Setting | Default | Env var |
|---|---|---|
| `MCP_SERVER_URL` | `https://sru-syntax-mcp-7474654188777746.aws.databricksapps.com/mcp` | `SRU_EVAL_MCP_URL` |
| `MODEL` | `models.ai.gpt-5-6-luna` | `SRU_EVAL_MODEL` |
| `EXPERIMENT_ID` | `131270370350843` (UC-backed SRU agent experiment) | `SRU_EVAL_EXPERIMENT_ID` |
| `SQL_WAREHOUSE_ID` | `50d2bd4ddf65e0f5` (Serverless Starter Warehouse) | `MLFLOW_TRACING_SQL_WAREHOUSE_ID` |
| `SECRET_SCOPE` | `sru-syntax-eval-secrets` | none |
| `AUTH_MODE` | `service_principal` | `SRU_EVAL_AUTH` |

A run takes about 2 to 3 minutes (11 rows, 3 at a time; the Supervisor Agent behind the tool takes about
20 seconds per title). Metrics print at the end; per-row results and traces are in the experiment's
**Evaluations** tab.

### Local dev copy of the server

To evaluate code changes before deploying, run `mcp_server/app.py` locally and point the eval at it with
`SRU_EVAL_MCP_URL=http://127.0.0.1:<port>/mcp` and `SRU_EVAL_AUTH=current_user`. The local server has no
Apps OAuth gate, so the current identity is enough.

## Scorers

| Scorer | Kind | Passes when |
|---|---|---|
| `sru_url_match` | Deterministic (primary) | The reply has an SRU URL on the production base whose decoded `alma.title` equals `expected_title`; or, when `expected_title` is blank, the reply has no SRU URL. |
| `correctness` | LLM judge | The reply contains the row's `expected_facts`. |
| `relevant_to_notice` | LLM guideline | The reply gives the SRU URL for the original article, or explains there is no single article. |
| `no_invented_urls` | LLM guideline | Only tool-produced URLs, no unrelated commentary, and errors are relayed rather than papered over. |
| `safety` | LLM judge | No harmful content. |

Results from a run against a local copy of the server (2026-11-18):

| Metric | Mean |
|---|---|
| `sru_url_match` | 1.00 |
| `correctness` | 0.91 |
| `relevant_to_notice` | 0.91 |
| `no_invented_urls` | 0.82 |
| `safety` | 1.00 |

In the run whose rows were inspected, the bare `Correction` row failed `correctness` and `no_invented_urls`:
the agent asked for the full title instead of calling the tool or saying the notice names no article.
The Supervisor Agent's occasional empty replies would show up as `sru_url_match` failures (none occurred
in these runs).

## Dataset

`datasets/sru-eval-0.csv` columns: `request` (the notice title, sent as-is), `expected_title` (the
`alma.title` term from `users.amanda_xu.build_sru_url`, blank when no URL is expected) and `source_rule`
(the extraction rule, logged as a tag). Rows came from
`Correction-Sample2-1494-Extracted-Titles-FINAL.xlsx`, one per `extraction_rule`.

To add rows, append to the CSV and fill `expected_title` from the UC function:

```sql
SELECT url_decode(regexp_extract(users.amanda_xu.build_sru_url(:title), 'query=(.*)$', 1))
```

If the title rules change, regenerate every `expected_title` the same way.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Service-principal credentials are missing` | The secret scope or keys are missing. Re-run Step 1, or check `SECRET_SCOPE` / `SECRET_KEY_*`. |
| Agent replies without a URL and logs a failed MCP connection, or tool calls return 401/403 | The SP is not reaching the app. Confirm it has `CAN_USE` on `sru-syntax-mcp` and `workspace-access`. |
| `INVALID_PARAMETER_VALUE: sql_warehouse_id is required` | Reading UC-stored traces needs `MLFLOW_TRACING_SQL_WAREHOUSE_ID` set to a warehouse you can use. |
| `no trace tagged with mlflow.eval.requestId was found` and missing assessments | Something set a trace destination other than the UC-backed experiment. Remove `set_destination` calls. |
| A tool error such as `(error unavailable, id ...)` in replies | The server's Supervisor Agent call failed. Search `databricks apps logs sru-syntax-mcp` for the id. |
| `bound to a different event loop` / `Event loop is closed` | Async plumbing. Do not add `nest_asyncio`; the script runs one persistent loop. |
