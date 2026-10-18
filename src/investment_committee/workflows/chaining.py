"""Prompt-chaining workflow: ingest -> preprocess -> classify -> extract -> summarize.

This is the news chain from docs/ARCHITECTURE.md. Each stage is a plain
function so the notebook can demonstrate them one at a time and the routing
workflow can consume any intermediate stage. The chain runs on saved articles
(committed JSON fixtures) so it works offline and without any API key.

Two stages are deliberate placeholders until the course reaches the model
work: classify() is a keyword rule and summarize() is lead-sentence
extraction. Both keep the chain runnable end to end today and both get
replaced behind the same signatures (see the Sep 22 and Oct 6 milestones in
the proposal).
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from investment_committee.models import Evidence, Run

if TYPE_CHECKING:  # pragma: no cover - typing only; the spacy import stays lazy at runtime
    from spacy.language import Language

# Typographic characters that appear in scraped news text, mapped to plain
# ASCII BEFORE the NFKD fallback below, so apostrophes and quotes survive
# normalization instead of being dropped.
_ASCII_REPLACEMENTS: dict[str, str] = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
    "\u00a0": " ",
}

_HTML_TAG = re.compile(r"<[^>]+>")

# Placeholder taxonomy for classify(). One category per broad driver of a
# price move; "general" is the fallback. The keyword lists are intentionally
# small: this stage is scheduled to become a model call later in the course.
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "earnings": ("earnings", "revenue", "profit", "quarter", "guidance", "eps"),
    "product": ("launch", "product", "unveil", "release", "feature"),
    "legal": ("lawsuit", "regulator", "antitrust", "settlement", "investigation"),
    "market": ("shares", "stock", "downgrade", "upgrade", "price target", "analyst"),
}


class RawArticle(BaseModel):
    """One news article as it arrives from a source or a saved fixture."""

    article_id: str
    symbol: str
    source: str
    published: str
    title: str
    body: str


class Entity(BaseModel):
    """One named entity found in an article's cleaned text."""

    text: str
    label: str
    start: int
    end: int


class ProcessedArticle(BaseModel):
    """An article after the full chain: cleaned, classified, tagged, summarized.

    ``accepted`` records the decision made by the classification gate.  Keeping
    the gate decision in the processed object makes the handoff auditable and
    lets the evaluation notebook count rejected news without re-running NLP.
    """

    article: RawArticle
    clean_text: str
    category: str
    accepted: bool
    gate_reason: str
    entities: list[Entity]
    summary: str


def ingest(path: str | Path) -> list[RawArticle]:
    """Load articles from a JSON file of saved samples.

    Args:
        path: A JSON file holding a list of article objects with the
            RawArticle fields.

    Returns:
        The articles in file order, validated into RawArticle models.

    Raises:
        FileNotFoundError: If the file does not exist.
        pydantic.ValidationError: If an object is missing a required field.
    """
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    return [RawArticle(**record) for record in records]


def clean_text(text: str) -> str:
    """Return one article text cleaned for the downstream stages.

    Four edits, in order: drop HTML tags, map typographic characters to their
    ASCII equivalents, NFKD-normalize and drop what still does not encode
    (accented letters fall back to their base letter), and collapse
    whitespace runs.

    Args:
        text: Raw article text, possibly containing HTML and Unicode
            typography.

    Returns:
        Plain ASCII text with single spaces.
    """
    text = _HTML_TAG.sub(" ", text)
    for bad, good in _ASCII_REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", errors="ignore").decode("ascii")
    return " ".join(text.split())


def preprocess(articles: list[RawArticle]) -> list[tuple[RawArticle, str]]:
    """Clean every article and drop exact duplicates and empty bodies.

    Duplicates are detected on the cleaned, lowercased title plus body, so
    the same wire story picked up twice with different whitespace or HTML
    still counts as one.

    Args:
        articles: Ingested articles.

    Returns:
        (article, clean_text) pairs, first occurrence kept, input order
        preserved.
    """
    seen: set[str] = set()
    kept: list[tuple[RawArticle, str]] = []
    for article in articles:
        cleaned = clean_text(article.body)
        if not cleaned:
            continue
        fingerprint = (clean_text(article.title) + " " + cleaned).lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        kept.append((article, cleaned))
    return kept


def classify(text: str) -> str:
    """Assign one coarse category to a cleaned article text.

    Placeholder implementation: the first category whose keyword list
    matches, in _CATEGORY_KEYWORDS order, with "general" as the fallback.
    Scheduled to become a model-based classifier once the course covers it;
    the signature stays.

    Args:
        text: Cleaned article text from preprocess().

    Returns:
        One of the _CATEGORY_KEYWORDS categories or "general".
    """
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "general"


# Categories that are considered actionable for the investment evidence pool.
# ``general`` remains useful for diagnostics, but it is not promoted to shared
# Evidence by default because the classifier did not identify an investment
# driver.  The tuple is deliberately explicit so a future model can replace
# ``classify()`` without changing the gate contract.
_GATE_CATEGORIES: frozenset[str] = frozenset(_CATEGORY_KEYWORDS)


