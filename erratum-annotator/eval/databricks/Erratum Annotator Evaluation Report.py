# Databricks notebook source
# DBTITLE 1,Install PDF libraries
# MAGIC %pip install -q reportlab pypdf "mlflow[databricks]>=3.4"
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# DBTITLE 1,Load evaluation results
import json
import pandas as pd

DOC = "/Workspace/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/doc"
RESULTS_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261122-uc.csv"  # run with traces in Unity Catalog
PREV_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261121.csv"  # November 21 run, for comparison
BASE_CSV = f"{DOC}/agent-erratum-annotator-eval-results-20261122.csv"  # same day, same scorers, no agent trace returned
RUNS_JSON = f"{DOC}/agent-erratum-annotator-eval-runs-20261122-uc.json"
OUTPUT_PATH = f"{DOC}/agent-erratum-annotator-evaluation-report.pdf"
RUN_DATE = "November 22, 2026"
SRU_DIR = "/Volumes/users/amanda_xu/erratum_files/sru_responses"
import os
n_saved = len([f for f in os.listdir(SRU_DIR) if f.endswith(".xml")])
base = pd.read_csv(BASE_CSV, keep_default_na=False)

r = pd.read_csv(RESULTS_CSV, keep_default_na=False)
BOOL = ["truncated", "annotated_title_exact", "erratum_note_exact", "original_mms_id_match", "called_tool",
        "correctness", "no_fabrication"]
TOOL_COL = "tool_annotated_title_exact"  # added November 21, 2026; not in the November 20 export
for c in BOOL + [TOOL_COL]:
    r[c] = r[c].astype(str) == "True"
runs = json.load(open(RUNS_JSON))
prev = pd.read_csv(PREV_CSV, keep_default_na=False)
for c in BOOL:
    prev[c] = prev[c].astype(str) == "True"

# Direct MCP server test as the Inspector Gadget service principal (notebook "mcp-erratum-note Inspector Gadget Test")
IG_CSV = f"{DOC}/mcp-erratum-note-inspector-test-20261121.csv"
ig = pd.read_csv(IG_CSV, keep_default_na=False)
for c in ["is_error", "title_ok", "mms_ok", "needs_review"]:
    ig[c] = ig[c].astype(str) == "True"
print(len(ig), "Inspector Gadget rows, run", ig["run_ts"].iloc[0])

N = len(r)
has_original = r["case"].isin(["annotated", "already_annotated"])  # rows with an expected original MMS ID
has_file = ~r["case"].isin(["manual_review", "no_file_no_original"])  # rows with a saved SRU response


def count(col, mask=None):
    mask = pd.Series(True, index=r.index) if mask is None else mask
    return int(r.loc[mask, col].sum()), int(mask.sum())


M = {
    "annotated_title_exact": count("annotated_title_exact"),
    "erratum_note_exact": count("erratum_note_exact"),
    "original_mms_id_match": count("original_mms_id_match", has_original),
    "called_tool": count("called_tool", has_file),
    TOOL_COL: count(TOOL_COL),
    "correctness": count("correctness"),
    "no_fabrication": count("no_fabrication"),
}
lat = r["latency_s"]
print(N, "rows", runs)
for k, (a, b) in M.items():
    print(f"{k:25s} {a}/{b}")
print(r["case"].value_counts().to_dict())

# Trace statistics: the full run's traces, read from Unity Catalog with the MLflow SDK (not from the tables directly).
import mlflow
import numpy as np
os.environ.setdefault("MLFLOW_TRACING_SQL_WAREHOUSE_ID", "50d2bd4ddf65e0f5")
TRACE_TABLES = "users.amanda_xu.agent_erratum_eval_otel_*"
traces = mlflow.search_traces(locations=[runs["experiment_id"]], run_id=runs["full_run_id"], max_results=500,
                              return_type="list")
