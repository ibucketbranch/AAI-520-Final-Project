#!/usr/bin/env python3
"""Build the light and full final notebooks from one list of sections.

The full notebook has every cell. The light notebook is the same notebook
without the cells tagged "full-only" (the "Code for this section" cells and
the appendix), so the two versions cannot drift apart.

Usage:
    python scripts/build_final_notebooks.py build
        Write both notebooks to notebooks/final/ with no outputs.
    python scripts/build_final_notebooks.py light-from-full
        After running the full notebook, make the light one from it, so both
        keep the same saved outputs.

Section 8 (conclusions) depends on the results, so it is written by hand in
the executed notebook after the final run, and so is section 9 (each
author's AI disclosure). "build" keeps both when it rebuilds.
"""

import argparse
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

FINAL_DIR = Path(__file__).resolve().parents[1] / "notebooks" / "final"
FULL_PATH = FINAL_DIR / "AAI520_Group7_Final_Full.ipynb"
LIGHT_PATH = FINAL_DIR / "AAI520_Group7_Final_Light.ipynb"

LIGHT = "light"
FULL = "full"


def full_only_cell(text):
    """A code cell that only the full notebook keeps."""
    cell = new_code_cell(text)
    cell.metadata["tags"] = ["full-only"]
    return cell


# Sections we write by hand in the notebook itself. A rebuild keeps them.
CONCLUSIONS = "## 8. Conclusions"
DISCLOSURES = "## 9. AI tool disclosures"


def _hand_written(notebook):
    """Return {heading: text} for the hand-written sections of a notebook."""
    sections = {}
    for cell in notebook.cells:
        if cell.cell_type != "markdown":
            continue
        for heading in (CONCLUSIONS, DISCLOSURES):
            if cell.source.startswith(heading):
                sections[heading] = cell.source
    return sections


def saved_sections():
    """Return the hand-written sections from the current full notebook that differ from the defaults."""
    if not FULL_PATH.exists():
        return {}
    defaults = _hand_written(build(FULL))
    current = _hand_written(nbformat.read(FULL_PATH, as_version=4))
    return {heading: text for heading, text in current.items() if text != defaults.get(heading)}


