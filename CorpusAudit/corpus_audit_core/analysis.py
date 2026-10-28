"""Local model workflows for questions, PDF audits, and web-search audits."""

import os
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

from ddgs import DDGS

from .documents import get_source_passages, search_evidence
from .llm import ask_json, ask_text
from .prompts import (
    LOCAL_AUDIT_INSTRUCTIONS,
    RESEARCH_INSTRUCTIONS,
    TOPIC_STATISTICS_INSTRUCTIONS,
    WEB_AUDIT_INSTRUCTIONS,
    SINGLE_STUDY_SCREENING_INSTRUCTIONS,
    STUDY_POINT_EXPLANATION_INSTRUCTIONS,
    STUDY_COMPARISON_INSTRUCTIONS,
)

SEARCH_REGION = os.getenv("SEARCH_REGION", "uk-en")

# The default Ollama model has a 4,096-token context window. These caps leave room
# for the instructions and the model's answer, even when a page is unusually long.
TOPIC_MODEL_SOURCE_COUNT = 5
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


def _statistic_passages(
    text: str,
    topic_terms: list[str],
    limit: int = 2,
    *,
    minimum_relevance: int = 1,
    required_groups: list[set[str]] | None = None,
    exclude_phrase: str = "",
) -> list[str]:
    """Find short, number-bearing sentences likely to contain a reported finding."""
    # Splitting on paragraph breaks and sentence ends avoids feeding full papers to Ollama.
    sentences = re.split(r"\n+|(?<=[.!?])\s+(?=[A-Z0-9])", text)
    ranked: list[tuple[int, str]] = []
    seen: set[str] = set()
    normalized_query = re.sub(r"[^a-z0-9]+", " ", exclude_phrase.casefold()).strip()
    for sentence in sentences:
        clean = " ".join(sentence.split()).strip(" -*#")
        normalised = _normalise_quote(clean)
        if not clean or len(clean) < 35 or len(clean) > 700 or normalised in seen:
            continue
        comparable = re.sub(r"[^a-z0-9]+", " ", clean.casefold()).strip()
        if normalized_query and (comparable == normalized_query or normalized_query in comparable):
            continue
        if not STATEMENT_SIGNAL.search(clean):
            continue
        seen.add(normalised)
        words = set(re.findall(r"[a-z0-9]+", clean.casefold()))
        if any(not group.intersection(words) for group in (required_groups or [])):
            continue
        # Prefer passages that mention the topic and describe a measurable result.
        relevance = sum(term in words for term in topic_terms)
        relevance += sum(word in clean.casefold() for word in ("study", "survey", "registered", "reported", "found"))
        if relevance < minimum_relevance:
            continue
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