def classification_gate(category: str) -> tuple[bool, str]:
    """Decide whether a classified article may continue through the chain.

    The gate sits immediately after ``classify()``.  Known investment-driver
    categories continue; ``general`` and unknown labels are stopped.  The
    decision and reason are returned together so downstream code can explain
    why an article was or was not promoted to Evidence.

    Args:
        category: Label returned by ``classify()``.

    Returns:
        ``(accepted, reason)``.  Accepted articles get a short audit reason;
        rejected articles identify the category that failed the gate.
    """
    normalized = category.strip().casefold()
    if normalized in _GATE_CATEGORIES:
        return True, f"accepted classification: {normalized}"
    return False, f"rejected classification: {normalized or 'empty'}"


def load_nlp() -> Language:
    """Load the small English spaCy pipeline for entity extraction.

    Kept in its own function so tests and CI can inject a lightweight
    pipeline instead: downloading the model needs the network, and tests do
    not touch the network.

    Returns:
        The en_core_web_sm pipeline.

    Raises:
        RuntimeError: If the model is not installed, with the install
            command in the message.
    """
    import spacy

    try:
        return spacy.load("en_core_web_sm")  # pragma: no cover - needs the model on disk
    except OSError as error:  # pragma: no cover - needs the model absent
        raise RuntimeError(
            "spaCy model en_core_web_sm is not installed. Run: "
            ".venv/bin/python -m spacy download en_core_web_sm"
        ) from error


def extract(text: str, nlp: Language) -> list[Entity]:
    """Find named entities in a cleaned article text.

    Args:
        text: Cleaned article text from preprocess().
        nlp: A spaCy pipeline with an entity recognizer (load_nlp() for the
            real one; tests pass a blank pipeline with an entity ruler).

    Returns:
        Entities in document order, with character offsets into text.
    """
    doc = nlp(text)
    return [
        Entity(text=ent.text, label=ent.label_, start=ent.start_char, end=ent.end_char)
        for ent in doc.ents
    ]


def summarize(text: str, max_sentences: int = 2) -> str:
    """Return a short extractive summary of a cleaned article text.

    Placeholder implementation: the first max_sentences sentences, split on
    sentence-ending punctuation. Scheduled to become a model-based
    summarizer later in the course; the signature stays.

    Args:
        text: Cleaned article text from preprocess().
        max_sentences: How many leading sentences to keep.

    Returns:
        The leading sentences joined with single spaces.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(sentences[:max_sentences]).strip()


def run_chain(articles: list[RawArticle], nlp: Language) -> list[ProcessedArticle]:
    """Run ingest output through preprocess, classify, gate, extract, summarize.

    The gate is evaluated immediately after classification.  For backwards
    compatibility with the Sep 15 chain, NER and summarization still run for
    every surviving preprocessed article; the gate controls promotion into the
    shared Evidence pool rather than deleting an article from the chain output.

    Args:
        articles: Ingested articles from the live news tool or a fixture.
        nlp: The spaCy pipeline used by ``extract()``.

    Returns:
        One ``ProcessedArticle`` for every article that survives preprocessing.
        Rejected articles remain in the result with ``accepted=False`` so the
        evaluation code can measure the gate instead of silently losing them.
    """
    processed: list[ProcessedArticle] = []
    for article, cleaned in preprocess(articles):
        category = classify(cleaned)
        accepted, gate_reason = classification_gate(category)

        # The gate sits after classification.  We still finish the original
        # chain for compatibility and auditability; processed_to_evidence()
        # enforces the gate at the shared-model boundary.
        entities = extract(cleaned, nlp)
        summary = summarize(cleaned)

        processed.append(
            ProcessedArticle(
                article=article,
                clean_text=cleaned,
                category=category,
                accepted=accepted,
                gate_reason=gate_reason,
                entities=entities,
                summary=summary,
            )
        )
    return processed


def processed_to_evidence(run: Run, articles: list[ProcessedArticle]) -> list[Evidence]:
    """Convert accepted news-chain output into the project's shared Evidence model.

    This is the ownership boundary between the news chain and the rest of the
    investment committee.  The chain owns article processing; the shared
    ``Evidence`` model is the contract consumed by Bull, Bear, and Evaluator.

    Each accepted article becomes one evidence item.  The evidence content is
    the chain's extractive summary, while the original title and source URL or
    provider identifier remain available in the title/reference fields.

    Args:
        run: Shared run record that owns the evidence.
        articles: Output from ``run_chain()``.

    Returns:
        Evidence records for accepted articles about run.symbol only.
    """
    evidence: list[Evidence] = []
    for item in articles:
        if not item.accepted:
            continue
        # Do not file another company's article under this run's symbol.
        if item.article.symbol != run.symbol:
            continue

        evidence.append(
            Evidence(
                run_id=run.run_id,
                symbol=run.symbol,
                source="news",
                title=item.article.title,
                content=item.summary or item.clean_text,
                as_of=item.article.published,
                reference=item.article.source,
            )
        )
    return evidence
