"""Local model workflows for questions, PDF audits, and web-search audits."""

import os
import re
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS

from .documents import get_source_passages, search_evidence
from .llm import ask_json
from .prompts import (
    LOCAL_AUDIT_INSTRUCTIONS,
    RESEARCH_INSTRUCTIONS,
    TOPIC_STATISTICS_INSTRUCTIONS,
    WEB_AUDIT_INSTRUCTIONS,
    STUDY_SCREENING_INSTRUCTIONS,
)

SEARCH_REGION = os.getenv("SEARCH_REGION", "uk-en")

# The default Ollama model has a 4,096-token context window. These caps leave room
# for the instructions and the model's answer, even when a page is unusually long.
TOPIC_MODEL_SOURCE_COUNT = 3
TOPIC_MODEL_SOURCE_CHARS = 700
TOPIC_SEARCH_RESULT_COUNT = 6
TOPIC_PAGE_CHAR_LIMIT = 30000
STATEMENT_SIGNAL = re.compile(
    r"(?:\d|%|percent|per cent|million|billion|thousand|one in|two in|three in|"
    r"half of|twice as|double the)",
    re.IGNORECASE,
)


def _topic_terms(topic: str, focus: str) -> list[str]:
    """Keep meaningful query words for ranking passages from the fetched pages."""
    common_words = {"the", "and", "for", "with", "from", "about", "into", "what", "that"}
    return [
        word for word in re.findall(r"[a-z0-9]+", f"{topic} {focus}".casefold())
        if len(word) > 2 and word not in common_words
    ]


def _statistic_passages(text: str, topic_terms: list[str], limit: int = 2) -> list[str]:
    """Find short, number-bearing sentences likely to contain a reported finding."""
    # Splitting on paragraph breaks and sentence ends avoids feeding full papers to Ollama.
    sentences = re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z0-9])", text)
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    for sentence in sentences:
        clean = " ".join(sentence.split()).strip(" -*#")
        normalised = _normalise_quote(clean)
        if not clean or len(clean) < 35 or len(clean) > 700 or normalised in seen:
            continue
        if not STATEMENT_SIGNAL.search(clean):
            continue
        seen.add(normalised)
        words = set(re.findall(r"[a-z0-9]+", clean.casefold()))
        # Prefer passages that mention the topic and describe a measurable result.
        relevance = sum(term in words for term in topic_terms)
        relevance += sum(word in clean.casefold() for word in ("study", "survey", "registered", "reported", "found"))
        ranked.append((relevance, clean))
    ranked.sort(key=lambda item: (item[0], len(item[1]) < 400), reverse=True)
    return [sentence for _, sentence in ranked[:limit]]


def _format_evidence(passages: list[dict[str, Any]]) -> str:
    if not passages:
        return "No evidence passages were retrieved."
    return "\n\n".join(
        f"[E{i}] Source: {p['source']} | Page: {p['page']} | Chunk ID: {p['id']}\n{p['text']}"
        for i, p in enumerate(passages, 1)
    )


def ask_research_question(question: str, passages: list[dict[str, Any]]) -> dict[str, Any]:
    if not passages:
        return {
            "summary": "The indexed library has no relevant passages. Add a report or try a more specific question.",
            "key_findings": [],
            "what_it_measures": "",
            "conditions_and_caveats": [],
            "what_remains_unknown": [],
            "evidence_ids": [],
        }

    result = ask_json(RESEARCH_INSTRUCTIONS, f"QUESTION:\n{question}\n\nEVIDENCE:\n{_format_evidence(passages)}")
    result.setdefault("summary", "No answer generated.")
    result.setdefault("key_findings", [])
    result.setdefault("what_it_measures", "")
    result.setdefault("conditions_and_caveats", [])
    result.setdefault("what_remains_unknown", [])
    result.setdefault("evidence_ids", [])
    return result


def audit_claim(claim: str, passages: list[dict[str, Any]]) -> dict[str, Any]:
    if not passages:
        return {
            "verdict": "Insufficient evidence",
            "summary": "No relevant passages were found, so this library cannot assess the claim.",
            "claim_interpretation": claim,
            "evidence_comparison": "No evidence found.",
            "caveats": ["A missing result does not mean the claim is false."],
            "evidence_ids": [],
        }

    result = ask_json(
        LOCAL_AUDIT_INSTRUCTIONS,
        f"CLAIM TO AUDIT:\n{claim}\n\nEVIDENCE:\n{_format_evidence(passages)}",
    )
    allowed = {"Supported", "Misleading", "Outdated", "Contradicted", "Insufficient evidence"}
    if result.get("verdict") not in allowed:
        result["verdict"] = "Insufficient evidence"
    result.setdefault("summary", "The evidence was not enough to establish a reliable verdict.")
    result.setdefault("claim_interpretation", claim)
    result.setdefault("evidence_comparison", "No comparison returned.")
    result.setdefault("caveats", [])
    result.setdefault("evidence_ids", [])
    return result