assert len(traces) == N, f"expected {N} traces, got {len(traces)}"
t_lat = np.array([t.info.execution_duration for t in traces]) / 1000
t_tok = [t.info.token_usage or {} for t in traces]
t_in = np.array([x.get("input_tokens", 0) for x in t_tok]); t_out = np.array([x.get("output_tokens", 0) for x in t_tok])
t_tools = [s for t in traces for s in t.data.spans if s.span_type == "TOOL"]
t_llm = [s for t in traces for s in t.data.spans if s.span_type == "CHAT_MODEL"]
t_tool_ms = np.array([(s.end_time_ns - s.start_time_ns) / 1e6 for s in t_tools])
t_llm_s = np.array([(s.end_time_ns - s.start_time_ns) / 1e9 for s in t_llm])
t_tool_err = sum(s.status.status_code.value == "ERROR" for s in t_tools)
t_states = pd.Series([t.info.state.value for t in traces]).value_counts().to_dict()
t_tool_names = pd.Series([s.name for s in t_tools]).value_counts().to_dict()
pct = lambda a, q: float(np.percentile(a, q))
print(len(traces), "traces", t_states, "tools", t_tool_names, "errors", t_tool_err, "LLM spans", len(t_llm),
      "tokens", int(t_in.sum()), int(t_out.sum()))

# COMMAND ----------

# DBTITLE 1,Build evaluation report PDF
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#1B3139"))
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#1B3139"))
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9.5, leading=12.5, spaceAfter=4)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8.5, leading=10.5, spaceAfter=0)
CELL_B = ParagraphStyle("CellB", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
CODE = ParagraphStyle("Code", parent=CELL, fontName="Courier", fontSize=7.5, leading=9.5)


def p(text, style=BODY):
    return Paragraph(text, style)


def bullets(items):
    return [p("&bull;&nbsp;" + i) for i in items]


def table(rows, widths, code_cols=()):
    data = [[Paragraph(escape(str(c)), CELL_B) for c in rows[0]]]
    for row in rows[1:]:
        data.append([Paragraph(escape(str(c)), CODE if j in code_cols else CELL) for j, c in enumerate(row)])
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B3139")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F7")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


frac = lambda k: f"{M[k][0]}/{M[k][1]} ({M[k][0] / M[k][1]:.0%})"
rows_of = lambda mask: sorted(r.loc[mask, "row_num"].tolist())

# Explanations of every failing row, from reading the replies and judge rationales of this run.
# The asserts stop the build if a rerun produces a different set of failures.
DET_FAIL = {
    34: "Erratum note correct, but the agent replaced the curly apostrophe (U+2019) in the catalog title with a straight one; the tool's annotated_title was exact.",
    40: "Erratum note correct, but the agent replaced the curly apostrophe (U+2019) in the catalog title with a straight one; the tool's annotated_title was exact.",
}
assert set(rows_of(~r.annotated_title_exact | ~r.erratum_note_exact | ~r.original_mms_id_match)) == set(DET_FAIL), \
    "Deterministic failures changed: update DET_FAIL"
CORR_FAIL = {
    4: "Judge error: the reply says Alma has only the correction notice and gives no annotated title, as expected; the judge "
       "failed it because the reply does not also say that it gives no search_title fallback.",
}
assert set(rows_of(~r.correctness)) == set(CORR_FAIL), "Correctness failures changed: update CORR_FAIL"
FAB_GROUPS = [
    ("Judge error: treats the original article's MMS ID as invented because it differs from the correction notice's MMS ID "
     "or is not in the request. It comes from process_sru_file (original_id) and matches the ground truth.",
     [8, 42, 43, 44, 51, 52, 53]),
    ("Judge error: objects that the reply names the article (taken from the correction notice title in the request) while "
     "saying no annotated title can be produced. No annotation is given, as expected.", [39]),
]
assert sorted(sum((g for _, g in FAB_GROUPS), [])) == rows_of(~r.no_fabrication), "no_fabrication failures changed"
assert r.loc[r.row_num.isin(FAB_GROUPS[0][1]), "original_mms_id_match"].all()
n_fab = int((~r.no_fabrication).sum())
NO_FILE = rows_of(~has_file)
assert (r.loc[~has_file, "tools"] == "").all(), "a no-file row called a tool"
MANUAL_ROWS = rows_of(r.case == "manual_review"); NO_ORIG_ROWS = rows_of(r.case == "no_file_no_original")
reply41 = r.loc[r.row_num == 41, "reply"].iloc[0]
assert r.loc[r.row_num == 41, ["annotated_title_exact", "erratum_note_exact"]].all(axis=None)
assert "mycokeys.124.171105" in reply41 and "mycokeys.134.198487" in reply41

