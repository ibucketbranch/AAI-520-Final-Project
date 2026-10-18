"""Tests for the news chain: ingest, preprocess, classify, extract, summarize.

No network and no spaCy model download: entity extraction is tested against a
blank English pipeline with an entity ruler, per the repo rule that tests mock
every tool.
"""

from pathlib import Path

import pytest
import spacy

from investment_committee.workflows.chaining import (
    RawArticle,
    classify,
    clean_text,
    extract,
    ingest,
    preprocess,
    run_chain,
    summarize,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_articles.json"


@pytest.fixture()
def nlp():
    """A blank English pipeline with a ruler standing in for the NER model."""
    pipeline = spacy.blank("en")
    ruler = pipeline.add_pipe("entity_ruler")
    ruler.add_patterns(
        [
            {"label": "ORG", "pattern": "Apple"},
            {"label": "ORG", "pattern": "Tesla"},
            {"label": "ORG", "pattern": "Netflix"},
            {"label": "PERSON", "pattern": "Elon Musk"},
            {"label": "PERSON", "pattern": "Tim Cook"},
        ]
    )
    return pipeline


def test_ingest_loads_and_validates_all_articles():
    articles = ingest(FIXTURE_PATH)
    assert len(articles) == 8
    assert all(isinstance(a, RawArticle) for a in articles)
    assert articles[0].symbol == "AAPL"


def test_clean_text_strips_html_maps_unicode_and_collapses_whitespace():
    raw = "café owners said<br /><br />it’s “fine” – for now…   really"
    cleaned = clean_text(raw)
    assert cleaned == 'cafe owners said it\'s "fine" - for now... really'
    assert all(ord(ch) < 128 for ch in cleaned)


def test_preprocess_drops_the_duplicate_and_the_empty_body():
    articles = ingest(FIXTURE_PATH)
    kept = preprocess(articles)
    kept_ids = [article.article_id for article, _ in kept]
    assert "a-002" not in kept_ids  # exact duplicate of a-001 modulo html/whitespace
    assert "n-002" not in kept_ids  # body is empty after cleaning
    assert kept_ids == ["a-001", "a-003", "t-001", "t-002", "t-003", "n-001"]


def test_classify_maps_keywords_and_falls_back_to_general():
    assert classify("Quarterly earnings beat expectations on revenue.") == "earnings"
    assert classify("A lawsuit and a regulator investigation.") == "legal"
    assert classify("The festival screening drew a quiet crowd.") == "general"


def test_extract_returns_ruler_entities_with_offsets(nlp):
    text = "Apple hired a rival while Elon Musk posted about it."
    entities = extract(text, nlp)
    labels = {(e.text, e.label) for e in entities}
    assert ("Apple", "ORG") in labels
    assert ("Elon Musk", "PERSON") in labels
    apple = next(e for e in entities if e.text == "Apple")
    assert text[apple.start : apple.end] == "Apple"


def test_summarize_keeps_the_lead_sentences():
    text = "First sentence. Second sentence! Third sentence?"
    assert summarize(text) == "First sentence. Second sentence!"
    assert summarize(text, max_sentences=1) == "First sentence."


def test_run_chain_end_to_end_on_the_fixtures(nlp):
    articles = ingest(FIXTURE_PATH)
    processed = run_chain(articles, nlp)
    assert len(processed) == 6
    by_id = {p.article.article_id: p for p in processed}
    assert by_id["a-001"].category == "earnings"
    assert by_id["t-001"].category == "legal"
    assert ("Apple", "ORG") in {(e.text, e.label) for e in by_id["a-001"].entities}
    assert all(p.summary for p in processed)
    assert all(ord(ch) < 128 for p in processed for ch in p.clean_text)


def test_classification_gate_accepts_known_investment_categories_and_rejects_general():
    from investment_committee.workflows.chaining import classification_gate

    assert classification_gate("earnings")[0] is True
    accepted, reason = classification_gate("product")
    assert accepted is True and "accepted" in reason
    rejected, reason = classification_gate("general")
    assert rejected is False and "rejected" in reason


def test_run_chain_records_gate_decision_and_stops_rejected_article(nlp):
    articles = [
        RawArticle(
            article_id="general-1",
            symbol="NFLX",
            source="fixture",
            published="2026-09-10",
            title="Festival item",
            body="The festival screening drew a quiet crowd.",
        ),
        RawArticle(
            article_id="earnings-1",
            symbol="AAPL",
            source="fixture",
            published="2026-09-10",
            title="Apple reports earnings",
            body="Apple reported quarterly earnings above expectations.",
        ),
    ]
    processed = run_chain(articles, nlp)
    rejected = processed[0]
    accepted = processed[1]
    assert rejected.accepted is False
    assert rejected.entities == []
    assert rejected.summary
    assert accepted.accepted is True
    assert accepted.summary


def test_processed_news_becomes_shared_evidence(nlp):
    from investment_committee.models import Run
    from investment_committee.workflows.chaining import processed_to_evidence

    articles = ingest(FIXTURE_PATH)
    processed = run_chain(articles, nlp)
    run = Run(symbol="AAPL")
    evidence = processed_to_evidence(run, processed)

    assert evidence
    assert all(item.source == "news" for item in evidence)
    assert all(item.run_id == run.run_id for item in evidence)
    assert all(item.content for item in evidence)
    assert not any(item.title.startswith("Netflix café") for item in evidence)


def test_processed_news_skips_other_companies(nlp):
    from investment_committee.models import Run
    from investment_committee.workflows.chaining import processed_to_evidence

    processed = run_chain(ingest(FIXTURE_PATH), nlp)
    tesla_titles = {item.article.title for item in processed if item.article.symbol == "TSLA"}
    evidence = processed_to_evidence(Run(symbol="AAPL"), processed)

    assert evidence
    assert all(item.title not in tesla_titles for item in evidence)