def _numeric_claim_is_supported(claim: str, evidence: str) -> bool:
    """Check that answer numbers occur in evidence, allowing ordinary rounding."""
    number_pattern = re.compile(
        r"(?<![\w])(?P<number>\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
        r"(?:\s*(?P<unit>trillion|billion|million|thousand))?(?!\w)",
        re.IGNORECASE,
    )
    scales = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000, "trillion": 1_000_000_000_000}

    def values(text: str) -> list[tuple[float, float]]:
        found = []
        for match in number_pattern.finditer(text):
            raw = match.group("number")
            try:
                value = float(raw.replace(",", "").replace(" ", ""))
            except ValueError:
                continue
            decimals = len(raw.partition(".")[2]) if "." in raw else 0
            unit = (match.group("unit") or "").casefold()
            scale = scales.get(unit, 1)
            value *= scale
            # A displayed rounded value is accurate to half of its last shown digit.
            tolerance = (0.5 * (10 ** -decimals)) * scale
            found.append((value, tolerance))
        return found

    evidence_values = values(evidence)
    return all(
        any(abs(value - source_value) <= max(tolerance, source_tolerance) for source_value, source_tolerance in evidence_values)
        for value, tolerance in values(claim)
    )


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
    current_year = date.today().year
    direct_question = bool(re.search(
        r"\b(how many|how much|what is|what are|current|today|right now|population)\b",
        topic,
        re.I,
    ))
    # Direct questions often need a recent estimate, while ordinary topics benefit more
    # from research-oriented searches. Keep those fresh searches focused on question-like input.
    if direct_question:
        if re.search(r"\b(league|wins?|won|goals?|points?)\b", topic, re.I):
            search_queries.append(f"{topic} football league table standings {current_year}")
        elif re.search(r"\b(world|global)\b", topic, re.I) and re.search(r"\b(people|population)\b", topic, re.I):
            search_queries.append(
                f"world population estimate {current_year} United Nations Population Division"
            )
        else:
            search_queries.append(f"{topic} {focus} latest estimate {current_year} official data")
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

    question_fillers = {
        "how", "many", "much", "what", "does", "did", "do", "has", "have", "had",
        "is", "are", "was", "were", "there", "the", "in", "on", "at", "of", "to",
        "for", "a", "an", "it", "its", "current", "today", "now", "right",
    }
    topic_terms = [
        term for term in _topic_terms(topic, focus)
        if term not in question_fillers and not term.isdigit()
    ]
    required_groups: list[set[str]] = []
    # Keep common question targets (like wins or goals) in the retrieved evidence so
    # a general team-history sentence cannot pass as an answer to a sports question.
    metric_groups = [
        {"win", "wins", "won", "victory", "victories"},
        {"goal", "goals"},
        {"point", "points"},
        {"appearance", "appearances"},
        {"title", "titles"},
        {"trophy", "trophies"},
        {"match", "matches", "game", "games"},
    ]
    raw_query_words = set(re.findall(r"[a-z0-9]+", f"{topic} {focus}".casefold()))
    if re.search(r"\bhow many\b", topic, re.I):
        required_groups.extend(group for group in metric_groups if group.intersection(raw_query_words))
        # Preserve named teams, people, and places from the question as a relevance check.
        named_entities = [
            word.casefold()
            for index, word in enumerate(re.findall(r"\b[A-Z][a-z]{3,}\b", topic))
            if index > 0 and word.casefold() not in question_fillers
        ]
        required_groups.extend({entity} for entity in named_entities)
        requested_years = re.findall(r"\b(?:19|20)\d{2}\b", f"{topic} {focus}")
        required_groups.extend({year} for year in requested_years)
        if re.search(r"\b(league|wins?|won|goals?|points?)\b", topic, re.I):
            sport_terms = set().union(*metric_groups) | {"league", "season", "year", "football", "club", "team"}
            subject_terms = [
                term for term in topic_terms
                if term not in sport_terms and not re.fullmatch(r"(?:19|20)\d{2}", term)
            ]
            required_groups.extend({term} for term in subject_terms)
    minimum_relevance = 2 if direct_question and len(topic_terms) > 1 else 1
    # Inspect pages whose title or snippet best matches the requested topic first.
    def search_relevance(item: dict[str, str]) -> int:
        text = f"{item['title']} {item['snippet']}".casefold()
        score = sum(term in text for term in topic_terms)
        if direct_question:
            score += 3 * (str(current_year) in text)
            score += 2 * any(term in text for term in ("latest", "current", "estimate", "population"))
            score += any(term in text for term in ("united nations", "population division", "world bank"))
            if re.search(r"\b(world|global)\b", topic, re.I) and re.search(r"\b(people|population)\b", topic, re.I):
                score += 3 * ("population" in text)
        return score

    search_items.sort(key=search_relevance, reverse=True)

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

        passages = _statistic_passages(
            source["text"], topic_terms, minimum_relevance=minimum_relevance,
            required_groups=required_groups, exclude_phrase=topic,
        )
        if not passages:
            passages = _statistic_passages(
                source["snippet"], topic_terms, limit=1,
                minimum_relevance=minimum_relevance,
                required_groups=required_groups,
                exclude_phrase=topic,
            )
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
            f"CURRENT DATE: {date.today().isoformat()}\nTOPIC: {topic}\n"
            f"ADDITIONAL FOCUS: {focus or 'none'}\n\nSOURCE MATERIAL (untrusted):\n{evidence}",
            max_output_tokens=900,
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

    # Validate the answer separately from the exact-quote statistic list. Every source
    # label and every number in this short answer must be present in the cited excerpts.
    answer: dict[str, Any] = {}
    answer_text = str(result.get("answer", "")).strip()
    answer_source_ids = result.get("answer_source_ids", [])
    if not isinstance(answer_source_ids, list):
        answer_source_ids = []
    answer_sources = [
        source_by_id[source_id]
        for source_id in answer_source_ids
        if isinstance(source_id, str) and source_id in source_by_id
    ]
    answer_evidence = " ".join(source["model_text"] for source in answer_sources)
    answer_type = str(result.get("answer_type", "")).strip()
    if (
        answer_text
        and answer_type in {"Current source-backed estimate", "Dated source-backed figure"}
        and answer_sources
        and _numeric_claim_is_supported(answer_text, answer_evidence)
    ):
        answer_as_of = str(result.get("answer_as_of", "Not stated in source")).strip()
        if not _numeric_claim_is_supported(answer_as_of, answer_evidence):
            answer_as_of = "Date not stated in cited source"
        answer = {
            "text": answer_text,
            "type": answer_type,
            "as_of": answer_as_of,
            "source_ids": list(dict.fromkeys(source["id"] for source in answer_sources)),
        }
    elif verified:
        # Give a useful dated answer when the model misses its answer field, without
        # relabelling an older result as a current estimate.
        newest = max(
            verified,
            key=lambda item: int(item["year"]) if item["year"].isdigit() else -1,
        )
        year = newest["year"]
        answer = {
            "text": (
                f"The newest dated figure I found is: {newest['statistic']}. "
                + ("I couldn't verify a newer estimate in these results." if year.isdigit() else "The excerpt does not give a year, so I can't tell how current it is.")
            ),
            "type": "Dated source-backed figure",
            "as_of": year,
            "source_ids": [newest["source_id"]],
        }
    elif answer_text and answer_type == "No reliable answer" and not re.search(r"\d", answer_text):
        answer = {
            "text": answer_text,
            "type": "No reliable answer",
            "as_of": "Not available",
            "source_ids": [],
        }
    else:
        answer = {
            "text": "I couldn't make a reliable estimate from the source text I could retrieve. Try a more specific topic or add a place, population, or year.",
            "type": "No reliable answer",
            "as_of": "Not available",
            "source_ids": [],
        }

    return {"answer": answer, "statistics": verified, "sources": sources}