story = []
story += [p("agent-erratum-annotator: Evaluation Report", ParagraphStyle("T", parent=H1, fontSize=18)),
          p(f"NAL erratum annotation agent. Offline MLflow evaluation run on {RUN_DATE}.", SMALL), Spacer(1, 6)]

# 1. Summary
story += [p("1. Summary", H1),
          p(f"The agent was evaluated on all {N} rows of the librarian-checked Sample1 spreadsheet, with row 41 now "
            "expecting two erratum notes (two corrections of one original). It returned the exact annotated original title "
            f"on {frac('annotated_title_exact')} rows, including row 41, and the correct original MMS ID on "
            f"{frac('original_mms_id_match')} rows that have one. It used a saved-response tool on every row with an SRU "
            f"file ({frac('called_tool')}). Both exact-match failures (rows 34 and 40) come from a limitation of the "
            "Supervisor Agent: it cannot output the curly apostrophe (U+2019) and writes a straight one. The tool result "
            f"the reply is built from has the exact catalog title on every row ({frac(TOOL_COL)}, "
            "tool_annotated_title_exact). There were no endpoint errors or unfinished approval loops. "
            f"None of the {len(NO_FILE)} notices with no saved SRU response called a tool or asked for SRU XML. "
            f"All {n_fab} no_fabrication failures and the one correctness failure are judge errors."),
          p(f"This run stores its traces in Unity Catalog ({TRACE_TABLES}) and attaches the agent's own trace to each "
            f"request, so tool calls, LLM calls and token usage are measured (section 6): {len(t_tools)} tool calls with "
            f"{t_tool_err} errors, and {int(t_in.sum() + t_out.sum()):,} tokens for the {N} requests."),
          table([["Scorer", "Kind", "Rows scored", "Result"],
                 ["annotated_title_exact (primary)", "Deterministic", "all rows", frac("annotated_title_exact")],
                 ["erratum_note_exact", "Deterministic", "all rows", frac("erratum_note_exact")],
                 ["original_mms_id_match", "Deterministic", "rows with an original", frac("original_mms_id_match")],
                 ["called_tool", "Deterministic", "rows with an SRU file", frac("called_tool")],
                 ["tool_annotated_title_exact", "Deterministic", "all rows", frac(TOOL_COL)],
                 ["correctness", "LLM judge", "all rows", frac("correctness")],
                 ["no_fabrication", "LLM guideline", "all rows", frac("no_fabrication")]],
                [2.3, 1.2, 1.6, 1.4])]

# 2. System under test
story += [p("2. System under test", H1),
          table([["Component", "Value"],
                 ["Agent", "agent-erratum-annotator (Agent Bricks Supervisor Agent)"],
                 ["Endpoint", runs["endpoint"]],
                 ["Tools", "MCP app mcp-erratum-note (process_sru_file, list_sru_files, ...; calls need approval); "
                           "UC function users.amanda_xu.process_sru_response"],
                 ["Saved SRU responses", f"/Volumes/users/amanda_xu/erratum_files/sru_responses ({n_saved} MODS XML files; the 48 Sample 1 files are in this evaluation)"],
                 ["Output format", "<original title> [Erratum: Mon. YYYY, v. V, no. N, page, DOI]; already-annotated titles unchanged"]],
                [1.6, 4.9])]

