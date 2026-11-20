# agent-erratum-annotator: Databricks evaluation

Offline MLflow evaluation of the `agent-erratum-annotator` Supervisor Agent (endpoint `mas-c341c0aa-endpoint`,
tools: MCP app `mcp-erratum-note` and UC function `users.amanda_xu.process_sru_response`) on the 53-row,
librarian-checked Sample1 spreadsheet.

**Report (PDF):** [agent-erratum-annotator-evaluation-report.pdf on GitHub](https://github.com/AmandaZXu-USDA/NAL/blob/add-mcp-servers/erratum-annotator/eval/databricks/doc/agent-erratum-annotator-evaluation-report.pdf)
(use the download icon at the top right of the preview). The same file is in this folder at
`doc/agent-erratum-annotator-evaluation-report.pdf` and in the Databricks volume at
`/Volumes/users/amanda_xu/erratum_files/reports/agent-erratum-annotator-evaluation-report.pdf`
(Catalog Explorer, then Download).

## Results (November 20, 2026)

| Scorer | Result |
| --- | --- |
| annotated_title_exact (primary) | 50/53 |
| erratum_note_exact | 52/53 |
| original_mms_id_match (rows with an original) | 45/46 |
| called_tool (rows with an SRU file) | 48/48 |
| correctness (LLM judge) | 50/53 |
| no_fabrication (LLM guideline) | 37/53, 10 of 16 failures are judge errors |

Failures: row 28 hit the Supervisor Agent's 290 s limit; rows 34 and 40 retyped a curly apostrophe in the title.
Notices with no saved SRU response get a request for SRU XML instead of a manual-review / no-original answer.

## Contents

| Item | Purpose |
| --- | --- |
| `Erratum Annotator Agent Evaluation` | Dataset, scorers with self-check, predict function, smoke test, full run, failure analysis, rescore, per-row export |
| `Erratum Annotator Evaluation Report` | Builds and verifies the PDF from the per-row export |
| `doc/agent-erratum-annotator-eval-results-20261120.csv` | Per-row scores, latency, tools, rationales and replies |
| `doc/agent-erratum-annotator-eval-runs-20261120.json` | MLflow experiment and run IDs |

The notebooks read and write paths under `/Workspace/Users/amanda.xu@usda.gov/erratum-annotator/eval`; edit
`RESULTS_DIR` / `DOC` to run them from this folder.
