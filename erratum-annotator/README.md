# erratum-annotator

Matches a correction (erratum) notice in the NAL Alma SRU catalog to its original article and appends an erratum
note to the original title, e.g. `<original title> [Erratum: Aug. 2026, v. 52, no. 4, 134, 10.1007/s10695-026-01767-0]`.
Titles that already carry an `[Erratum: ...]` note are returned unchanged.

## Contents

| Path | Purpose |
| --- | --- |
| `mcp_server/erratum_annotator.py` | Core logic: parse SRU MODS XML, pick the original record, build the erratum note, enhance the title |
| `mcp_server/app.py` | MCP server `mcp-erratum-note` (FastMCP, streamable HTTP at `/mcp`) for Databricks Apps |
| `mcp_server/app.yaml`, `requirements.txt` | Databricks Apps config; `SRU_VOLUME_DIR` points at the saved SRU responses volume |
| `eval/databricks/` | MLflow evaluation of the `agent-erratum-annotator` Supervisor Agent and the [PDF report](https://github.com/AmandaZXu-USDA/NAL/blob/add-mcp-servers/erratum-annotator/eval/databricks/doc/agent-erratum-annotator-evaluation-report.pdf) |

## MCP tools

`health`, `parse_sru_response`, `extract_erratum_note`, `enhance_title`, `process_sru_response`,
`list_sru_files`, `process_sru_file` (reads a saved response from `SRU_VOLUME_DIR`).

## Deploy

Deploy `mcp_server/` as a Databricks App named `mcp-erratum-note`. The app's service principal needs READ VOLUME on
the volume in `SRU_VOLUME_DIR`. The Supervisor Agent `agent-erratum-annotator` uses this MCP app plus the UC
function `users.amanda_xu.process_sru_response`.

The deployed app runs from this repo folder: `/Workspace/Users/amanda.xu@usda.gov/NAL/erratum-annotator/mcp_server`
(snapshot deployment, November 20, 2026). Redeploy after pulling changes:
`databricks apps deploy mcp-erratum-note --source-code-path <repo>/erratum-annotator/mcp_server`.
