# NAL Metadata Support: automating PubAg correction processing

Databricks MCP Hackathon project from the USDA National Agricultural Library (NAL).

Publishers issue correction notices (errata, corrigenda, addenda) for articles indexed in PubAg. Each notice
has its own catalog record, and staff must find the **original article** it corrects. Today that means
reading the notice title, working out the original article title by hand, and searching NAL's Alma catalog.

This project is the initial stage of automating that workflow:

1. **Part 1, spreadsheet processing:** extract the original article title from each correction notice title
   and build an Alma SRU search URL for it.
2. **Part 2, agents, MCP and governance on Databricks:** make the same logic available to people and AI
   agents as a governed Unity Catalog function, a Supervisor Agent and an MCP server, with tracing and
   evaluation.
3. **Part 3, erratum annotation:** from the SRU response, find the original article's record and append an
   erratum note to its title, with a second MCP server and agent ([`erratum-annotator/`](erratum-annotator/README.md)).

## At a glance: two MCP apps, two agents

| | Project 1: SRU syntax (Parts 1 and 2) | Project 2: Erratum annotator (Part 3) |
| --- | --- | --- |
| What it does | Correction notice title -> NAL Alma SRU search URL | SRU response (MODS XML) -> original title with `[Erratum: ...]` note |
| MCP server (Databricks App) | `mcp-sru-syntax`: 1 tool, `build_sru_search_url` | `mcp-erratum-note`: 7 tools, e.g. `list_sru_files`, `process_sru_file` |
| Agent | Supervisor Agent `agent-sru-syntax` (`mas-c8629507-endpoint`); the app also serves an OpenAI Agents SDK agent at `/invocations` | Supervisor Agent `agent-erratum-annotator` (`mas-c341c0aa-endpoint`), [configuration](erratum-annotator/agent/README.md) |
| Deterministic rules | UC function `users.amanda_xu.build_sru_url` | UC function `users.amanda_xu.process_sru_response` |
| Code | [`sru-syntax-mcp/`](sru-syntax-mcp/README.md) | [`erratum-annotator/`](erratum-annotator/README.md) |
| Evaluation | [`sru-syntax-mcp/eval/databricks/`](sru-syntax-mcp/eval/databricks/README.md) | [`erratum-annotator/eval/databricks/`](erratum-annotator/eval/databricks/README.md) |
| Headline result | 135/142 correct replies via MCP, 0 wrong URLs | Agent: 50/53 exact annotated titles; MCP server alone: 0 errors, 48/48 original MMS IDs |
| Deploy | Declarative Automation Bundle `sru_syntax` in `sru-syntax-mcp/` | `databricks apps deploy` from `erratum-annotator/mcp_server` |