def build(kind, kept=None):
    """Return the full or light notebook, with no outputs."""
    kept = kept or {}
    cells = []

    def md(text):
        cells.append(new_markdown_cell(text.strip()))

    def code(text):
        cells.append(new_code_cell(text.strip()))

    def source(text, names):
        # Only the full notebook prints the source code.
        if kind != FULL:
            return
        md("**Code for this section.** " + text.strip())
        code(f"show_code({', '.join(names)})")
        cells[-1].metadata["tags"] = ["full-only"]
        cells[-2].metadata["tags"] = ["full-only"]

    # ------------------------------------------------------------------ intro
    if kind == FULL:
        version_note = (
            "This is the **full** version. It has the same steps as the light version, and "
            "after each section it also prints the actual source code of the functions that "
            "just ran (read straight from the package with `inspect`, so it always matches what "
            "ran). You can follow every step without opening GitHub."
        )
    else:
        version_note = (
            "This is the **light** version. It calls the functions in our package and explains "
            "the results. The code itself lives in `src/investment_committee/` in the repository. "
            "A full version of this notebook prints that code inline after every section."
        )

    md(f"""
# AI Investment Committee

**AAI-520 Final Team Project, Group 7:** Michael Valderrama, Guna Pasupathy, Mina Habib

**Repository:** https://github.com/ibucketbranch/AAI-520-Final-Project

Our project is a small "investment committee" made of AI agents. You give it a stock symbol. A planner decides what to research, three tools collect earnings, news, and market data, a Bull analyst and a Bear analyst argue from that evidence, an evaluator checks every claim against the evidence it cites, and the committee writes a short memo with a verdict. A memory note from each run is read by the planner on the next run.

This is a class project to show agent design and workflow patterns. **It is not financial advice.**

{version_note}

**How to run it**

1. From the repo root: `pip install -r requirements.txt` (or `make setup`). The setup cell adds `src/` to Python's path, so the package works even if you skip `pip install -e .`.
2. Optional: copy `.env.example` to `.env` and add `OPENAI_API_KEY` (and `NEWSAPI_KEY` for news). Without keys everything still runs: the planner, analysts, and evaluator fall back to their rule-based versions.
3. `LIVE = True` (below) uses real market and news data, so it needs internet. `LIVE = False` uses the small sample files in `tests/fixtures/`.

The outputs saved in this notebook come from one live run with an OpenAI key. Live data and model answers change from run to run, so a re-run will show different numbers.
""")

    # ----------------------------------------------------------- section 1
    md("""
## 1. Agent design and workflows

The committee has one job: give a short, evidence-backed opinion on a stock, and be honest about what it could not check.

```
 stock symbol
      |
   Planner  <-------------- memory note from the last run
      |
      +--> earnings tool --------------------+
      +--> news tool --> news chain --> gate +--> evidence pool (SQLite)
      +--> market tool ----------------------+          |
                                              +---------+---------+
                                              |                   |
                                          Bull analyst       Bear analyst
                                              |                   |
                                              +----> Evaluator <--+
                                                    |    |
                                  unsupported claims    supported claims
                                  go back with reason        |
                                                          Verdict + memo
                                                             |
                                                      memory note saved

```
*ChatGPT was used for formatting this text diagram*

**The agents**

| Agent | What it does |
|---|---|
| Planner | Picks which sources to research and in what order. Reads the last run's memory note. |
| Tools (earnings, news, market) | Collect real data with yfinance and NewsAPI and turn it into `Evidence` records. |
| Bull and Bear analysts | Each writes 2 to 5 claims for its side. Every claim must cite evidence ids from the pool. |
| Evaluator | Checks each claim against the evidence it cites and gives a reason when a claim is not supported. |
| Chair (verdict) | Reads only the supported claims and picks bull, bear, or none. |

**The three workflow patterns** (from Anthropic, 2024)

1. **Prompt chaining:** the news chain runs ingest, preprocess, classify, gate, extract, and summarize, one step after another (section 3).
2. **Routing:** each planned step is sent to its own specialist tool (section 2).
3. **Evaluator-optimizer:** the analysts write claims, the evaluator judges them, and rejected claims go back to be rewritten (section 5).

**Design choices we made on purpose**

- **Everything cites evidence.** A claim without a valid evidence id is rejected, so the memo can always be traced back to data.
- **Every agent has a fallback.** No API key, a failed call, or a bad model answer drops back to a rule-based version and the run records why. A broken data source does not stop the run.
- **One database as the handoff.** Each stage reads the previous stage's results from SQLite by run id. This is also what makes the with/without-review experiment fair (section 7).
""")

    # ----------------------------------------------------------- setup
    md("""
## Setup

This cell finds the repo folder, makes the package in `src/` importable, checks that the spaCy English model is installed (the news chain needs it for named entities), and loads the API keys from `.env` if there is one. It also starts a fresh database file just for this notebook.
""")

    code("""
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pandas as pd
import spacy
from IPython.display import display

# Find the repo root (the folder with pyproject.toml), so paths work from any folder.
ROOT = Path.cwd()
while not (ROOT / "pyproject.toml").exists() and ROOT != ROOT.parent:
    ROOT = ROOT.parent

# Use the package straight from src/, so this works even without "pip install -e .".
sys.path.insert(0, str(ROOT / "src"))

# The news chain uses spaCy's small English model. Download it once if it is missing.
# If the download fails (no internet), use a blank pipeline: the chain still runs,
# it just finds no named entities.
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    try:
        subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"], check=True)
        nlp = spacy.load("en_core_web_sm")
    except (subprocess.CalledProcessError, OSError):
        print("Could not get the spaCy model, so entity extraction will find nothing.")
        nlp = spacy.blank("en")

from investment_committee.config import load_settings

settings = load_settings(str(ROOT / ".env"))
HAVE_OPENAI = bool(settings.values.get("OPENAI_API_KEY"))
HAVE_NEWSAPI = bool(settings.values.get("NEWSAPI_KEY"))

LIVE = True

# "openai" uses the models; "template" is the rule-based fallback used without a key.
PROVIDER = "openai" if HAVE_OPENAI else "template"

# A fresh database just for this notebook, so old runs do not mix in.
DB_PATH = ROOT / "data" / "final_notebook.db"
DB_PATH.parent.mkdir(exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()

print("Repo folder:     ", ROOT.name)
print("Live data:       ", LIVE)
print("OpenAI key found:", HAVE_OPENAI, "->", PROVIDER)
print("NewsAPI key found:", HAVE_NEWSAPI)
""")

    code('''
import inspect

from investment_committee.workflows.chaining import clean_text

pd.set_option("display.max_colwidth", 200)


def plain(value):
    """Make text plain ASCII for display (news and model text can have curly quotes)."""
    if isinstance(value, str):
        return "\\n".join(clean_text(line) for line in value.splitlines())
    return value


def table(rows):
    """Show a list of dicts as a table, with plain text."""
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.map(plain)
    return frame


def show_code(*functions):
    """Print the real source code of package functions, with the file name."""
    for function in functions:
        path = inspect.getsourcefile(function)
        short = path.split("src/")[-1] if "src/" in path else path
        lines, start = inspect.getsourcelines(function)
        print(f"# ---- {short}, line {start}")
        print("".join(lines))
''')

    code('''
import json

from investment_committee.models import Evidence
from investment_committee.tools.earnings import gather_earnings
from investment_committee.tools.market import gather_market
from investment_committee.tools.news import gather_news
from investment_committee.workflows.chaining import RawArticle, processed_to_evidence, run_chain

SAMPLE_EVIDENCE = json.loads((ROOT / "tests/fixtures/sample_evidence.json").read_text())
SAMPLE_ARTICLES = json.loads((ROOT / "tests/fixtures/sample_articles.json").read_text())


def sample_gatherer(source):
    """Offline stand-in for a tool: the sample evidence rows for one source."""

    def gather(run):
        rows = []
        for item in SAMPLE_EVIDENCE["evidence"]:
            if item["source"] == source:
                rows.append(
                    Evidence(
                        run_id=run.run_id,
                        symbol=run.symbol,
                        source=source,
                        title=item["title"],
                        content=item["content"],
                        as_of=item["as_of"],
                        reference="sample data",
                    )
                )
        return rows

    return gather


def sample_news(run):
    """Offline stand-in for the news tool: the saved sample articles for this stock."""
    articles = []
    for item in SAMPLE_ARTICLES:
        if item["symbol"] == run.symbol:
            articles.append(RawArticle(**item))
    return articles


def chained_news(run):
    """News tool plus the news chain, so news comes back as Evidence."""
    articles = gather_news(run) if LIVE else sample_news(run)
    return processed_to_evidence(run, run_chain(articles, nlp))


if LIVE:
    TOOLS = {"earnings": gather_earnings, "news": chained_news, "market": gather_market}
else:
    TOOLS = {
        "earnings": sample_gatherer("earnings"),
        "news": chained_news,
        "market": sample_gatherer("market"),
    }
''')

    # ----------------------------------------------------------- section 2
    md("""
## 2. Planner and dynamic tool use

**Rubric items:** the agent plans its research steps, uses tools dynamically, and routes work to specialists.

### 2.1 The planner makes a plan

We have two planners. The rule-based one always gives the same three steps in a fixed order. The OpenAI planner asks a model to choose one to three sources and explain why. The model's answer has to fit a fixed format (a list of steps, each with a source and a reason), so a bad answer is rejected instead of breaking the run. If there is no key or the call fails, it falls back to the rule-based plan and records why.
""")

    code("""
from investment_committee.agents.planner import plan_research
from investment_committee.models import Run

SYMBOL = "AAPL"


def plan_table(plan):
    rows = []
    for number, task in enumerate(plan.tasks, start=1):
        rows.append({"step": number, "source": task.source, "reason": task.reason})
    return table(rows)


demo_run = Run(symbol=SYMBOL)
rules = plan_research(SYMBOL, demo_run.run_id, provider="rules")
print("Rule-based plan:")
display(plan_table(rules.plan))

model_plan = plan_research(SYMBOL, demo_run.run_id, provider="openai", settings=settings)
print("Planner asked for:", model_plan.provider_requested, "| used:", model_plan.provider_used)
if model_plan.fallback_reason:
    print("Fell back because:", model_plan.fallback_reason)
if model_plan.model_call:
    call = model_plan.model_call
    print("Model:", call.model, "| tokens in/out:", call.prompt_tokens, "/", call.completion_tokens)
plan_table(model_plan.plan)
""")

    md("""
The plan also reacts to memory. If the last run for a stock left a note saying a source was missing, that source moves to the front. Here we hand the planner a pretend note. Section 6 does this for real, with a note written by an actual run.
""")

    code("""
from investment_committee.models import MemoryNote

pretend_note = MemoryNote(
    run_id="earlier-run",
    symbol=SYMBOL,
    confidence=0.4,
    open_gaps=["no news evidence in the pool"],
    lesson="Check the news first next time.",
)
with_note = plan_research(SYMBOL, demo_run.run_id, provider="rules", previous_note=pretend_note)
plan_table(with_note.plan)
""")

    source(
        "The planner: `plan_research` picks the provider and falls back, `build_plan` is the "
        "rule-based plan that moves a gap's source to the front, and `_build_openai_plan` is the "
        "model call with the fixed answer format.",
        ["plan_research", "build_plan", "_build_openai_plan"],
    )
    if kind == FULL:
        cells.insert(
            len(cells) - 1,
            full_only_cell(
                "from investment_committee.agents.planner import (\n"
                "    _build_openai_plan,\n    build_plan,\n)"
            ),
        )

    md("""
### 2.2 Routing: each step goes to its own tool

The router has a simple map from source to tool. To show that it follows the plan, we give it a plan with only a market step and record which tools get called. Only the market tool should run.
""")

    code("""
from investment_committee.agents.planner import ResearchPlan, ResearchTask
from investment_committee.workflows.routing import default_gatherers, route_plan

for source, tool in default_gatherers().items():
    print(f"{source:9} -> {tool.__module__}.{tool.__name__}")

called = []


def record_calls(source, tool):
    def gather(run):
        called.append(source)
        return tool(run)

    return gather


market_only = ResearchPlan(
    symbol=SYMBOL, tasks=[ResearchTask(source="market", reason="Only check the price.")]
)
watched = {source: record_calls(source, tool) for source, tool in TOOLS.items()}
routed = route_plan(Run(symbol=SYMBOL), market_only, gatherers=watched)
print()
print("Tools called:", called)
""")

    md("""
### 2.3 The tools return real data

Now we route the full plan, so all three tools run. Earnings and market data come from yfinance. News comes from yfinance, then NewsAPI, then yfinance search headlines, whichever returns articles first. (Yahoo's ticker news feed stopped working in early October 2026, which is why the news tool has fallbacks.) News is passed through the news chain from section 3 before it becomes evidence.
""")

    code("""
tool_run = Run(symbol=SYMBOL)
full_plan = plan_research(SYMBOL, tool_run.run_id, provider="rules").plan
gathered = route_plan(tool_run, full_plan, gatherers=TOOLS)


def evidence_table(items):
    rows = []
    for item in items:
        rows.append({"source": item.source, "title": item.title, "content": item.content, "as of": item.as_of})
    return table(rows)


for source, items in gathered.items():
    print(f"{source}: {len(items)} evidence records")
evidence_table(gathered["earnings"] + gathered["market"])
""")

    code("""
evidence_table(gathered["news"]).head(6)
""")

    source(
        "Routing and the three tools. The market tool computes RSI and MACD from the price "
        "history; the news tool tries yfinance, NewsAPI, and search in that order.",
        [
            "route_plan",
            "default_gatherers",
            "gather_earnings",
            "gather_market",
            "market_module._rsi",
            "gather_news",
            "news_module._newsapi_records",
        ],
    )
    if kind == FULL:
        cells.insert(
            len(cells) - 1,
            full_only_cell(
                "import investment_committee.tools.market as market_module\n"
                "import investment_committee.tools.news as news_module"
            ),
        )

    md("""
### 2.4 The whole thing in one call

`run_research` does all of the above: read the last memory note, plan, route, run the tools, and save the run and its evidence to SQLite. (We pass in our `TOOLS`, whose news tool runs the news chain with the `nlp` pipeline loaded in setup.) If one source has no data (for example an ETF has no earnings), the run still finishes and says which source was missing. This saved run is the evidence pool the next sections argue from.
""")

    code("""
from investment_committee.storage import load_evidence, open_db
from investment_committee.workflows.runner import run_research

snapshot = run_research(
    SYMBOL,
    gatherers=TOOLS,
    database_path=DB_PATH,
    planner_provider="openai",
)
MAIN_RUN = snapshot.run.run_id

print("Run id:        ", MAIN_RUN)
print("Planner used:  ", snapshot.planner_provider_used, snapshot.planner_model or "")
print("Plan:          ", [task.source for task in snapshot.plan.tasks])
print("Saved evidence:", snapshot.saved_evidence_count)
for source, message in snapshot.gather_errors.items():
    print(f"Warning ({source}):", plain(message))

with closing(open_db(DB_PATH)) as conn:
    POOL = load_evidence(conn, MAIN_RUN)
table([{"source": source, "records": sum(1 for e in POOL if e.source == source)}
       for source in ("earnings", "news", "market")])
""")

    source(
        "`run_research` ties planning, routing, the news chain, and saving together.",
        ["run_research"],
    )

    # ----------------------------------------------------------- section 3
    md("""
## 3. News chain: ingest, preprocess, classify, gate, extract, summarize

**Rubric item:** prompt chaining. Each step's output is the next step's input.

We show the chain on the saved sample articles first, because they include tricky cases on purpose: an exact duplicate, an empty article, HTML tags, and curly quotes.

### Step 1: ingest
""")

    code("""
from investment_committee.workflows.chaining import (
    classification_gate,
    classify,
    extract,
    ingest,
    preprocess,
    summarize,
)

articles = ingest(ROOT / "tests/fixtures/sample_articles.json")
table([{"id": a.article_id, "symbol": a.symbol, "title": a.title, "body length": len(a.body)}
       for a in articles])
""")

    md("""
### Step 2: preprocess

Remove HTML, turn curly quotes into plain ones, collapse spaces, and drop empty articles and exact duplicates.
""")

    code("""
kept = preprocess(articles)
kept_ids = [article.article_id for article, _ in kept]
print("In:", len(articles), "| out:", len(kept))
print("Dropped:", [a.article_id for a in articles if a.article_id not in kept_ids])
print()
# The raw text has a curly apostrophe; backslashreplace prints it as \\u2019 so we can see it.
raw = articles[0].body.encode("ascii", "backslashreplace").decode()
print("Before:", raw[60:190])
print("After: ", kept[0][1][60:175])
""")

    md("""
`a-002` is the same story as `a-001` with extra spaces, and `n-002` has an empty body, so both are dropped. After cleaning, the `<br />` tags are gone and the curly apostrophe (`\\u2019`) is a plain `'`.

### Steps 3 and 4: classify, then the gate

`classify` gives each article a category from keywords. The **gate** comes right after it: only categories that can move a stock price (earnings, product, legal, market) are allowed into the evidence pool. Articles classified as `general` stop here.
""")

    code("""
rows = []
for article, text in kept:
    category = classify(text)
    accepted, reason = classification_gate(category)
    rows.append({"id": article.article_id, "title": article.title, "category": category,
                 "accepted": accepted, "gate reason": reason})
table(rows)
""")

    md("""
### Steps 5 and 6: extract and summarize

`extract` finds named entities (companies, people, money, dates) with spaCy. `summarize` keeps the first two sentences.
""")

    code("""
first_text = kept[0][1]
entities = extract(first_text, nlp)
display(table([{"entity": e.text, "label": e.label} for e in entities]))
print("Summary:", summarize(first_text))
""")

    md("""
### The whole chain, and the handoff to evidence

`run_chain` runs all the steps. `processed_to_evidence` turns only the **accepted** articles into shared `Evidence` records. Rejected articles stay in the chain output so we can count them, but they never reach the analysts. Evidence belongs to one stock, so here we only hand off the Apple articles.
""")

    code("""
apple_articles = [a for a in articles if a.symbol == "AAPL"]
processed = run_chain(apple_articles, nlp)
sample_run = Run(symbol="AAPL")
news_evidence = processed_to_evidence(sample_run, processed)
print("Processed:", len(processed), "| accepted:", sum(p.accepted for p in processed),
      "| became evidence:", len(news_evidence))
evidence_table(news_evidence)
""")

    md("""
**The same chain on live news.** These are the live articles for our stock. Real news has more noise than the samples, so the gate matters more here.
""")

    code("""
live_articles = gather_news(Run(symbol=SYMBOL)) if LIVE else sample_news(Run(symbol=SYMBOL))
live_processed = run_chain(live_articles, nlp)
print("Live articles:", len(live_articles), "| accepted by the gate:",
      sum(p.accepted for p in live_processed))
table([{"title": p.article.title, "category": p.category, "accepted": p.accepted}
       for p in live_processed])
""")

    source(
        "The chain steps, the gate, and the handoff to the shared `Evidence` model.",
        [
            "preprocess",
            "clean_text",
            "classify",
            "classification_gate",
            "extract",
            "summarize",
            "run_chain",
            "processed_to_evidence",
        ],
    )

    # ----------------------------------------------------------- section 4
    md("""
## 4. Bull and Bear over the evidence pool

**Rubric item:** agents that use the evidence to argue a position.

Both analysts use one shared drafting engine with opposite instructions. Each one reads the evidence pool from section 2.4 and must return 2 to 5 claims, and **every claim has to cite evidence ids from the pool**. The prompt also tells the model that the evidence text is data, not instructions (news text could contain anything).

If a claim cites an id that is not in the pool, we keep it on purpose. Throwing it away would hide the mistake. The evaluator in section 5 rejects it with a reason instead.
""")

    code("""
from investment_committee.agents.bear import draft_bear_claims_model
from investment_committee.agents.bull import draft_bull_claims_model

titles = {item.evidence_id: item.title for item in POOL}


def claims_table(claims):
    rows = []
    for claim in claims:
        cited = [titles.get(eid, "NOT IN POOL: " + eid) for eid in claim.evidence_ids]
        rows.append({"side": claim.side, "claim": claim.text, "cites": "; ".join(cited)})
    return table(rows)


bull = draft_bull_claims_model(POOL, settings, provider=PROVIDER)
bear = draft_bear_claims_model(POOL, settings, provider=PROVIDER)
for name, result in (("Bull", bull), ("Bear", bear)):
    print(f"{name}: {len(result.claims)} claims, provider used: {result.provider_used}",
          f"| unknown ids cited: {result.dropped_ids or 'none'}")
    if result.fallback_reason:
        print("  fell back because:", plain(result.fallback_reason))
claims_table(bull.claims + bear.claims)
""")

    source(
        "The shared drafting engine: the prompt, the model call, and the fallback to the "
        "template analysts.",
        ["_drafting_prompt", "draft_claims_model", "draft_claims_with_fallback"],
    )
    if kind == FULL:
        cells.insert(
            len(cells) - 1,
            full_only_cell(
                "from investment_committee.agents.analyst import (\n"
                "    _drafting_prompt,\n    draft_claims_model,\n    draft_claims_with_fallback,\n)"
            ),
        )

    # ----------------------------------------------------------- section 5
    md("""
## 5. Evaluator-optimizer loop and the verdict

**Rubric items:** the agent self-reflects on the quality of its output, and the evaluator-optimizer workflow.

The loop works like this:

1. Bull and Bear draft claims (section 4).
2. The **evaluator** checks every claim in two gates. The rules gate rejects any claim that cites evidence not in the pool. The model gate reads each remaining claim next to the text of the evidence it cites and decides if that text really supports it, with a one-sentence reason.
3. Rejected claims go **back to their analyst with the reason**, and the analyst writes a replacement. Supported claims are kept.
4. This repeats until everything is supported or we hit the round limit (2 rounds).
5. A final call reads **only the supported claims** and picks bull, bear, or none. We do not just count claims, because then the side that writes more small claims would win.

We run the committee as a new run that points to the evidence run from section 2.4 (its "parent"), so it argues from exactly that pool.
""")

    code("""
from investment_committee.storage import save_run
from investment_committee.workflows.evaluator_optimizer import run_committee_from_storage

with closing(open_db(DB_PATH)) as conn:
    committee_run = Run(symbol=SYMBOL, with_review=True, parent_run_id=MAIN_RUN)
    save_run(conn, committee_run)
    result = run_committee_from_storage(conn, committee_run.run_id, settings, provider=PROVIDER)

print("Rounds:", result.rounds, "| verdict:", result.verdict)
print("Fallbacks:", result.fallbacks or "none")
""")

    md("""
**Every claim the evaluator saw, round by round.** Revision 0 is the first draft. Revision 1 claims are rewrites of claims that were rejected in round 1.
""")

    code("""
rows = []
for claim in result.all_claims:
    rows.append({"revision": claim.revision, "side": claim.side, "supported": claim.supported,
                 "evaluator reason": claim.reason, "claim": claim.text})
table(rows)
""")

    md("""
**The memo.** The verdict comes first, then the diagnostics, then the supported claims with their evidence ids.
""")

    code("""
print(plain(result.memo))
""")

    md("""
**Self-reflection.** At the end, the committee scores its own work: its confidence is the share of final claims that were supported, and its open gaps list what it went without (a missing source, or claims that were sent back). This becomes the memory note for the next run (section 6).

We also keep every model call with its stage, tokens, and time, so we can see what the loop cost.
""")

    code("""
print("Confidence:", round(result.note.confidence, 2))
print("Open gaps: ", result.note.open_gaps or "none")
print("Lesson:    ", plain(result.note.lesson))
print()
calls = pd.DataFrame([{"stage": c.stage, "tokens": c.prompt_tokens + c.completion_tokens,
                       "ms": c.latency_ms} for c in result.model_calls])
if calls.empty:
    print("No model calls (rule-based run).")
else:
    display(calls.groupby("stage").agg(calls=("tokens", "size"), tokens=("tokens", "sum"),
                                       total_ms=("ms", "sum")))
""")

    md("""
### A controlled example of one full review cycle

A live run does not always reject a claim, so here is a small controlled example where we know a rejection will happen. Instead of OpenAI, we plug in a **scripted client** that gives fixed answers in the same format the model would. This is the same trick our tests use. Everything else (the loop, the two evaluator gates, the rewrite, the verdict) is the real code.

The script: the Bull analyst cites real evidence. The Bear analyst's first claim cites an evidence id that does not exist, so the rules gate rejects it without even asking the model. The Bear analyst then gets the rejection reason back and writes a replacement that cites real evidence, and round 2 accepts it.

**This is not a live result.** The answers are written by us to show the mechanism.
""")

    code('''
from types import SimpleNamespace

from investment_committee.agents.analyst import DraftedClaim, DraftedClaims
from investment_committee.agents.evaluator import ClaimVerdict
from investment_committee.config import ENV_VARS, Settings
from investment_committee.workflows.evaluator_optimizer import CommitteeVerdict, run_committee


class ScriptedClient:
    """Stands in for the OpenAI client and returns our fixed answers in order."""

    def __init__(self, drafts, verdicts, decisions):
        self.answers = {DraftedClaims: drafts, ClaimVerdict: verdicts, CommitteeVerdict: decisions}
        self.responses = self

    def parse(self, *, model, instructions, input, text_format):
        answer = self.answers[text_format].pop(0)
        usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        return SimpleNamespace(output_parsed=answer, model="scripted", usage=usage)


def one_claim(evidence_id, text):
    return DraftedClaims(claims=[DraftedClaim(text=text, evidence_ids=[evidence_id])])


script = ScriptedClient(
    drafts=[
        one_claim("ev-001", "Revenue grew 4 percent from a year earlier."),  # Bull, round 1
        one_claim("ev-999", "Profit collapsed this quarter."),  # Bear, round 1: no such id
        one_claim("ev-002", "EPS beat consensus by only 4 cents."),  # Bear rewrite, round 2
    ],
    verdicts=[
        ClaimVerdict(supported=True, reason="The revenue row says up 4 percent."),
        ClaimVerdict(supported=True, reason="Still matches the revenue row."),
        ClaimVerdict(supported=True, reason="EPS was 1.42 against 1.38."),
    ],
    decisions=[CommitteeVerdict(side="bull", reason="Growth is clear; the EPS beat is small.")],
)

sample_pool = [Evidence(**item) for item in SAMPLE_EVIDENCE["evidence"]]
scripted_settings = Settings(values={name: "scripted" if name == "OPENAI_API_KEY" else None
                                     for name in ENV_VARS})
controlled = run_committee(Run(symbol="AAPL", with_review=True), sample_pool, scripted_settings,
                           client=script)

table([{"revision": c.revision, "side": c.side, "supported": c.supported,
        "evaluator reason": c.reason, "evidence": ", ".join(c.evidence_ids), "claim": c.text}
       for c in controlled.all_claims])
''')

    md("""
Round 1 rejected the Bear claim with the reason "cites evidence not in the pool: ev-999". In round 2 the Bear analyst replaced it with a claim that cites `ev-002`, the evaluator accepted it, and the kept Bull claim was checked again. Then the loop stopped because nothing was left unsupported.
""")

    code("""
print("Rounds:", controlled.rounds, "| verdict:", controlled.verdict)
print(controlled.memo)
""")

    source(
        "The loop itself (`run_committee`), the verdict call, and the two evaluator gates. "
        "`reflect` is the self-reflection step that writes confidence and open gaps.",
        [
            "run_committee",
            "evo_module._decide",
            "evaluate_claims",
            "evaluate_claims_model",
            "evaluator_module._judge_claim",
            "reflect",
            "run_committee_from_storage",
        ],
    )
    if kind == FULL:
        cells.insert(
            len(cells) - 1,
            full_only_cell(
                "import investment_committee.agents.evaluator as evaluator_module\n"
                "import investment_committee.workflows.evaluator_optimizer as evo_module\n"
                "from investment_committee.agents.evaluator import (\n"
                "    evaluate_claims,\n    evaluate_claims_model,\n    reflect,\n)\n"
                "from investment_committee.workflows.evaluator_optimizer import run_committee"
            ),
        )

    # ----------------------------------------------------------- section 6
    md("""
## 6. Memory across runs

**Rubric item:** the agent learns across runs.

After every committee run, its memory note (confidence, open gaps, lesson) is saved in SQLite. When the next run for the same stock starts, `run_research` loads the latest note and gives it to the planner.

To make the effect easy to see, we use a different stock and pretend the market tool is down in the first run. The committee should notice that it had no market evidence, and the second run's planner should move market from the last step to the first.
""")

    code("""
from investment_committee.storage import load_latest_note

MEMORY_SYMBOL = "MSFT"
TOOLS_NO_MARKET = {**TOOLS, "market": lambda run: []}

with closing(open_db(DB_PATH)) as conn:
    print("Note before run 1:", load_latest_note(conn, MEMORY_SYMBOL))

first = run_research(MEMORY_SYMBOL, gatherers=TOOLS_NO_MARKET, database_path=DB_PATH,
                     planner_provider="rules")
print("Run 1 plan:", [task.source for task in first.plan.tasks])

with closing(open_db(DB_PATH)) as conn:
    first_committee = run_committee_from_storage(conn, first.run.run_id, settings, provider=PROVIDER)
    saved_note = load_latest_note(conn, MEMORY_SYMBOL)

print("Run 1 verdict:", first_committee.verdict)
print("Saved note -> confidence:", round(saved_note.confidence, 2))
print("              open gaps:", saved_note.open_gaps)
""")

    md("""
Now the second run. Nothing is passed in by hand: `run_research` reads the note from the database by itself.
""")

    code("""
second = run_research(MEMORY_SYMBOL, gatherers=TOOLS, database_path=DB_PATH, planner_provider="rules")
print("Lesson the planner read:", plain(second.plan.memory_lesson))
display(table([{"step": n, "run 1": a.source, "run 2": b.source, "run 2 reason": b.reason}
               for n, (a, b) in enumerate(zip(first.plan.tasks, second.plan.tasks, strict=True), start=1)]))
""")

    md("""
Market moved from step 3 to step 1, and its reason now says it is revisiting the gap from the last run. Nobody changed the code or the settings between the two runs; the only difference is the note the first run left behind.

The OpenAI planner gets the same note inside its prompt, so it can use it too:
""")

    code("""
model_with_memory = plan_research(MEMORY_SYMBOL, second.run.run_id, provider="openai",
                                  previous_note=saved_note, settings=settings)
print("Planner used:", model_with_memory.provider_used)
plan_table(model_with_memory.plan)
""")

    source(
        "Saving and loading the notes. The other half, how `build_plan` uses the open gaps, "
        "is printed in section 2.",
        ["load_latest_note", "save_memory_note"],
    )
    if kind == FULL:
        cells.insert(
            len(cells) - 1,
            full_only_cell("from investment_committee.storage import save_memory_note"),
        )

    # ----------------------------------------------------------- section 7
    md("""
## 7. Evaluation and iteration: with vs without review

**Question:** does the evaluator loop make the committee's final claims better supported?

**How we test it fairly.** For each stock we gather evidence **once**. Then we run the committee twice on that same saved evidence: once with the review loop and once without it (draft, judge once, decide). Both runs point to the same parent run in SQLite, so the evidence is identical and the review loop is the only setting we change. Each run still writes its own first draft, so the drafts can differ too (see the limits below).

### 7.1 A controlled comparison (scripted, offline)

First the same experiment with the scripted client from section 5, so the difference between the arms is easy to see and the result is the same every time. Both arms get the same scripted first drafts: a good Bull claim and a Bear claim that cites a missing id. With review, the Bear claim is sent back and rewritten. Without review, it stays rejected. **This shows how the experiment works, not whether the loop helps:** we wrote these answers ourselves.
""")

    code("""
from investment_committee.evaluation.harness import (
    plot_support_comparison,
    run_review_comparison,
    run_symbol_sweep,
)
from investment_committee.evaluation.metrics import comparison_rows, score_run
from investment_committee.storage import save_run_with_evidence

with_review_answers = dict(
    drafts=[
        one_claim("ev-001", "Revenue grew 4 percent from a year earlier."),
        one_claim("ev-999", "Profit collapsed this quarter."),
        one_claim("ev-002", "EPS beat consensus by only 4 cents."),
    ],
    verdicts=[ClaimVerdict(supported=True, reason="Matches the cited row.")] * 3,
    decisions=[CommitteeVerdict(side="none", reason="Each side has one grounded point.")],
)
without_review_answers = dict(
    drafts=[
        one_claim("ev-001", "Revenue grew 4 percent from a year earlier."),
        one_claim("ev-999", "Profit collapsed this quarter."),
    ],
    verdicts=[ClaimVerdict(supported=True, reason="Matches the cited row.")],
    decisions=[CommitteeVerdict(side="bull", reason="Only the Bull claim survived.")],
)
# run_review_comparison runs the with-review arm first, then the other one.
script = ScriptedClient(
    drafts=with_review_answers["drafts"] + without_review_answers["drafts"],
    verdicts=with_review_answers["verdicts"] + without_review_answers["verdicts"],
    decisions=with_review_answers["decisions"] + without_review_answers["decisions"],
)

controlled_conn = open_db(":memory:")
controlled_parent = Run(**SAMPLE_EVIDENCE["run"])
save_run_with_evidence(controlled_conn, controlled_parent, sample_pool)
controlled_ab = run_review_comparison(
    controlled_conn, controlled_parent.run_id, scripted_settings, client=script
)
controlled_ids = [controlled_ab.with_review.run.run_id, controlled_ab.without_review.run.run_id]
table(comparison_rows(controlled_conn, controlled_ids))
""")

    md("""
With review, the Bear claim was rewritten and both sides reached the chair, so the verdict was "none". Without review, only the Bull claim survived, so the chair said "bull". The loop changed which arguments the decision was based on.

### 7.2 The live comparison

**What we measure** for each run:
- **Supported claims:** how many grounded claims the evaluator saved for the chair.
- **Rejected drafts:** how many drafts were sent back or left out of the verdict.
- Rounds, model calls, and tokens: what the loop costs.
- Verdict: did the loop change the decision?
""")

    code("""
EVAL_SYMBOLS = ["AAPL", "NVDA", "JPM"]

# Michael's sweep helper gathers each stock once, runs both review arms from
# that saved evidence, and reads the scorecard back from SQLite.
sweep_rows = run_symbol_sweep(
    EVAL_SYMBOLS,
    DB_PATH,
    settings,
    gatherers=None if LIVE else TOOLS,
    planner_provider="rules",
    provider=PROVIDER,
)
sweep_table = table(sweep_rows)
if PROVIDER == "template":
    print("Rule-based run: the template analysts cite one real item per claim, so every claim")
    print("passes and both arms look the same. The comparison needs the model run.")
sweep_table.drop(columns=["run id"])
""")

    code("""
columns = ["supported claims", "rejected drafts", "model calls", "rounds"]
summary = sweep_table.groupby("review loop")[columns].mean()
summary.round(2)
""")

    md("""
**The stored scorecard.** `run_symbol_sweep` already returns `comparison_rows` from SQLite. Here "supported claims" and "rejected drafts" count every draft the evaluator judged, including drafts the loop later replaced, so they show how much work the loop did.
""")

    code("""
run_ids = [row["run id"] for row in sweep_rows]

with closing(open_db(DB_PATH)) as conn:
    scores = [score_run(conn, run_id) for run_id in run_ids]
display(sweep_table)

figure, axis = plot_support_comparison(scores)
""")

    md("""
**How to read this.** Without review, the first drafts are judged once and go straight to the verdict. With review, rejected claims are sent back with the evaluator's reason and rewritten, and the rewrites are judged again. A rewrite can be rejected too, and after the second round the loop stops, so the final slate with review can still contain unsupported claims. The chair only reads the supported ones either way. The chart shows the extra work the loop does: rejected drafts are claims the evaluator sent back.

**Limits of this test.** Each arm writes its own first draft, so some of the difference between arms comes from the drafts and not from the loop. Three stocks is a small sample. And the same model family drafts and judges the claims, and model judges tend to favor their own writing (Panickssery et al., 2024).
""")

    source(
        "The experiment harness and the stored scorecard.",
        [
            "run_review_comparison",
            "run_symbol_sweep",
            "score_run",
            "comparison_rows",
            "plot_support_comparison",
        ],
    )

    # ----------------------------------------------------------- appendix (full only)
    if kind == FULL:
        md("""
## Appendix: shared data models and the database

Every stage passes these record types to the next one, and SQLite is the only place they are stored. This is the contract the three of us built against.
""")
        cells[-1].metadata["tags"] = ["full-only"]
        code("""
import investment_committee.models as models_module
from investment_committee.storage import SCHEMA

show_code(models_module.Run, models_module.Evidence, models_module.Claim,
          models_module.MemoryNote, models_module.ModelCall)
print(SCHEMA)
""")
        cells[-1].metadata["tags"] = ["full-only"]

    # ----------------------------------------------------------- 8, 9, refs
    if CONCLUSIONS in kept:
        md(kept[CONCLUSIONS])
    else:
        md("""
## 8. Conclusions

TODO(team): write after the final run, using the numbers in section 7.

- **What worked:** ...
- **What did not:** ...
- **With more time:** check claims with an NLI model, use a judge from a different model family than the analysts, and add SEC filings for the earnings analyst (the stretch items in `docs/ARCHITECTURE.md`).
""")

    if DISCLOSURES in kept:
        md(kept[DISCLOSURES])
    else:
        md("""
## 9. AI tool disclosures

Each of us writes our own paragraph in the first person, following `docs/AI_DISCLOSURE.md`: which tools we used, what they did, what we changed or checked, and that the work reflects our own understanding.

**Guna Pasupathy.** TODO(guna)

**Michael Valderrama.** TODO(michael)

**Mina Habib.** TODO(mina)
""")

    md("""
## References

Anthropic. (2024). *Building effective agents*. https://www.anthropic.com/research/building-effective-agents

Aroussi, R. (2026). *yfinance* (Version 1.7.0) [Computer software]. https://github.com/ranaroussi/yfinance

Du, Y., Li, S., Torralba, A., Tenenbaum, J. B., & Mordatch, I. (2023). *Improving factuality and reasoning in language models through multiagent debate*. International Conference on Machine Learning. https://arxiv.org/abs/2305.14325

Honnibal, M., Montani, I., Van Landeghem, S., & Boyd, A. (2020). *spaCy: Industrial-strength natural language processing in Python*. Zenodo. https://doi.org/10.5281/zenodo.1212303

NewsAPI. (n.d.). *News API*. Retrieved October 10, 2026, from https://newsapi.org

Panickssery, A., Bowman, S. R., & Feng, S. (2024). *LLM evaluators recognize and favor their own generations*. Advances in Neural Information Processing Systems. https://arxiv.org/abs/2404.13076

Xiao, Y., Sun, E., Luo, D., & Wang, W. (2024). *TradingAgents: Multi-agents LLM financial trading framework*. https://arxiv.org/abs/2412.20138

TODO(team): add the AI tool entries from section 9 and the OpenAI model entry, alphabetized.
""")

    notebook = new_notebook(cells=cells)
    notebook.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    notebook.metadata["language_info"] = {"name": "python"}
    return notebook


def light_from_full(full_path, light_path):
    """Drop the full-only cells, swap in the light intro, and renumber the cells."""
    full = nbformat.read(full_path, as_version=4)
    cells = [cell for cell in full.cells if "full-only" not in cell.metadata.get("tags", [])]
    cells[0] = build(LIGHT).cells[0]

    count = 0
    for cell in cells:
        if cell.cell_type == "code" and cell.get("execution_count") is not None:
            count += 1
            cell.execution_count = count
            for output in cell.outputs:
                if "execution_count" in output:
                    output.execution_count = count

    full.cells = cells
    nbformat.write(full, light_path)


def main():
    """Run one build step from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["build", "light-from-full"])
    args = parser.parse_args()
    if args.step == "build":
        # Keep the hand-written sections, so a rebuild does not erase them.
        kept = saved_sections()
        nbformat.write(build(FULL, kept), FULL_PATH)
        nbformat.write(build(LIGHT, kept), LIGHT_PATH)
    else:
        light_from_full(FULL_PATH, LIGHT_PATH)
    print("done:", args.step)


if __name__ == "__main__":
    main()