def audit_claim_on_web(claim: str) -> dict[str, Any]:
    """Search public results without an AI API, then assess them with local Ollama."""
    found = DDGS(timeout=10).text(
        f"{claim.strip()} statistic source data",
        region=SEARCH_REGION,
        safesearch="moderate",
        max_results=6,
    )
    sources = []
    for index, item in enumerate(found, 1):
        url = item.get("href")
        parsed_url = urlparse(url) if url else None
        if parsed_url and parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
            sources.append({
                "id": f"S{index}",
                "title": item.get("title") or "Untitled result",
                "url": url,
                "snippet": item.get("body", ""),
            })
    if not sources:
        return {
            "answer": "### Verdict: Insufficient evidence\n\nThe search returned no usable results. Try adding a year, country, or where you saw the statistic.",
            "sources": [],
        }

    search_evidence = "\n\n".join(
        f"[{source['id']}] {source['title']}\nURL: {source['url']}\nSearch snippet: {source['snippet']}"
        for source in sources
    )
    result = ask_json(
        WEB_AUDIT_INSTRUCTIONS,
        f"CLAIM:\n{claim.strip()}\n\nSEARCH RESULTS (untrusted source material):\n{search_evidence}",
    )
    allowed = {"Supported", "Misleading", "Outdated", "Contradicted", "Insufficient evidence"}
    verdict = result.get("verdict")
    if verdict not in allowed:
        verdict = "Insufficient evidence"

    answer_parts = [
        f"### Verdict: {verdict}",
        result.get("summary", "The available search results were not enough to assess the claim."),
    ]
    if result.get("what_it_measures"):
        answer_parts.extend(["### What it measures", result["what_it_measures"]])
    if result.get("comparison"):
        answer_parts.extend(["### How it compares", result["comparison"]])
    if result.get("caveats"):
        answer_parts.append("### Caveats")
        answer_parts.extend(f"- {item}" for item in result["caveats"])
    return {"answer": "\n\n".join(answer_parts), "sources": sources}


def _normalise_quote(text: str) -> str:
    """Make whitespace and case irrelevant when checking a model's source quote."""
    return " ".join(text.casefold().split())