Both live apps are deployed from this repository. The hackathon copy for judges,
[`AmandaZXu-USDA/mcp-hackathon-demo-sru`](https://github.com/AmandaZXu-USDA/mcp-hackathon-demo-sru), mirrors
both projects (Project 1 in the GSA template layout, Project 2 byte-identical in `erratum-annotator/`); make
changes here first, then copy them. The deck and both reports are in [`submission/`](submission/README.md).
Safe-deployment rules for each app: [`sru-syntax-mcp/README.md`](sru-syntax-mcp/README.md) and
[`erratum-annotator/README.md`](erratum-annotator/README.md#deploying-safely).

```
Correction notice title (Sample 1, row 43; erratum MMS ID 9917175550407426)
  "Publisher Correction: DNMT3A/TET2-mediated epigenetic alteration in Type-1 diabetes dysregulates the haematopoiesis"
        |
        v  title extraction rules (Part 1)
Original article title
  "DNMT3A/TET2-mediated epigenetic alteration in Type-1 diabetes dysregulates the haematopoiesis"
        |
        v  SRU URL builder (Part 2, mcp-sru-syntax)
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve
  &recordSchema=mods&query=alma.title%3D%22DNMT3A%2FTET2-mediated%20epigenetic%20alteration%20in%20Type-1%20diabetes%20dysregulates%20the%20haematopoiesis%22%20and%20alma.local_field_912%3D%22Article%22
        |
        v  run the SRU search in Alma; save the response (MODS XML) to the volume, or paste it
SRU searchRetrieveResponse (MODS XML): 2 records
  correction notice  9917175550407426
  original article   9917168304707426
        |
        v  erratum annotation (Part 3, mcp-erratum-note)
        |    process_sru_file("Sample1-Row43-9917175550407426.xml")  (or process_sru_response for pasted XML)
        |    1. parse_sru_response    records: title, MMS ID, <part><text>, DOI, is_correction
        |    2. match                 correction record (erratum MMS ID) -> original article
        |                             (cited DOI first, then title similarity; else needs_review)
        |    3. extract_erratum_note  "[Erratum: Dec. 2026, v. 53, no. 1, 1310, 10.1007/s11033-026-12468-5]"
        |    4. enhance_title         append the note; titles that already have "[Erratum:" stay unchanged
        v
Annotated original title (original MMS ID 9917168304707426, needs_review = false)
  "DNMT3A/TET2-mediated epigenetic alteration in Type-1 diabetes dysregulates the haematopoiesis [Erratum: Dec. 2026, v. 53, no. 1, 1310, 10.1007/s11033-026-12468-5]"
```

## Repository layout

| Folder | What it is |
| --- | --- |
| [`title-extraction/`](title-extraction/README.md) | Part 1: `erratum_title_extractor.py`, the spreadsheet processing script. |
| [`sru-syntax-mcp/`](sru-syntax-mcp/README.md) | Part 2: MCP server and agent (Databricks App), UC function `build_sru_url` (`uc_functions/`), bundle config, agent skill, offline evaluation. Tools and functions: [`deploy/databricks/README.md`](sru-syntax-mcp/deploy/databricks/README.md#tools-and-functions). |
| [`erratum-annotator/`](erratum-annotator/README.md) | Part 3: MCP server `mcp-erratum-note`, UC functions (`uc_functions/`), agent `agent-erratum-annotator` configuration, evaluation, Inspector Gadget test and report. Tools and functions: [`README.md`](erratum-annotator/README.md#mcp-tools). |
| [`submission/`](submission/README.md) | Hackathon deck, both evaluation reports and the librarian quick-start (same files as the hackathon repo). |
| [`mcp-hackathon/`](mcp-hackathon/README.md) | The GSA MCP Hackathon server template this project started from (FastMCP, deploy kits, eval templates). |

## Part 1: Spreadsheet processing

**Input:** an Alma export of correction notice records. The main sample,
`Correction-Sample2-1494-20261021.xlsx`, has 1,494 records with `Title` and `MMS ID` columns.

**Code:** [`title-extraction/erratum_title_extractor.py`](title-extraction/README.md)
(`python erratum_title_extractor.py INPUT.xlsx`; needs `pandas` and `openpyxl`).

**Output:** the same records with these columns, as a downloadable Excel workbook:

| Column | Name | Contents |
| --- | --- | --- |
| A | `erratumn_article_title` | Correction notice title, as exported |
| B | `extracted_title` | Original article title after the extraction rules |
| C | `erratum_MMSID` | MMS ID of the correction notice record |
| D | `extracted_title_clean` | Extracted title after normalisation (dashes, quotes, spaces) |
| E | `SRU_Query_Syntax` | CQL query: `alma.title="<title>" and alma.local_field_912="Article"` |
| F | `SRU_Full_URL` | Full SRU searchRetrieve URL |
| G | `extraction_rule` | QA column: which rule produced the title |

The column name `erratumn_article_title` is kept as-is for compatibility with existing files.

### Title extraction rules

The rules were built up iteratively on real notices:

1. Remove notice prefixes such as `Correction:`, `Correction to:` and `Publisher Correction:`.
2. Parse the embedded article title out of bibliographic `Corrigendum:` and `Corrigenda:` notices of the form
   `Corrigendum: Author1, Author2, ... (2026) Original article title. Journal Title 123: 45-67. https://doi.org/...`.
   Remove the prefix, author list, year, journal title, volume/issue/page information and DOI, and keep only
   the original article title.
3. Handle the other notice patterns found in the data: quoted titles, cited authors
   (`Correction for Kuo and Chang, <title>`), quoted full citations, trailing citations
   (`... by Lee et al. Journal 2024;27(6):488-501; doi: ...`), notice suffixes (`<title>/Correction`), and
   titles with no notice wording.
4. Leave the title blank, so no URL is built, when the notice names no single article: bare notices
   (`Correction`, `ERRATA`) and issue-level notices (`Taxon 61(6)`, `Correction for Data Papers Published in 2020`).
5. Guard against false positives: a real title such as `Correction of hypocalcemia in dairy cows` is kept.

**Journal-agnostic corrigendum parsing.** Corrigendum citations use many journal names and formats. Instead of
listing journals, the extractor takes the text immediately after the year `(YYYY)` and cuts it at the first
journal citation segment, so it also works for journals that are not in the sample.

The full rule table, with an example and rule name for each case, is in
[`sru-syntax-mcp/.agents/skills/agent-sru-syntax/references/sru_url_rules.md`](sru-syntax-mcp/.agents/skills/agent-sru-syntax/references/sru_url_rules.md).

### SRU URL format

```
https://nal.alma.exlibrisgroup.com/view/sru/01NAL_INST?version=1.2&operation=searchRetrieve&recordSchema=mods
  &query=alma.title%3D%22<title>%22%20and%20alma.local_field_912%3D%22Article%22
```

* Production Alma (`nal.alma...`). The sandbox (`nal-psb.alma...`) does not hold the production records.
* The whole query is percent-encoded (spaces as `%20`, not `+`); there is no `maximumRecords` parameter.
* `"` and `\` inside a title are replaced with spaces so they cannot end the CQL quoted term.

### Results on the 1,494-record sample

* 1,384 records get an SRU URL; 110 are bare or issue-level notices with no single article, so no URL is built.
* The Unity Catalog function (below) reproduces the extractor's output for all 1,494 records.
* A URL that returns a valid SRU response with 0 records means the article was not found in Alma, not a
  syntax problem.

## Part 2: Agents, MCP and governance on Databricks

### Components

| Component | What it does |
| --- | --- |
| Unity Catalog function `users.amanda_xu.build_sru_url(correction_title)` | Python UDF with the Part 1 rules. Deterministic; the source of truth for SRU URLs. Use it for bulk processing in SQL. |
| Supervisor Agent `agent-sru-syntax` (endpoint `mas-c8629507-endpoint`) | Agent Bricks agent that calls the function as a tool. |
| Databricks App `mcp-sru-syntax` | Custom MCP server with one read-only tool, `build_sru_search_url`, that runs the function on a SQL warehouse first (about 4 s) and asks the Supervisor Agent only if that call fails. The same app serves an OpenAI Agents SDK agent at `/invocations` that uses the tool. See [`sru-syntax-mcp/README.md`](sru-syntax-mcp/README.md). |
| Agent skill `agent-sru-syntax` | Instructions and rules for coding agents working on this project ([`SKILL.md`](sru-syntax-mcp/.agents/skills/agent-sru-syntax/SKILL.md)). |
| Offline evaluation | MLflow GenAI evaluation over 41 labelled notices ([`sru-syntax-mcp/eval/databricks/`](sru-syntax-mcp/eval/databricks/README.md)). |

For bulk work, call the function from SQL. The MCP tool and the browser page answer in about 4 seconds
per title (live test 2026-11-21: 3.9-4.7 s), because they run the function first; the Supervisor Agent
(about 20 seconds per title) is only the fallback. Either way they suit interactive use rather than
thousands of rows.

### Two ways to reach the logic over MCP

**1. Databricks-managed MCP server for Unity Catalog functions (no hosting).** Databricks exposes Unity
Catalog functions as MCP tools at:

* `https://<workspace-host>/api/2.0/mcp/functions/{catalog}/{schema}`: every function in the schema
* `https://<workspace-host>/api/2.0/mcp/functions/{catalog}/{schema}/{function_name}`: one function

A workspace admin must enable Managed MCP Servers on the workspace Previews page. Clients request the
`unity-catalog` OAuth scope.

From a Databricks notebook, using `DatabricksMCPClient` from the `databricks-mcp` package:

```python
%pip install databricks-mcp nest_asyncio
```

```python
import nest_asyncio
nest_asyncio.apply()  # the client runs asyncio internally; this lets it run inside the notebook's event loop

from databricks.sdk import WorkspaceClient
from databricks_mcp import DatabricksMCPClient

ws = WorkspaceClient()  # authenticated as the notebook user
server_url = f"{ws.config.host}/api/2.0/mcp/functions/users/amanda_xu/build_sru_url"
client = DatabricksMCPClient(server_url=server_url, workspace_client=ws)

print([t.name for t in client.list_tools()])  # ['users__amanda_xu__build_sru_url']
result = client.call_tool(
    "users__amanda_xu__build_sru_url",
    {"correction_title": "Correction: Lorazepam reduces recurrence of urethral obstruction in male cats"},
)
print(result.content[0].text)  # JSON with the SRU URL in rows[0][0]
```

Tool names are the function's full name with `__` in place of dots. The schema-level URL also lists
`build_sru_url_v1`, an older version, so use the function-level URL to expose only the current function.
The first call can time out while the function warms up; retry once.

**2. Custom MCP server on Databricks Apps (`mcp-sru-syntax`).** Managed MCP has no endpoint for
Supervisor Agents, so the app wraps the agent in an MCP tool:
`https://mcp-sru-syntax-7474654188777746.aws.databricksapps.com/mcp`. Databricks Apps require an OAuth token;
personal access tokens are rejected.

### Governance

* **Unity Catalog permissions.** Callers need `USE CATALOG`, `USE SCHEMA` and `EXECUTE` on the function. The
  app's service principal gets only the resources declared in the bundle: `CAN_QUERY` on the Supervisor Agent
  endpoint, `EXECUTE` on the model service, `CAN_EDIT` on the experiment and `MODIFY` on the trace tables.
* **Deployment as code.** The app, its resources and permissions are defined in a Declarative Automation
  Bundle ([`sru-syntax-mcp/databricks.yml`](sru-syntax-mcp/databricks.yml)).
* **Tracing in Unity Catalog.** MLflow traces every agent, model and tool call into
  `users.amanda_xu.sru_syntax_agent_otel_*` tables, so traces are governed and queryable like any other table.
* **Safe tool behaviour.** The MCP tool is annotated read-only and idempotent, and returns stable error
  categories (`invalid_input`, `timeout`, `unavailable`, `rate_limited`, `permission_denied`, `not_found`,
  `bad_request`, `bad_response`, `empty_reply`, `internal`) with an error ID instead of upstream error bodies.
  An empty reply, a busy agent or a temporary outage is retried once; an empty reply after the retry returns
  `empty_reply`, which points to the SQL function for that title.
* **Evaluation.** An offline MLflow evaluation checks URLs deterministically against the Unity Catalog
  function, plus LLM judges for correctness, relevance, safety and "no invented URLs".

## Status and next steps

* Done: extraction rules, Unity Catalog function, Supervisor Agent, MCP server app, Unity Catalog tracing,
  offline evaluation.
* Known issue: the Supervisor Agent sometimes returns an empty reply for a title (3 of 41 eval rows). Use the
  function directly for those titles.
* Next: run the SRU searches against Alma to retrieve the original article's MMS ID and link it to the
  correction record; provision the evaluation service principal so the eval can run against the deployed app.