# 3. Dataset
case_counts = r["case"].value_counts()
CASE_DESC = {
    "annotated": "Original found in the SRU response; note appended",
    "already_annotated": "Original title already carries an [Erratum: ...] note; must be returned unchanged",
    "manual_review": "Generic 'Correction' title, no SRU file; needs manual review",
    "file_but_no_original": "SRU file holds only the correction; no annotation expected (no search-title fallback)",
    "no_file_no_original": "No SRU file and no original in Alma; no annotation expected",
}
story += [p("3. Evaluation dataset", H1),
          p("Ground truth: /Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv. Each request gives "
            "the correction notice title, the erratum MMS ID and, when saved, the SRU response file name, e.g. "
            "<i>Annotate the original article title for the correction notice \"Correction: ...\" (erratum MMS ID "
            "9916524607707426). The saved SRU response file is Sample1-Row1-9916524607707426.xml.</i>"),
          table([["Case", "Rows", "Meaning"]] + [[c, int(case_counts.get(c, 0)), d] for c, d in CASE_DESC.items()],
                [1.6, 0.6, 4.3])]

# 4. Method
story += [p("4. Method", H1),
          *bullets([
              "mlflow.genai.evaluate with a predict function that calls the endpoint through the Responses API and "
              "auto-approves each mcp_approval_request (up to 8 rounds, 300 s client timeout, 2 retries). Only the final "
              "round's text is scored; all text and tool calls are kept for diagnosis.",
              "Traces are stored in Unity Catalog: the experiment is bound to " + TRACE_TABLES + ". Each request asks "
              "the endpoint to return its own trace (databricks_options.return_trace) and attaches it with "
              "mlflow.add_trace, which adds the agent's LLM spans (with token usage) and TOOL spans.",
              "Deterministic scorers compare after removing markdown escapes, bold and backticks and collapsing "
              "whitespace. Hyphens and quote characters are not normalized, because the catalog title must be exact.",
              "annotated_title_exact: the expected title appears exactly and no other note is attached to a title. "
              "erratum_note_exact: the set of notes attached to the title equals the expected notes (one, or two for "
              "row 41). Notes restated after a label (e.g. under Details) and placeholders such as [Erratum: ...] in "
              "prose are ignored.",
              "Before any agent call, a self-check scores the ground truth itself (must pass), plus corrupted notes, "
              "doubled notes and markdown-formatted titles (46/46 each), and regression cases from earlier runs.",
              "A 3-row smoke test (rows 4, 41, 43) preceded the full run (up to 3 parallel workers).",
          ]),
          p("Scorer revisions", H2),
          *bullets([
              "November 20, smoke test: the first scorers counted notes, so a correct reply that restated its note in a "
              "Details list failed (0/3). Changed to count only notes attached to a title.",
              "November 20, full run: 2 replies wrote '[Erratum: ...]' as a placeholder in a status sentence, and 9 "
              "already-annotated replies listed the new correction's note under Details. Both were scored as extra "
              "notes. Fixed and rescored from the saved replies without calling the agent: title 48 to 50/53, note 40 "
              "to 52/53.",
              "November 22: the expected note became every note in the expected title, compared as a set, so a reply "
              "with only one of row 41's two notes fails.",
          ])]

# 5. Results
by_case = r.groupby("case").agg(rows=("row_num", "size"), title=("annotated_title_exact", "sum"),
                                note=("erratum_note_exact", "sum"), correct=("correctness", "sum"),
                                lat=("latency_s", "median")).reindex(list(CASE_DESC))