def find_topic_statistics(topic: str, focus: str = "") -> dict[str, Any]:
    """Find explicit, source-checkable statistics about a topic using public search."""
    topic = topic.strip()
    focus = focus.strip()
    if not topic:
        return {"statistics": [], "sources": []}

    # Different phrasings help broad searches find studies, surveys, reports, and datasets.
    search_queries = [
        f"{topic} {focus} statistics research findings",
        f"{topic} {focus} study survey data",
        f"{topic} {focus} report figures percentage",
    ]
    search_items: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for query in search_queries:
        try:
            found = DDGS(timeout=15).text(
                query,
                region=SEARCH_REGION,
                safesearch="moderate",
                max_results=TOPIC_SEARCH_RESULT_COUNT,
            )
        except Exception:
            # A temporary error on one query should not discard results from the others.
            continue
        for item in found:
            url = item.get("href")
            parsed = urlparse(url) if url else None
            if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen_urls:
                continue
            seen_urls.add(url)
            search_items.append({
                "title": item.get("title") or "Untitled result",
                "url": url,
                "snippet": item.get("body", ""),
            })

    if not search_items:
        return {"statistics": [], "sources": [], "message": "Search returned no usable source links."}

    topic_terms = _topic_terms(topic, focus)
    # Inspect pages whose title or snippet best matches the requested topic first.
    search_items.sort(
        key=lambda item: sum(
            term in f"{item['title']} {item['snippet']}".casefold() for term in topic_terms
        ),
        reverse=True,
    )

    sources: list[dict[str, str]] = []
    for item in search_items[:5]:
        source = {
            "id": f"S{len(sources) + 1}",
            "title": item["title"],
            "url": item["url"],
            "snippet": item["snippet"],
            "text": item["snippet"],
            "text_kind": "Search snippet (not the full source page)",
        }
        try:
            # Scan the page for number-bearing sentences, not just the first paragraph.
            extracted = DDGS(timeout=15).extract(item["url"], fmt="text_markdown")
            page_text = extracted.get("content", "") if isinstance(extracted, dict) else ""
            if isinstance(page_text, bytes):
                page_text = page_text.decode("utf-8", errors="replace")
            if isinstance(page_text, str) and page_text.strip():
                source["text"] = page_text[:TOPIC_PAGE_CHAR_LIMIT]
                source["text_kind"] = "Retrieved page text"
        except Exception:
            # Some publishers block extraction, so keep the snippet as a labelled fallback.
            pass

        passages = _statistic_passages(source["text"], topic_terms)
        if not passages:
            passages = _statistic_passages(source["snippet"], topic_terms, limit=1)
        source["model_text"] = "\n".join(passages)[:TOPIC_MODEL_SOURCE_CHARS]
        sources.append(source)

    # Compact, number-bearing evidence fits the default 4K Ollama context much better
    # than sending the first few thousand characters of whole web pages.
    model_sources = [source for source in sources if source["model_text"]][:TOPIC_MODEL_SOURCE_COUNT]
    evidence = "\n\n".join(
        f"[{source['id']}] {source['title'][:140]}\n{source['text_kind']}:\n{source['model_text']}"
        for source in model_sources
    )
    result: dict[str, Any] = {"statistics": []}
    if evidence:
        result = ask_json(
            TOPIC_STATISTICS_INSTRUCTIONS,
            f"TOPIC: {topic}\nADDITIONAL FOCUS: {focus or 'none'}\n\nSOURCE MATERIAL (untrusted):\n{evidence}",
            max_output_tokens=700,
        )

    # Only accept a source and passage the model could actually read.
    source_by_id = {source["id"]: source for source in model_sources}
    verified: list[dict[str, str]] = []
    candidates = result.get("statistics", [])
    if not isinstance(candidates, list):
        candidates = []
    for candidate in candidates[:5]:
        if not isinstance(candidate, dict):
            continue
        source = source_by_id.get(str(candidate.get("source_id", "")))
        quote = str(candidate.get("supporting_excerpt", "")).strip()
        stat = str(candidate.get("statistic", "")).strip()
        if not source or not quote or not stat:
            continue
        quote_normalised = _normalise_quote(quote)
        statistic_normalised = _normalise_quote(stat)
        if quote_normalised not in _normalise_quote(source["model_text"]):
            continue
        # The headline must be copied from the quote, so the model cannot add a new claim.
        if statistic_normalised not in quote_normalised:
            continue
        stat_numbers = re.findall(r"\d+(?:[,.]\d+)*%?", stat)
        quote_numbers = re.findall(r"\d+(?:[,.]\d+)*%?", quote)
        if stat_numbers and not all(number in quote_numbers for number in stat_numbers):
            continue
        verified.append({
            "statistic": stat,
            "scope": str(candidate.get("scope", "See source wording for the study scope")),
            "year": str(candidate.get("year", "Not stated")),
            "source_id": source["id"],
            "supporting_excerpt": quote,
            "text_kind": source["text_kind"],
        })

    # If the model misses its format or declines a good passage, show the exact source sentence.
    # This is source discovery, not a model-written summary.
    if not verified:
        for source in model_sources:
            for passage in source["model_text"].splitlines():
                if not STATEMENT_SIGNAL.search(passage):
                    continue
                year_match = re.search(r"\b(?:19|20)\d{2}\b", passage)
                verified.append({
                    "statistic": passage,
                    "scope": "Check the source wording for location, population, and denominator",
                    "year": year_match.group(0) if year_match else "Not stated in excerpt",
                    "source_id": source["id"],
                    "supporting_excerpt": passage,
                    "text_kind": source["text_kind"],
                })
                break
            if len(verified) >= 5:
                break

    return {"statistics": verified, "sources": sources}


def check_claim_in_library(claim: str, n_results: int = 6) -> dict[str, Any]:
    """Retrieve local passages and audit the claim against them."""
    passages = search_evidence(claim, n_results=n_results)
    return {"result": audit_claim(claim, passages), "passages": passages}