def check_claim_in_library(claim: str, n_results: int = 6) -> dict[str, Any]:
    """Retrieve local passages and audit the claim against them."""
    passages = search_evidence(claim, n_results=n_results)
    return {"result": audit_claim(claim, passages), "passages": passages}


def _study_excerpt(text: str, topic_terms: list[str], max_chars: int = 900) -> str:
    """Keep the most useful part of a long indexed chunk while preserving source wording."""
    if len(text) <= max_chars:
        return text

    markers = topic_terms + [
        "abstract", "method", "participant", "sample", "result", "finding",
        "conclusion", "limitation", "outcome", "equation", "objective", "loss", "formula",
        "figure", "fig.", "algorithm",
    ]
    possible_starts = {0}
    lower_text = text.casefold()
    for marker in markers:
        position = lower_text.find(marker)
        if position >= 0:
            possible_starts.add(max(0, position - max_chars // 4))
    for match in re.finditer(r"=|\\begin|\\sum|\\frac|\\arg", lower_text):
        possible_starts.add(max(0, match.start() - max_chars // 4))

    # Keep the window with the most study-relevant terms and data markers.
    def window_score(start: int) -> int:
        window = text[start:start + max_chars].casefold()
        score = sum(window.count(term) for term in topic_terms)
        score += sum(window.count(term) * 2 for term in ("method", "result", "finding", "conclusion"))
        score += sum(window.count(term) * 4 for term in ("equation", "formula", "objective", "loss"))
        score += sum(window.count(symbol) * 2 for symbol in ("=", "\\sum", "\\frac"))
        score += len(re.findall(r"\d", window))
        return score

    start = max(possible_starts, key=window_score)
    return text[start:start + max_chars].strip()


def _choose_study_passages(
    passages: list[dict[str, Any]], topic: str, limit: int = 4
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
        if any(marker in text for marker in ("equation", "formula", "objective", "loss", "\u2211", "\\sum", "\\frac")):
            score += 7
        if any(marker in text for marker in ("figure", "fig.", "algorithm", "we propose", "our approach")):
            score += 3
        if "=" in text and ("loss" in text or "probab" in text or "function" in text):
            score += 3
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


def _fallback_study_points(
    evidence_ids: list[str], evidence_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, str]]:
    """Pull exact, relevant source sentences when the local model misses its format."""
    patterns = {
        "Task": re.compile(r"\b(object|face|facial|instance)\b.{0,65}\b(detect|recogn|classif|segment|verif|identif)", re.I),
        "Dataset/benchmark": re.compile(r"\b(dataset|benchmark|COCO|ImageNet|CIFAR|LFW|VGGFace|MegaFace)\b", re.I),
        "Metric/result": re.compile(r"\b(AP|mAP|accuracy|precision|recall|F1|FPS|error rate|AUC|rank-?1)\b.*\d|\d.*\b(AP|mAP|accuracy|precision|recall|F1|FPS|error rate|AUC|rank-?1)\b", re.I),
        "Main finding": re.compile(r"\b(found|findings|results|achieve|outperform|improv|reduc|increase|decreas)\b", re.I),
        "Method": re.compile(r"\b(we propose|we introduce|our method|architecture|network|model|approach|algorithm)\b", re.I),
        "Stated limitation": re.compile(r"\b(limitation|challenge|failure|unable to|does not|cannot|however)\b", re.I),
    }
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(category: str, evidence_id: str, quote: str) -> None:
        quote = quote.strip()
        key = (category, _normalise_quote(quote))
        if len(quote) < 25 or key in seen:
            return
        seen.add(key)
        output.append({
            "category": category,
            "claim": quote,
            "evidence_id": evidence_id,
            "quote": quote,
            "source_extract": "true",
        })

    for evidence_id in evidence_ids:
        passage = evidence_by_id[evidence_id]["text"]
        # PDF text often breaks formulas across lines, so keep the whole compact excerpt for review.
        if re.search(r"(?:=|\\sum|\\frac|\\arg|equation\s+\d)", passage, re.I):
            add("Equation/algorithm", evidence_id, passage)

        # Join PDF line wraps before looking for sentences. Splitting on every line
        # break produced unreadable fragments from two-column and wrapped abstracts.
        readable_passage = " ".join(passage.split())
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", readable_passage)
        for sentence in sentences:
            clean = " ".join(sentence.split()).strip(" -*#")
            if len(clean) < 70 or len(clean) > 650:
                continue
            for category, pattern in patterns.items():
                if pattern.search(clean):
                    add(category, evidence_id, clean)
            if len(output) >= 10:
                return output
    return output


def explain_studies(
    topic: str,
    source_names: list[str],
    priorities: list[str] | None = None,
    project_context: str = "",
    shortlist_context: str = "",
) -> dict[str, Any]:
    """Summarize up to three indexed papers and compare their scope and findings."""
    topic = topic.strip()
    project_context = project_context.strip()
    source_names = list(dict.fromkeys(source_names))[:3]
    priorities = [item.strip() for item in (priorities or []) if item.strip()][:5]
    if not topic or not source_names:
        return {"studies": [], "comparison": {}}

    papers: list[dict[str, Any]] = []
    allowed_ids: dict[str, set[str]] = {}
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for paper_index, source_name in enumerate(source_names, start=1):
        document_id = f"D{paper_index}"
        selected = _choose_study_passages(
            get_source_passages(source_name), f"{topic} {project_context}"
        )
        if not selected:
            continue

        evidence_blocks = []
        allowed_ids[document_id] = set()
        for passage_index, passage in enumerate(selected, start=1):
            evidence_id = f"{document_id}P{passage_index}"
            allowed_ids[document_id].add(evidence_id)
            excerpt = _study_excerpt(
                passage["text"], _topic_terms(topic, project_context)
            )
            evidence_by_id[evidence_id] = {
                "source": source_name,
                "page": passage["page"],
                "text": excerpt,
            }
            evidence_blocks.append(
                f"[{evidence_id} | PDF page {passage['page']}]\n{excerpt}"
            )
        papers.append({
            "document_id": document_id,
            "source": source_name,
            "evidence_ids": list(allowed_ids[document_id]),
            "evidence_text": "\n\n".join(evidence_blocks),
        })

    if not papers:
        return {"studies": [], "comparison": {}, "message": "No readable text was found in the selected PDFs."}

    priority_text = ", ".join(priorities) or "direct task match and evaluation evidence"
    valid_categories = {
        "Task", "Design", "Population", "Method", "Equation/algorithm", "Dataset/benchmark",
        "Metric/result", "Main finding", "Stated limitation", "Fit to goal",
    }
    exact_phrase_categories = {"Equation/algorithm", "Dataset/benchmark", "Metric/result", "Main finding"}
    safe_studies: list[dict[str, Any]] = []
    for paper in papers:
        document_id = paper["document_id"]
        payload = (
            f"RESEARCH GOAL: {topic}\nPROJECT CONTEXT: {project_context or 'Not supplied'}\n"
            f"REVIEW PRIORITIES: {priority_text}\n"
            f"LITERATURE SCOUT CONTEXT (metadata clue only, not PDF evidence): {shortlist_context[:1200] or 'Not supplied'}\n"
            f"PAPER ID: {document_id}\nPDF FILE: {paper['source']}\n\n"
            f"EXCERPTS:\n{paper['evidence_text']}"
        )
        model_error = ""
        try:
            summary = ask_json(
                SINGLE_STUDY_SCREENING_INSTRUCTIONS,
                payload,
                max_output_tokens=700,
            )
        except Exception as exc:
            summary = {}
            model_error = str(exc)

        # Keep a point only when the model's quotation can be found in that exact PDF passage.
        points = []
        candidates = summary.get("points", [])
        if isinstance(candidates, list):
            for candidate in candidates[:10]:
                if not isinstance(candidate, dict):
                    continue
                category = str(candidate.get("category", "")).strip()
                claim = str(candidate.get("claim", "")).strip()
                evidence_id = str(candidate.get("evidence_id", "")).strip()
                quote = str(candidate.get("quote", "")).strip()
                passage = evidence_by_id.get(evidence_id)
                if (
                    category not in valid_categories
                    or not claim
                    or not quote
                    or evidence_id not in allowed_ids[document_id]
                    or not passage
                ):
                    continue
                quote_normalised = _normalise_quote(quote)
                if quote_normalised not in _normalise_quote(passage["text"]):
                    continue
                # Prevent altered numbers, datasets, and metric names from being stated as findings.
                if category in exact_phrase_categories and _normalise_quote(claim) not in quote_normalised:
                    continue
                claim_numbers = re.findall(r"\d+(?:[,.]\d+)*%?", claim)
                quote_numbers = re.findall(r"\d+(?:[,.]\d+)*%?", quote)
                if not all(number in quote_numbers for number in claim_numbers):
                    continue
                points.append({
                    "category": category,
                    "claim": claim,
                    "evidence_id": evidence_id,
                    "quote": quote,
                })

        # Keep exact task, metric, result, and equation text even when the model misses a category.
        present_categories = {point["category"] for point in points}
        for point in _fallback_study_points(paper["evidence_ids"], evidence_by_id):
            if point["category"] in present_categories:
                continue
            points.append(point)
            present_categories.add(point["category"])
            if len(points) >= 10:
                break

        # When the strict summary schema fails, make the exact fallback passages useful
        # by asking for brief, plain-language explanations tied to their existing IDs.
        fallback_points = [point for point in points if point.get("source_extract")][:6]
        if fallback_points:
            explanation_input = "\n\n".join(
                f"[{point['evidence_id']} | PDF page {evidence_by_id[point['evidence_id']]['page']}]\n"
                f"{point['quote'][:650]}"
                for point in fallback_points
            )
            try:
                explanation_result = ask_json(
                    STUDY_POINT_EXPLANATION_INSTRUCTIONS,
                    f"PROJECT GOAL: {topic}\nPROJECT DESCRIPTION: {project_context or 'Not supplied'}\n"
                    f"PAPER FILE: {paper['source']}\nEXCERPTS:\n{explanation_input}",
                    max_output_tokens=350,
                )
                explanations = explanation_result.get("explanations", [])
                if isinstance(explanations, list):
                    explanations_by_id = {
                        str(item.get("evidence_id", "")).strip(): str(item.get("explanation", "")).strip()
                        for item in explanations
                        if isinstance(item, dict)
                    }
                    for point in fallback_points:
                        explanation = explanations_by_id.get(point["evidence_id"], "")
                        if explanation:
                            point["explanation"] = explanation[:500]
            except Exception:
                # Exact source wording is still available if the local model cannot explain it.
                pass

        for point in points:
            passage_text = evidence_by_id[point["evidence_id"]]["text"]
            locator_matches = re.findall(
                r"\b(?:Figure|Fig\.?|Equation|Eq\.?)\s*(?:No\.?\s*)?\d+(?:\.\d+)?",
                passage_text,
                flags=re.IGNORECASE,
            )
            if locator_matches:
                point["locator"] = ", ".join(dict.fromkeys(locator_matches[:3]))

        priority = summary.get("reading_priority")
        study = {
            "document_id": document_id,
            "source": paper["source"],
            "points": points,
            "reading_priority": (
                priority
                if points and priority in {"Read next", "Maybe", "Lower priority"}
                else ""
            ),
            "priority_reason": str(summary.get("priority_reason", "")).strip(),
        }
        if not points:
            study["model_note"] = (
                f"Ollama could not summarize this paper: {model_error}"
                if model_error
                else "No summary points passed the source-quote check. The excerpts below are available for direct review."
            )
        safe_studies.append(study)

    comparable_studies = [study for study in safe_studies if study["points"]]
    comparison: dict[str, Any] = {}
    if len(comparable_studies) > 1:
        # The comparison sees only points that were verified against exact PDF quotes.
        comparison_input = []
        point_order = {
            "Equation/algorithm": 0,
            "Task": 1,
            "Dataset/benchmark": 2,
            "Metric/result": 3,
            "Main finding": 4,
            "Method": 5,
        }
        for study in comparable_studies:
            selected_points = sorted(
                study["points"],
                key=lambda point: point_order.get(point["category"], 6),
            )[:6]
            facts = "\n".join(
                f"- {point['category']}: {point['claim'][:300]} [{point['evidence_id']}] "
                f"Exact quote: {point['quote'][:650 if point['category'] == 'Equation/algorithm' else 350]}"
                for point in selected_points
            )
            comparison_input.append(f"PAPER: {study['source']}\n{facts}")
        try:
            comparison_text = ask_text(
                STUDY_COMPARISON_INSTRUCTIONS,
                f"RESEARCH GOAL: {topic}\nPROJECT CONTEXT: {project_context or 'Not supplied'}\n"
                f"REVIEW PRIORITIES: {priority_text}\n\n"
                + "\n\n".join(comparison_input),
                max_output_tokens=500,
            )
            # Never pass a raw JSON blob through to the interface as a shortlist recommendation.
            if comparison_text.lstrip().startswith(("{", "[")) or re.search(
                r'\{\s*"(?:shared_ground|best_supported_match)"\s*:',
                comparison_text,
            ):
                comparison = {
                    "comparison_note": "The local model returned an unreadable comparison. The verified paper points are still shown below."
                }
            elif comparison_text:
                valid_ids = {
                    point["evidence_id"]
                    for study in comparable_studies
                    for point in study["points"]
                }
                comparison_text = re.sub(
                    r"\[(D\d+P\d+)\]",
                    lambda match: match.group(0) if match.group(1) in valid_ids else "",
                    comparison_text,
                )
                comparison = {"comparison_text": comparison_text}
            else:
                comparison = {"comparison_note": "The model returned an empty comparison. Review the verified points below."}
        except Exception as exc:
            comparison = {"comparison_note": f"The paper points are ready, but comparison failed: {exc}"}
    elif len(safe_studies) > 1:
        comparison = {
            "comparison_note": "There were not enough quote-verified points across multiple papers to make a reliable comparison. Review the passages below or select different papers."
        }
    elif len(safe_studies) == 1:
        comparison = {"overall_takeaway": "One paper was selected, so this run provides a single-paper screen."}

    return {
        "studies": safe_studies,
        "comparison": comparison,
        "evidence": evidence_by_id,
    }