story += [p("5. Results", H1), p("5.1 By case", H2),
          table([["Case", "Rows", "Title exact", "Note exact", "Correctness", "Median latency"]] +
                [[c, int(x.rows), f"{int(x.title)}/{int(x.rows)}", f"{int(x.note)}/{int(x.rows)}",
                  f"{int(x.correct)}/{int(x.rows)}", f"{x.lat:.1f} s"] for c, x in by_case.iterrows()],
                [1.7, 0.6, 0.9, 0.9, 1.0, 1.1]),
          p("5.2 Deterministic failures", H2),
          table([["Row", "Case", "What happened"]] +
                [[n, r.loc[r.row_num == n, "case"].iloc[0], t] for n, t in sorted(DET_FAIL.items())], [0.5, 1.4, 4.6]),
          p("5.3 LLM judges", H2),
          p(f"<b>correctness</b> {frac('correctness')}. Failing rows:"),
          table([["Row", "Case", "Reason"]] +
                [[n, r.loc[r.row_num == n, "case"].iloc[0], t] for n, t in sorted(CORR_FAIL.items())], [0.5, 1.4, 4.6]),
          Spacer(1, 6),
          p(f"<b>no_fabrication</b> {frac('no_fabrication')}. Reading the {n_fab} rationales: all are judge errors. The "
            "deterministic scorers found no invented title, note or MMS ID."),
          table([["Group", "Rows"]] + [[g, ", ".join(map(str, rows))] for g, rows in FAB_GROUPS], [5.0, 1.5]),
          p("Rows 6, 9, 16, 19 and 39 pass the deterministic scorers only because they give no annotation; the "
            "deterministic scorers do not check that the reply explains why.", SMALL),
          p("5.4 Compared with earlier runs", H2),
          table([["Scorer", "November 21", "November 22, no agent trace", "November 22, traces in UC"]] +
                [[k] + [f"{int(d.loc[m(d), k].astype(str).eq('True').sum())}/{int(m(d).sum())}" for d in (prev, base, r)]
                 for k, m in [("annotated_title_exact", lambda d: d.index == d.index),
                              ("erratum_note_exact", lambda d: d.index == d.index),
                              ("original_mms_id_match", lambda d: d["case"].isin(["annotated", "already_annotated"])),
                              ("called_tool", lambda d: ~d["case"].isin(["manual_review", "no_file_no_original"])),
                              ("correctness", lambda d: d.index == d.index),
                              ("no_fabrication", lambda d: d.index == d.index)]] +
                [["Median latency"] + [f"{d.latency_s.median():.1f} s" for d in (prev, base, r)]],
                [2.0, 1.4, 1.6, 1.5]),
          p("The November 21 run was scored against the ground truth before row 41's change (one expected note); "
            "both November 22 runs use the updated ground truth. Between November 21 and 22, mcp-erratum-note returns "
            "a blank annotated_title when the response has no original or no correction record.", SMALL)]

# 6. Latency and tool use
tools = r["tools"].replace("", "(none)").value_counts()
story += [p("6. Latency, tool calls and token usage", H1),
          p(f"From the {len(traces)} full-run traces in Unity Catalog (states: "
            + ", ".join(f"{k} {v}" for k, v in t_states.items()) + ") and the per-row results.", SMALL),
          table([["Measure", "Value"],
                 [f"Per-request latency ({N} rows)", f"p50 {pct(t_lat, 50):.1f} s, p90 {pct(t_lat, 90):.1f} s, "
                                                  f"p95 {pct(t_lat, 95):.1f} s, p99 {pct(t_lat, 99):.1f} s, max {t_lat.max():.1f} s"],
                 ["Rows with an SRU file", f"median {r.loc[has_file, 'latency_s'].median():.1f} s (one tool call, one approval)"],
                 ["Rows without an SRU file", f"median {r.loc[~has_file, 'latency_s'].median():.1f} s (no tool call)"],
                 ["Slowest row", f"row {int(r.loc[lat.idxmax(), 'row_num'])}: {lat.max():.1f} s (reply correct)"],
                 ["Endpoint errors / truncated loops", f"{int((r.error != '').sum())} / {int(r.truncated.sum())}"],
                 ["Tool calls (TOOL spans)", ", ".join(f"{k} {v}" for k, v in t_tool_names.items())
                  + f"; {t_tool_err} errors; p50 {pct(t_tool_ms, 50):.0f} ms, p95 {pct(t_tool_ms, 95):.0f} ms, "
                    f"max {t_tool_ms.max():.0f} ms"],
                 ["LLM calls (CHAT_MODEL spans)", f"{len(t_llm)}, about {len(t_llm) / len(traces):.1f} per request; "
                                                  f"p50 {pct(t_llm_s, 50):.1f} s, p95 {pct(t_llm_s, 95):.1f} s"],
                 ["Input tokens per request", f"median {int(np.median(t_in)):,}, mean {int(t_in.mean()):,}, max {int(t_in.max()):,}"],
                 ["Output tokens per request", f"median {int(np.median(t_out)):,}, mean {int(t_out.mean()):,}, max {int(t_out.max()):,}"],
                 ["Tokens, whole run", f"{int(t_in.sum()):,} input + {int(t_out.sum()):,} output = {int(t_in.sum() + t_out.sum()):,}"]] +
                [[f"Rows by tool used: {k}", f"{v} rows"] for k, v in tools.items()],
                [2.4, 4.1]),
          p(f"Median latency was {lat.median():.1f} s, against {base.latency_s.median():.1f} s in the same day's run "
            "that did not ask the endpoint to return its trace. Returning the trace may add time; this was not "
            "measured separately.", SMALL)]

