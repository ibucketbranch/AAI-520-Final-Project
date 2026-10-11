"""Build the light and full course notebooks from one set of cells."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from textwrap import dedent

import nbformat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from investment_committee.agents.bear import draft_bear_claims  # noqa: E402
from investment_committee.agents.bull import draft_bull_claims  # noqa: E402
from investment_committee.agents.evaluator import evaluate_claims  # noqa: E402
from investment_committee.agents.planner import build_plan  # noqa: E402
from investment_committee.evaluation.harness import (  # noqa: E402
    plot_support_comparison,
    run_review_comparison,
)
from investment_committee.evaluation.metrics import (  # noqa: E402
    comparison_rows,
    score_run,
)
from investment_committee.models import Claim, Evidence, MemoryNote, Run  # noqa: E402
from investment_committee.workflows.chaining import (  # noqa: E402
    classification_gate,
    classify,
    clean_text,
    extract,
    ingest,
    preprocess,
    processed_to_evidence,
    run_chain,
    summarize,
)
from investment_committee.workflows.evaluator_optimizer import (  # noqa: E402
    run_committee,
)
from investment_committee.workflows.routing import route_plan  # noqa: E402


def _markdown(text: str):
    return nbformat.v4.new_markdown_cell(dedent(text).strip())


def _code(text: str):
    return nbformat.v4.new_code_cell(dedent(text).strip())


def _source_cell(title: str, *objects: object):
    source = "\n\n".join(inspect.getsource(item).rstrip() for item in objects)
    text = (
        f"### {title}: code used in this section\n\n"
        "The full notebook includes the main implementation so it can be reviewed here.\n\n"
        f"```python\n{source}\n```"
    )
    return nbformat.v4.new_markdown_cell(text)


def _intro_cells() -> list:
    return [
        _markdown("""
        # AI Investment Committee

        **AAI-520 Final Team Project, Group 7**<br>
        **Team:** Guna Pasupathy, Mina Habib, and Michael Valderrama<br>
        **Repository:** [AAI-520-Final-Project](https://github.com/ibucketbranch/AAI-520-Final-Project)

        This notebook shows how our investment committee plans research, routes work,
        processes news, builds Bull and Bear claims, checks those claims, and remembers
        a lesson for the next run. It is a class demonstration, not financial advice.

        The demo is offline. The articles and financial values are synthetic fixtures.
        A scripted client stands in for a language model so the same review behavior can
        be reproduced without an API key.
        """),
        _markdown("""
        ## 1. Agent design and workflows

        The system starts with a stock symbol. A planner decides which sources to use.
        Earnings, news, and market gatherers add facts to one evidence pool. The Bull
        and Bear analysts make claims from that pool. The evaluator checks every cited
        evidence ID and sends weak claims back for one more draft. The final run saves a
        memory note that the next plan can read.

        We use three workflow patterns:

        1. **Routing:** each plan task goes to the matching gatherer.
        2. **Prompt chaining:** news moves through ingest, clean, classify, gate,
           entity extraction, and summary steps.
        3. **Evaluator-optimizer:** claims are drafted, checked, and revised when needed.

        ```mermaid
        flowchart TD
            S[Stock symbol] --> P[Planner]
            P --> E[Earnings gatherer]
            P --> N[News gatherer]
            P --> M[Market gatherer]
            E --> POOL[(Evidence pool)]
            N --> C[News chain and gate]
            C --> POOL
            M --> POOL
            POOL --> BULL[Bull analyst]
            POOL --> BEAR[Bear analyst]
            BULL --> EV[Evaluator]
            BEAR --> EV
            EV --> V[Verdict and memo]
            EV --> MEM[Memory note]
            MEM -.-> P
        ```
        """),
        _code("""
        import json
        import sys
        from pathlib import Path
        from types import SimpleNamespace

        import pandas as pd
        import spacy

        # This works when the notebook starts from the repository root or its own folder.
        ROOT = next(
            folder for folder in [Path.cwd(), *Path.cwd().parents] if (folder / "pyproject.toml").exists()
        )
        sys.path.insert(0, str(ROOT / "src"))

        from investment_committee.agents.analyst import DraftedClaim, DraftedClaims
        from investment_committee.agents.bear import draft_bear_claims
        from investment_committee.agents.bull import draft_bull_claims
        from investment_committee.agents.evaluator import ClaimVerdict
        from investment_committee.agents.planner import build_plan
        from investment_committee.config import ENV_VARS, Settings
        from investment_committee.evaluation.harness import (
            plot_support_comparison,
            run_review_comparison,
        )
        from investment_committee.evaluation.metrics import comparison_rows, score_run
        from investment_committee.models import Evidence, Run
        from investment_committee.storage import open_db, save_run_with_evidence
        from investment_committee.workflows.chaining import (
            ingest,
            processed_to_evidence,
            run_chain,
        )
        from investment_committee.workflows.evaluator_optimizer import CommitteeVerdict
        from investment_committee.workflows.routing import route_plan

        print("Project package loaded from the repository.")
        print("This run uses local fixtures and makes no network calls.")
        """),
        _markdown("""
        The scripted client below returns fixed structured responses. It is only used
        for the offline class demo. The production path uses the same functions with an
        OpenAI client when a key is available.
        """),
        _code("""
        class ScriptedResponses:
            def __init__(self, drafts, verdicts, decisions):
                self.drafts = list(drafts)
                self.verdicts = list(verdicts)
                self.decisions = list(decisions)

            def parse(self, *, model, instructions, input, text_format):
                if text_format is DraftedClaims:
                    result = self.drafts.pop(0)
                elif text_format is ClaimVerdict:
                    result = self.verdicts.pop(0)
                elif text_format is CommitteeVerdict:
                    result = self.decisions.pop(0)
                else:
                    raise ValueError(f"Unexpected response type: {text_format}")

                return SimpleNamespace(
                    output_parsed=result,
                    model="offline-scripted-model",
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                )


        class ScriptedClient:
            def __init__(self, drafts, verdicts, decisions):
                self.responses = ScriptedResponses(drafts, verdicts, decisions)


        def drafted_claim(evidence_id, text):
            return DraftedClaims(claims=[DraftedClaim(text=text, evidence_ids=[evidence_id])])


        def make_demo_client():
            # The reviewed arm rejects one Bear draft and replaces it in round two.
            # The baseline arm stops after the same first-round rejection.
            drafts = [
                drafted_claim("ev-001", "Revenue growth supports the Bull case."),
                drafted_claim("missing-evidence", "Profit collapsed in the quarter."),
                drafted_claim("ev-002", "Valuation still depends on continued EPS growth."),
                drafted_claim("ev-001", "Revenue growth supports the Bull case."),
                drafted_claim("missing-evidence", "Profit collapsed in the quarter."),
            ]
            verdicts = [
                ClaimVerdict(supported=True, reason="The revenue evidence supports it."),
                ClaimVerdict(supported=True, reason="The revenue evidence still supports it."),
                ClaimVerdict(supported=True, reason="The EPS evidence supports the revision."),
                ClaimVerdict(supported=True, reason="The revenue evidence supports it."),
            ]
            decisions = [
                CommitteeVerdict(side="none", reason="Both sides have supported points."),
                CommitteeVerdict(side="bull", reason="Only the Bull claim survived."),
            ]
            return ScriptedClient(drafts, verdicts, decisions)


        demo_settings = Settings(
            values={name: "offline-demo" if name == "OPENAI_API_KEY" else None for name in ENV_VARS}
        )
        """),
    ]


def _planner_cells(full: bool) -> list:
    cells = [
        _markdown("""
        ## 2. Planner and dynamic tool use

        The planner returns an ordered list of sources. The router reads that list and
        calls the matching gatherer. For this offline run, each gatherer reads from the
        committed evidence fixture instead of calling a live service.
        """),
    ]
    if full:
        cells.append(_source_cell("Planner and router", build_plan, route_plan))
    cells.append(
        _code("""
        fixture = json.loads((ROOT / "tests/fixtures/sample_evidence.json").read_text())
        fixture_evidence = [Evidence(**item) for item in fixture["evidence"]]

        plan = build_plan("AAPL")
        routing_run = Run(symbol="AAPL")


        def fixture_gatherer(source):
            def gather(run):
                return [
                    item.model_copy(update={"run_id": run.run_id})
                    for item in fixture_evidence
                    if item.source == source
                ]

            return gather


        gatherers = {source: fixture_gatherer(source) for source in ("earnings", "news", "market")}
        routed = route_plan(routing_run, plan, gatherers)

        display(pd.DataFrame([task.model_dump() for task in plan.tasks]))
        display(
            pd.DataFrame(
                [{"source": source, "rows returned": len(items)} for source, items in routed.items()]
            )
        )
        """),
    )
    return cells


def _news_cells(full: bool) -> list:
    cells = [
        _markdown("""
        ## 3. News chain: ingest, preprocess, classify, extract, summarize

        The news chain keeps each step visible. The classification gate only promotes
        earnings, product, legal, or market articles into the shared evidence pool.
        General articles remain visible in the results but do not become evidence.
        """),
    ]
    if full:
        cells.append(
            _source_cell(
                "News chain",
                ingest,
                clean_text,
                preprocess,
                classify,
                classification_gate,
                extract,
                summarize,
                run_chain,
                processed_to_evidence,
            )
        )
    cells.append(
        _code("""
        articles = [
            article
            for article in ingest(ROOT / "tests/fixtures/sample_articles.json")
            if article.symbol == "AAPL"
        ]

        nlp = spacy.blank("en")
        ruler = nlp.add_pipe("entity_ruler")
        ruler.add_patterns(
            [
                {"label": "ORG", "pattern": "Apple"},
                {"label": "PERSON", "pattern": "Tim Cook"},
            ]
        )

        processed_news = run_chain(articles, nlp)
        news_run = Run(symbol="AAPL")
        news_evidence = processed_to_evidence(news_run, processed_news)

        display(
            pd.DataFrame(
                [
                    {
                        "title": item.article.title,
                        "category": item.category,
                        "accepted": item.accepted,
                        "entities": ", ".join(entity.text for entity in item.entities),
                        "summary": item.summary,
                    }
                    for item in processed_news
                ]
            )
        )
        print(f"Promoted {len(news_evidence)} article(s) into Evidence rows.")
        """),
    )
    return cells


def _analyst_cells(full: bool) -> list:
    cells = [
        _markdown("""
        ## 4. Bull and Bear over the evidence pool

        Both analysts use the same evidence records. Every claim must list at least one
        evidence ID. The simple template path below works without a model and makes the
        citation handoff easy to inspect.
        """),
    ]
    if full:
        cells.append(_source_cell("Bull and Bear fallback", draft_bull_claims, draft_bear_claims))
    cells.append(
        _code("""
        # Leave out market evidence on purpose so the memory section has a real gap.
        parent = Run(**fixture["run"])
        evidence = [item for item in fixture_evidence if item.source != "market"]

        bull_claims = draft_bull_claims(evidence)
        bear_claims = draft_bear_claims(evidence)
        display(
            pd.DataFrame(
                [
                    {
                        "side": claim.side,
                        "claim": claim.text,
                        "evidence IDs": ", ".join(claim.evidence_ids),
                    }
                    for claim in bull_claims + bear_claims
                ]
            )
        )
        """),
    )
    return cells


def _committee_cells(full: bool) -> list:
    cells = [
        _markdown("""
        ## 5. Evaluator-optimizer loop and verdict

        We save one parent gathering run, then let both committee arms point to its
        evidence. In the reviewed arm, the first Bear claim cites a missing ID. The free
        citation gate rejects it, the Bear drafts a grounded replacement, and the second
        round checks the replacement. The baseline arm stops after round one.
        """),
    ]
    if full:
        cells.append(_source_cell("Evaluator-optimizer loop", evaluate_claims, run_committee))
    cells.append(
        _code("""
        conn = open_db(":memory:")
        save_run_with_evidence(conn, parent, evidence)

        comparison = run_review_comparison(
            conn,
            parent.run_id,
            demo_settings,
            client=make_demo_client(),
            model="offline-scripted-model",
        )

        reviewed = comparison.with_review
        history = pd.DataFrame(
            [
                {
                    "side": claim.side,
                    "revision": claim.revision,
                    "supported": claim.supported,
                    "reason": claim.reason,
                    "claim": claim.text,
                    "evidence IDs": ", ".join(claim.evidence_ids),
                }
                for claim in reviewed.all_claims
            ]
        )
        display(history)
        print(reviewed.memo)
        """),
    )
    return cells


def _memory_cells() -> list:
    return [
        _markdown("""
        ## 6. Memory across runs

        Reflection writes a confidence value, open gaps, and a short lesson. Our parent
        pool intentionally has no market evidence, so the reviewed run records that gap.
        The next rule-based plan moves market research to the first position.
        """),
        _code("""
        note = reviewed.note
        first_plan = build_plan("AAPL")
        next_plan = build_plan("AAPL", note)

        print("Saved lesson:", note.lesson)
        print("Open gaps:", note.open_gaps)
        display(
            pd.DataFrame(
                {
                    "first plan": [task.source for task in first_plan.tasks],
                    "next plan": [task.source for task in next_plan.tasks],
                }
            )
        )
        """),
    ]


def _evaluation_cells(full: bool) -> list:
    cells = [
        _markdown("""
        ## 7. Evaluation and iteration: with review vs. without review

        Both arms use the same parent evidence. The only setting that changes is
        `with_review`. The table is read back from SQLite instead of being built from
        temporary Python objects. Rejected drafts count every draft that failed at any
        point, including a draft that was later replaced.
        """),
    ]
    if full:
        cells.append(
            _source_cell(
                "A/B harness and metrics",
                run_review_comparison,
                score_run,
                comparison_rows,
                plot_support_comparison,
            )
        )
    cells.append(
        _code("""
        run_ids = [reviewed.run.run_id, comparison.without_review.run.run_id]
        rows = comparison_rows(conn, run_ids)
        display(pd.DataFrame(rows))

        scores = [score_run(conn, run_id) for run_id in run_ids]
        figure, axis = plot_support_comparison(scores)
        display(figure)
        """),
    )
    cells.append(
        _markdown("""
        In this offline example, review adds a second round and replaces the unsupported
        Bear draft with a supported claim. The no-review arm keeps the rejection and
        stops after one round. This is the behavior we wanted the A/B test to measure.

        The result does **not** show that the system predicts stock returns. It only shows
        that the review loop can improve citation support on a controlled example.
        """),
    )
    return cells


def _closing_cells() -> list:
    return [
        _markdown("""
        ## 8. Conclusions

        The project works best when every step uses the same small record types. The
        shared Evidence model lets market data, earnings data, and approved news flow
        into the same Bull, Bear, and evaluator code. SQLite also makes the comparison
        easier to audit because claims, calls, notes, and memos stay attached to a run.

        The main limitations are the use of synthetic fixtures in the offline demo,
        unstable public data services, and the fact that model judgments can change.
        With more time, we would test more symbols, add SEC filings, and compare the
        evaluator with a second model family.
        """),
        _markdown("""
        ## 9. AI tool disclosures

        These are draft disclosures. Each team member should confirm the tool version
        and wording before submission.

        **Guna Pasupathy.** I used Codex to help review the planner integration, resolve
        Git conflicts, and assemble this notebook. I checked the function calls, ran the
        offline notebook, and verified the results against the tests. The design choices
        and conclusions reflect my own understanding of the project.

        **Michael Valderrama.** I used Claude to help draft and review parts of the Bull,
        Bear, evaluator, and evaluation harness code. I revised the code, added offline
        tests, and checked the final behavior. Before submission, I will add the exact
        Claude model version I used. The design choices and conclusions reflect my own
        understanding of the project.

        **Mina Habib.** Mina will add a first-person paragraph naming the AI tools and
        versions she used for the news chain, what the tools helped with, and what she
        personally checked. The final paragraph will state that the methods and
        conclusions reflect her own understanding.
        """),
        _markdown("""
        ## References

        Anthropic. (2024). *Building effective agents*.
        https://www.anthropic.com/research/building-effective-agents

        Du, Y., Li, S., Torralba, A., Tenenbaum, J. B., & Mordatch, I. (2023).
        *Improving factuality and reasoning in language models through multiagent
        debate*. International Conference on Machine Learning.
        https://arxiv.org/abs/2305.14325

        Panickssery, A., Bowman, S. R., & Feng, S. (2024). *LLM evaluators recognize
        and favor their own generations*. Advances in Neural Information Processing
        Systems. https://arxiv.org/abs/2404.13076

        Xiao, Y., Sun, E., Luo, D., & Wang, W. (2024). *TradingAgents: Multi-agents
        LLM financial trading framework*. https://arxiv.org/abs/2412.20138
        """),
    ]


def build_notebook(*, full: bool):
    """Return either the short notebook or the self-contained review notebook."""
    cells = _intro_cells()
    if full:
        cells.insert(2, _source_cell("Shared records", Run, Evidence, Claim, MemoryNote))
    cells.extend(_planner_cells(full))
    cells.extend(_news_cells(full))
    cells.extend(_analyst_cells(full))
    cells.extend(_committee_cells(full))
    cells.extend(_memory_cells())
    cells.extend(_evaluation_cells(full))
    cells.extend(_closing_cells())
    return nbformat.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.11"},
        },
    )


def main() -> None:
    """Write the light dev notebook and the full final notebook."""
    light_path = ROOT / "notebooks/dev/gp_final_notebook_light.ipynb"
    full_path = ROOT / "notebooks/final/AAI520_AI_Investment_Committee.ipynb"
    nbformat.write(build_notebook(full=False), light_path)
    nbformat.write(build_notebook(full=True), full_path)
    print(f"Wrote {light_path.relative_to(ROOT)}")
    print(f"Wrote {full_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