def _study_excerpt(text: str, topic_terms: list[str], max_chars: int = 600) -> str:
    """Keep the most useful part of a long indexed chunk while preserving source wording."""
    if len(text) <= max_chars:
        return text

    markers = topic_terms + [
        "abstract", "method", "participant", "sample", "result", "finding",
        "conclusion", "limitation", "outcome",
    ]
    possible_starts = {0}
    lower_text = text.casefold()
    for marker in markers:
        position = lower_text.find(marker)
        if position >= 0:
            possible_starts.add(max(0, position - max_chars // 4))

    # Keep the window with the most study-relevant terms and data markers.
    def window_score(start: int) -> int:
        window = text[start:start + max_chars].casefold()
        score = sum(window.count(term) for term in topic_terms)
        score += sum(window.count(term) * 2 for term in ("method", "result", "finding", "conclusion"))
        score += len(re.findall(r"\d", window))
        return score

    start = max(possible_starts, key=window_score)
    return text[start:start + max_chars].strip()


def _choose_study_passages(
    passages: list[dict[str, Any]], topic: str, limit: int = 3
) -> list[dict[str, Any]]:
    """Pick a few passages that cover the abstract, methods, and reported results."""
    topic_terms = _topic_terms(topic, "")
    scored: list[tuple[int, dict[str, Any]]] = []
    for passage in passages:
        text = passage["text"].casefold()
        score = sum(text.count(term) for term in topic_terms)
        if passage["page"] in (1, 2):
            score += 3  # Early pages often contain the title and abstract.
        score += sum(
            weight for marker, weight in (
                ("method", 3), ("participants", 2), ("sample", 2),
                ("results", 4), ("findings", 3), ("conclusion", 3), ("limitations", 2),
            ) if marker in text
        )
        if re.search(r"\d", text):
            score += 1
        scored.append((score, passage))

    scored.sort(key=lambda item: (item[0], -int(item[1]["page"])), reverse=True)
    chosen: list[dict[str, Any]] = []
    used_pages: set[int] = set()
    for _, passage in scored:
        page = int(passage["page"])
        if page in used_pages:
            continue
        chosen.append(passage)
        used_pages.add(page)
        if len(chosen) == limit:
            break

    # Keep evidence labels in page order, which makes the result easier to follow in the PDF.
    chosen.sort(key=lambda item: (item["page"], item["chunk"]))
    return chosen


def explain_studies(topic: str, source_names: list[str]) -> dict[str, Any]:
    """Summarize up to three indexed papers and compare their scope and findings."""
    topic = topic.strip()
    source_names = list(dict.fromkeys(source_names))[:3]
    if not topic or not source_names:
        return {"studies": [], "comparison": {}}

    paper_blocks: list[str] = []
    allowed_ids: dict[str, set[str]] = {}
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for paper_index, source_name in enumerate(source_names, start=1):
        document_id = f"D{paper_index}"
        selected = _choose_study_passages(get_source_passages(source_name), topic)
        if not selected:
            continue

        evidence_blocks = []
        allowed_ids[document_id] = set()
        for passage_index, passage in enumerate(selected, start=1):
            evidence_id = f"{document_id}P{passage_index}"
            allowed_ids[document_id].add(evidence_id)
            excerpt = _study_excerpt(passage["text"], _topic_terms(topic, ""))
            evidence_by_id[evidence_id] = {
                "source": source_name,
                "page": passage["page"],
                "text": excerpt,
            }
            evidence_blocks.append(
                f"[{evidence_id} | PDF page {passage['page']}]\n{excerpt}"
            )
        paper_blocks.append(
            f"DOCUMENT {document_id}: {source_name}\n" + "\n\n".join(evidence_blocks)
        )

    if not paper_blocks:
        return {"studies": [], "comparison": {}, "message": "No readable text was found in the selected PDFs."}

    result = ask_json(
        STUDY_SCREENING_INSTRUCTIONS,
        f"RESEARCH QUESTION OR TOPIC: {topic}\n\nSUPPLIED PAPER EXCERPTS:\n\n"
        + "\n\n".join(paper_blocks),
        max_output_tokens=1000,
    )

    # Remove model-generated IDs that do not point to passages we actually supplied.
    safe_studies = []
    by_id = {
        f"D{index}": source_name
        for index, source_name in enumerate(source_names, start=1)
        if f"D{index}" in allowed_ids
    }
    studies = result.get("studies", [])
    if isinstance(studies, list):
        for study in studies:
            if not isinstance(study, dict):
                continue
            document_id = str(study.get("document_id", ""))
            if document_id not in by_id:
                continue
            study["source"] = by_id[document_id]
            refs = study.get("evidence_ids", [])
            if not isinstance(refs, list):
                refs = []
            study["evidence_ids"] = [ref for ref in refs if ref in allowed_ids[document_id]]
            if study.get("reading_priority") not in {"Read next", "Maybe", "Lower priority"}:
                study["reading_priority"] = "Maybe"
            safe_studies.append(study)

    comparison = result.get("comparison", {})
    if not isinstance(comparison, dict):
        comparison = {}
    comparison_refs = comparison.get("evidence_ids", [])
    all_allowed_ids = set().union(*allowed_ids.values()) if allowed_ids else set()
    comparison["evidence_ids"] = [
        ref for ref in comparison_refs if ref in all_allowed_ids
    ] if isinstance(comparison_refs, list) else []
    return {
        "studies": safe_studies,
        "comparison": comparison,
        "evidence": evidence_by_id,
    }