# 7. Findings and recommendations
story += [p("7. Findings and recommendations", H1),
          *bullets([
              "<b>Take the catalog title from the tool result, not the reply.</b> The Supervisor Agent cannot output the "
              "curly apostrophe U+2019: given d\u2019I in a plain message, it reports the character as U+0027. A stronger "
              "instruction (worked example, character check, title in a code block) gave 0 of 6 exact on rows 34 and 40, "
              "so it was reverted. The tool's annotated_title is exact on all rows; librarians should copy it from the "
              "tool result, and tool_annotated_title_exact scores it.",
              "<b>Two corrections in one original work end to end.</b> Row 41's reply carries both notes in date order "
              "and passes both exact scorers.",
              f"<b>No SRU file.</b> None of the {len(NO_FILE)} no-file replies calls a tool or asks for XML. Rows "
              + ", ".join(map(str, MANUAL_ROWS)) + " say the notice needs manual review; rows "
              + " and ".join(map(str, NO_ORIG_ROWS)) + ", whose requests pass on the librarian's Alma search result, "
              "say the original is not in Alma.",
              f"<b>Watch latency and cost.</b> p95 {pct(t_lat, 95):.1f} s, max {t_lat.max():.1f} s, no timeouts. Each "
              f"request uses about {int(np.median(t_in)):,} input tokens, mostly the agent's instructions and context; "
              "the experiment's overview now tracks this over time.",
              f"<b>Replace or ground the no_fabrication judge.</b> All {n_fab} of its failures here are judge errors "
              "(11 on November 21). Either pass the tool outputs to the judge as context, or use a deterministic check "
              "that every MMS ID and DOI in the reply appears in a tool output.",
              "<b>Validate scorers on real replies.</b> Synthetic self-checks passed, but real replies restated notes "
              "and used placeholders. Keep the smoke test and the regression cases.",
              f"<b>Grow the dataset.</b> {n_saved} SRU responses are saved, including 25 from Sample 4 (row 4: two "
              "corrections in one original; row 25: only the original in Alma). Add them once they have librarian-checked "
              "titles, and Sample3 (142 rows) once its SRU responses are saved.",
          ])]

# 8. MCP server test (Inspector Gadget)
ig_diff = sorted(ig.loc[ig.is_error | ~ig.title_ok | ~ig.mms_ok, "row_num"].tolist())
assert ig_diff == [4, 24], f"Inspector Gadget differences changed: {ig_diff}"
assert not ig.loc[ig.row_num.isin(ig_diff), "needs_review"].any()
ig_frac = lambda col: f"{int(ig[col].sum())}/{len(ig)}"
story += [p("8. MCP server test (Inspector Gadget)", H1),
          p(f"The MCP server was also tested directly, without the agent, on {ig['run_ts'].iloc[0].replace('T', ' ')} "
            "UTC. A test client signed in as the Inspector Gadget service principal (OAuth M2M, CAN_USE on the app), "
            f"listed the 7 tools, called list_sru_files and then process_sru_file on each of the {len(ig)} saved SRU "
            "responses, and compared annotated_title and original_id with the ground truth. Each run is appended to "
            "the table users.amanda_xu.erratum_mcp_inspector_test."),
          table([["Check", "Result"],
                 ["Tools listed", "7: health, parse_sru_response, extract_erratum_note, enhance_title, "
                                  "process_sru_response, list_sru_files, process_sru_file"],
                 ["Tool errors", f"{int(ig.is_error.sum())}/{len(ig)}"],
                 ["annotated_title exact", ig_frac("title_ok")],
                 ["original MMS ID match", ig_frac("mms_ok")],
                 ["Latency per process_sru_file call",
                  f"median {ig.latency_sec.median():.2f} s, max {ig.latency_sec.max():.2f} s"]],
                [2.0, 4.5]),
          p("Rows 4 and 24 are the only differences. Alma has no original for them, so the ground-truth title is "
            "blank. The tool correctly returns no original_id, but it still builds an annotated title from the search "
            "title and sets needs_review to false. Recommendation: when no original is found, return no annotated_title "
            "or set needs_review to true. Done November 22, 2026: annotated_title is now blank when no original is found (section 10)."),
          p("The tool answers in under a second, so nearly all of the agent's per-request time (section 6) is spent "
            "in the Supervisor Agent, not in the MCP server.")]

# 9. Artifacts
story += [p("9. Artifacts and reproduction", H1),
          table([["Item", "Location"],
                 ["Evaluation notebook", "/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/Erratum Annotator Agent Evaluation"],
                 ["Report notebook", "/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/Erratum Annotator Evaluation Report"],
                 ["MLflow experiment", f"{runs['experiment']} (id {runs['experiment_id']})"],
                 ["Full run", runs["full_run_id"]], ["Rescore run", runs["rescore_run_id"]],
                 ["Smoke run", runs["smoke_run_id"]],
                 ["Per-row results", RESULTS_CSV],
                 ["Inspector Gadget test notebook",
                  "/Users/amanda.xu@usda.gov/NAL/erratum-annotator/eval/databricks/mcp-erratum-note Inspector Gadget Test"],
                 ["Inspector Gadget results", IG_CSV]],
                [1.5, 5.0], code_cols=(1,)),
          Spacer(1, 4),
          p("To reproduce: run the evaluation notebook top to bottom (cells 2 to 4 need no agent calls), then this "
            "notebook. The rescore cell reapplies the deterministic scorers to saved replies.", SMALL)]

# 10. Changes since the November 21 run (computed from the current code and files)
import importlib.util
_ANN = "/Workspace/Users/amanda.xu@usda.gov/NAL/erratum-annotator/mcp_server/erratum_annotator.py"
_spec = importlib.util.spec_from_file_location("erratum_annotator_now", _ANN)
ea_now = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(ea_now)
GT_CSV = "/Volumes/users/amanda_xu/erratum_files/Correction-Sample1-53-annotated.csv"
_xml = lambda f: open(f"{SRU_DIR}/{f}", encoding="utf-8-sig").read()
TWO = [("Sample 4, row 4", "Sample4-Row4-9917012079207426-TwoCorrectionsInOneOriginalTitle.xml", "9917012079207426"),
       ("Sample 1, row 41", "Sample1-Row41-9917175655407426.xml", "9917175655407426")]
two = {lab: ea_now.process_sru_response(_xml(f), "", cid) for lab, f, cid in TWO}
assert all(len(v["erratum_notes"]) == 2 for v in two.values()), "two-note rule changed"
gt_now = pd.read_csv(GT_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
_strip = lambda s: s[2:-1] if s.startswith('="') else s
now_ok, now_diff, now_n = 0, [], 0
for _, g in gt_now.iterrows():
    _cid = _strip(g.erratum_mms_id); _f = f"Sample1-Row{g.row_num}-{_cid}.xml"
    if not os.path.exists(f"{SRU_DIR}/{_f}"):
        continue
    now_n += 1
    if ea_now.process_sru_response(_xml(_f), "", _cid)["annotated_title"] == g.annotated_title:
        now_ok += 1
    else:
        now_diff.append(int(g.row_num))
assert now_diff == [], f"tool vs updated ground truth changed: {now_diff}"
assert gt_now.loc[gt_now.row_num == "41", "annotated_title"].item() == two["Sample 1, row 41"]["annotated_title"]
_r25 = ea_now.process_sru_response(_xml("Sample4-Row25-9917162397207426-OnlyOriginalTitle.xml"), "", "9917162397207426")
assert _r25["annotated_title"] == "" and _r25["num_corrections"] == 0
story += [p("10. Changes since the November 21 run", H1),
          p("<b>Two corrections in one original title.</b> New rule from the project owner: when an SRU response holds "
            "two or more correction records of one original article, every correction's erratum note goes into the single "
            "original title, ordered by date (year, month, day), then volume, issue and page. Two saved responses have "
            "this case:"),
          table([["Notice", "Notes appended, in order"]] +
                [[lab, "  ".join(v["erratum_notes"])] for lab, v in two.items()], [1.3, 5.2], code_cols=(1,)),
          Spacer(1, 4),
          *bullets([
              "<b>Ground truth changed for row 41.</b> Its expected annotated title in Correction-Sample1-53-annotated "
              "now carries both notes (Nov. 13, 2025, then June 18, 2026). The previous files are kept as "
              "Correction-Sample1-53-annotated-before-20261122.csv and .xlsx. In this run the agent's row 41 reply "
              "has both notes and passes.",
              "<b>Blank annotated_title when nothing can be annotated.</b> If the response has no original record "
              "(Sample 1 rows 4 and 24) or no correction record (Sample 4 row 25: only the original is in Alma, status "
              "no_correction, with a manual-review warning), annotated_title is blank. This is the fix recommended in "
              "section 8.",
              f"<b>Tool check against the updated ground truth.</b> process_sru_response, run now on the {now_n} Sample1 "
              f"rows with a saved response, gives the expected annotated title on {now_ok}/{now_n}.",
              f"<b>Saved responses.</b> {n_saved} files: 48 from Sample 1, Sample 2 rows 3 and 14, and 25 from Sample 4 "
              "(rows 2 to 30 except 16, 19, 20 and 22, which have no SRU response and need manual review).",
              "<b>Traces in Unity Catalog.</b> The evaluation now writes to the experiment "
              f"{runs['experiment']} (id {runs['experiment_id']}), bound to {TRACE_TABLES}. The earlier experiment keeps "
              "the November 20 to 22 runs.",
          ])]


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(0.75 * inch, 0.5 * inch, f"agent-erratum-annotator evaluation report, {RUN_DATE}")
    canvas.drawRightString(7.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


SimpleDocTemplate(OUTPUT_PATH, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                  topMargin=0.7 * inch, bottomMargin=0.75 * inch,
                  title="agent-erratum-annotator evaluation report").build(story, onFirstPage=_footer, onLaterPages=_footer)
print("Saved", OUTPUT_PATH)

# COMMAND ----------

# DBTITLE 1,Verify report PDF
import os
from pypdf import PdfReader

reader = PdfReader(OUTPUT_PATH)
flat = " ".join(" ".join(page.extract_text() for page in reader.pages).split())
print(f"{os.path.getsize(OUTPUT_PATH):,} bytes, {len(reader.pages)} pages")
checks = ["1. Summary", "2. System under test", "3. Evaluation dataset", "4. Method", "5. Results",
          "6. Latency, tool calls and token usage", "7. Findings and recommendations",
          "8. MCP server test (Inspector Gadget)", "9. Artifacts and reproduction", "erratum_mcp_inspector_test",
          ig_frac("title_ok"), ig_frac("mms_ok"),
          frac("annotated_title_exact"), frac("erratum_note_exact"), frac("original_mms_id_match"), frac("called_tool"),
          frac("correctness"), frac("no_fabrication"), runs["full_run_id"], runs["rescore_run_id"], runs["experiment_id"],
          runs["endpoint"], "U+2019", "48 to 50/53", "40 to 52/53", f"max {t_lat.max():.1f} s",
          "5.4 Compared with earlier runs", RUN_DATE, "tool_annotated_title_exact", "U+0027",
          "10. Changes since the November 21 run", "10.1007/s00018-025-05953-w", "10.3897/mycokeys.124.171105",
          f"{now_ok}/{now_n}", "before-20261122", "agent_erratum_eval_otel", f"{int(t_in.sum() + t_out.sum()):,}",
          f"{len(t_tools)} tool calls", "no_correction"]
missing = [c for c in checks if c not in flat]
for c in checks:
    print("OK  " if c not in missing else "MISSING  ", c)
assert not missing, missing