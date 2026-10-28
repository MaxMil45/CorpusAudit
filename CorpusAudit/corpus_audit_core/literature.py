"""Scholarly paper discovery and citation trails using public metadata APIs."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .prompts import CITATION_ROLE_INSTRUCTIONS, PAPER_MATCH_INSTRUCTIONS

OPENALEX_API = "https://api.openalex.org"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PROFILE_FILE = DATA_DIR / "literature_profiles.json"
WORK_FIELDS = (
    "id,doi,title,publication_year,publication_date,authorships,primary_location,"
    "best_oa_location,open_access,abstract_inverted_index,cited_by_count"
)


def _get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch one public scholarly API response and return its JSON body."""
    if params:
        url = f"{url}?{urlencode(params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "CorpusAudit/1.0 (local research tool)",
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("The paper index is rate-limiting requests. Wait briefly and try again.") from exc
        raise RuntimeError(f"The paper index returned HTTP {exc.code}.") from exc
    except (TimeoutError, URLError) as exc:
        raise RuntimeError("The paper index could not be reached. Check your internet connection and retry.") from exc
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The paper index returned unreadable data.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("The paper index returned an unexpected response.")
    return data


def _abstract_from_index(index: Any) -> str:
    """Rebuild OpenAlex's position-indexed abstract into readable text."""
    if not isinstance(index, dict):
        return ""
    words: dict[int, str] = {}
    for word, positions in index.items():
        if isinstance(positions, list):
            for position in positions:
                if isinstance(position, int):
                    words[position] = str(word)
    return " ".join(words[position] for position in sorted(words))


def _normalize_work(work: dict[str, Any]) -> dict[str, Any]:
    authorships = work.get("authorships") or []
    authors = [
        author.get("author", {}).get("display_name", "")
        for author in authorships
        if isinstance(author, dict) and isinstance(author.get("author"), dict)
    ]
    best_location = work.get("best_oa_location") or {}
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    doi = str(work.get("doi") or "")
    open_access = work.get("open_access") or {}
    return {
        "id": str(work.get("id") or work.get("doi") or work.get("title") or ""),
        "openalex_id": str(work.get("id") or ""),
        "title": str(work.get("title") or "Untitled paper"),
        "authors": authors,
        "year": work.get("publication_year"),
        "date": str(work.get("publication_date") or ""),
        "venue": str(source.get("display_name") or ""),
        "doi": doi,
        "doi_url": doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else ""),
        "url": str(best_location.get("landing_page_url") or primary_location.get("landing_page_url") or doi or work.get("id") or ""),
        "pdf_url": str(best_location.get("pdf_url") or ""),
        "is_oa": bool(open_access.get("is_oa")),
        "abstract": _abstract_from_index(work.get("abstract_inverted_index")),
        "citation_count": int(work.get("cited_by_count") or 0),
        "referenced_works": work.get("referenced_works") or [],
    }


def _works(query: str, *, page: int = 1, per_page: int = 20, year_from: int | None = None,
           open_access_only: bool = False, include_references: bool = False) -> dict[str, Any]:
    selected_fields = WORK_FIELDS + (",referenced_works" if include_references else "")
    params: dict[str, Any] = {
        "search": query, "per_page": per_page, "page": page, "select": selected_fields,
    }
    filters = []
    if year_from:
        filters.append(f"publication_year:{year_from}-{date.today().year}")
    if open_access_only:
        filters.append("open_access.is_oa:true")
    if filters:
        params["filter"] = ",".join(filters)
    return _get_json(f"{OPENALEX_API}/works", params)


def search_papers(query: str, *, page: int = 1, year_from: int | None = None,
                  open_access_only: bool = False) -> dict[str, Any]:
    """Search OpenAlex works by title/abstract text and return normalized records."""
    query = query.strip()
    if not query:
        return {"papers": [], "total": 0, "page": page}
    response = _works(query, page=page, year_from=year_from, open_access_only=open_access_only)
    results = response.get("results", [])
    return {
        "papers": [_normalize_work(work) for work in results if isinstance(work, dict)],
        "total": int((response.get("meta") or {}).get("count") or 0),
        "page": page,
    }


def find_seed_papers(query: str) -> list[dict[str, Any]]:
    """Find a small set of candidate seed papers by title or DOI."""
    query = query.strip()
    if not query:
        return []
    doi_match = re.search(r"10\.\d{4,9}/[^\s]+", query)
    if doi_match:
        doi = doi_match.group(0).rstrip(".,)")
        encoded = quote(f"https://doi.org/{doi}", safe="")
        work = _get_json(f"{OPENALEX_API}/works/{encoded}")
        return [_normalize_work(work)]
    response = _works(query, per_page=5, include_references=True)
    return [_normalize_work(work) for work in response.get("results", []) if isinstance(work, dict)]


def _fetch_openalex_ids(ids: list[str]) -> list[dict[str, Any]]:
    """Fetch a seed paper's references in one batched works request."""
    ids = [str(item).rsplit("/", 1)[-1] for item in ids if item]
    if not ids:
        return []
    response = _get_json(
        f"{OPENALEX_API}/works",
        {
            "filter": "openalex:" + "|".join(ids[:100]),
            "per_page": min(len(ids), 100),
            "select": WORK_FIELDS,
        },
    )
    return [_normalize_work(work) for work in response.get("results", []) if isinstance(work, dict)]


def _semantic_scholar_contexts(doi: str) -> list[dict[str, Any]]:
    """Fetch citation sentences and the index's coarse intent labels, if available."""
    if not doi:
        return []
    paper_id = quote(f"DOI:{doi.removeprefix('https://doi.org/')}", safe="")
    fields = (
        "contexts,intents,isInfluential,citingPaper.title,citingPaper.year,"
        "citingPaper.url,citingPaper.externalIds"
    )
    response = _get_json(
        f"{SEMANTIC_SCHOLAR_API}/paper/{paper_id}/citations",
        {"fields": fields, "limit": 30},
    )
    citations = []
    for item in response.get("data", []):
        paper = item.get("citingPaper") or {}
        contexts = item.get("contexts") or []
        if not paper.get("title") or not contexts:
            continue
        citations.append({
            "title": str(paper.get("title") or ""),
            "year": paper.get("year"),
            "url": str(paper.get("url") or ""),
            "doi": str((paper.get("externalIds") or {}).get("DOI") or ""),
            "contexts": [str(context) for context in contexts[:3]],
            "api_intents": [str(intent) for intent in item.get("intents", [])],
            "influential": bool(item.get("isInfluential")),
        })
    return citations


def explore_seed(seed: dict[str, Any], direction: str, *, limit: int = 20, page: int = 1) -> dict[str, Any]:
    """Browse papers cited by a seed or papers that cite it, with optional intent."""
    if direction == "Papers it cites":
        referenced_works = seed.get("referenced_works", [])
        if not referenced_works and seed.get("openalex_id"):
            full_seed = _get_json(seed["openalex_id"])
            referenced_works = full_seed.get("referenced_works", [])
            seed["referenced_works"] = referenced_works
        start = (page - 1) * limit
        papers = _fetch_openalex_ids(referenced_works[start:start + limit])
        total = len(referenced_works)
    else:
        work_id = seed.get("openalex_id", "").rsplit("/", 1)[-1]
        response = _get_json(
            f"{OPENALEX_API}/works",
            {
                "filter": f"cites:{work_id}", "sort": "publication_date:desc",
                "per_page": limit, "page": page, "select": WORK_FIELDS,
            },
        )
        papers = [_normalize_work(work) for work in response.get("results", []) if isinstance(work, dict)]
        total = int((response.get("meta") or {}).get("count") or 0)

    warning = ""
    if direction == "Papers that cite it" and seed.get("doi"):
        try:
            citations = _semantic_scholar_contexts(seed["doi"])
            by_doi = {item["doi"].casefold(): item for item in citations if item.get("doi")}
            by_title = {item["title"].casefold(): item for item in citations}
            matched_contexts = 0
            for paper in papers:
                citation = by_doi.get(paper.get("doi", "").casefold()) or by_title.get(paper["title"].casefold())
                if citation:
                    paper["citation_contexts"] = citation["contexts"]
                    paper["api_intents"] = citation["api_intents"]
                    paper["citation_influential"] = citation["influential"]
                    matched_contexts += len(citation["contexts"])
            _classify_citation_roles(papers)
            if not matched_contexts:
                warning = "Citation papers were found, but no matching citation sentences were available."
        except Exception:
            warning = "Citation context was unavailable from Semantic Scholar; the citation links are still shown."
    elif direction == "Papers that cite it" and not seed.get("doi"):
        warning = "This seed has no DOI, so citation links are shown without citation-context labels."

    return {
        "seed": seed, "direction": direction, "papers": papers, "warning": warning,
        "total": total, "page": page, "limit": limit,
    }


def _classify_citation_roles(papers: list[dict[str, Any]]) -> None:
    """Use the local model to cautiously label exact citation sentences."""
    from .llm import ask_json

    citation_papers = [paper for paper in papers if paper.get("citation_contexts")]
    items = []
    for index, paper in enumerate(citation_papers[:12]):
        for context_index, context in enumerate(paper["citation_contexts"][:2]):
            items.append({
                "context_id": f"{paper['id']}::{context_index}",
                "title": paper["title"],
                "context": context,
                "api_intents": paper.get("api_intents", []),
            })
    if not items:
        return
    payload = json.dumps(items, ensure_ascii=False)
    try:
        result = ask_json(CITATION_ROLE_INSTRUCTIONS, payload, max_output_tokens=450)
    except Exception:
        return
    roles_by_context: dict[str, dict[str, str]] = {}
    for candidate in result.get("citations", []) if isinstance(result.get("citations"), list) else []:
        if not isinstance(candidate, dict):
            continue
        context_id = str(candidate.get("context_id", ""))
        role = str(candidate.get("role", "")).strip()
        basis = str(candidate.get("basis", "")).strip()
        item = next((item for item in items if item["context_id"] == context_id), None)
        allowed = {"Method use or extension", "Baseline or comparison", "Background mention", "Unclear"}
        if item and role in allowed and basis and basis.casefold() in item["context"].casefold():
            roles_by_context[context_id] = {"role": role, "basis": basis}
    for paper in citation_papers:
        paper["citation_annotations"] = [
            roles_by_context.get(f"{paper['id']}::{index}", {})
            for index, _ in enumerate(paper["citation_contexts"][:2])
        ]


def assess_paper_matches(query: str, profile: str, papers: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Explain shortlist matches using exact phrases from returned abstracts."""
    from .llm import ask_json

    material = [
        {"paper_id": paper["id"], "title": paper["title"], "year": paper.get("year"),
         "abstract": paper.get("abstract", "")[:1000]}
        for paper in papers[:5]
    ]
    if not material:
        return {}
    payload = json.dumps({"research_question": query, "project_profile": profile, "papers": material}, ensure_ascii=False)
    try:
        result = ask_json(PAPER_MATCH_INSTRUCTIONS, payload, max_output_tokens=450)
    except Exception:
        return {}
    papers_by_id = {paper["id"]: paper for paper in papers}
    matches = {}
    for candidate in result.get("matches", []) if isinstance(result.get("matches"), list) else []:
        if not isinstance(candidate, dict):
            continue
        paper_id = str(candidate.get("paper_id", ""))
        quote = str(candidate.get("abstract_quote", "")).strip()
        reason = str(candidate.get("reason", "")).strip()
        paper = papers_by_id.get(paper_id)
        if paper and quote and reason and " ".join(quote.casefold().split()) in " ".join(paper.get("abstract", "").casefold().split()):
            matches[paper_id] = {"reason": reason[:350], "abstract_quote": quote[:350]}
    return matches


def load_profiles() -> dict[str, str]:
    """Load saved project anchors from the ignored local data folder."""
    try:
        data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(name): str(description) for name, description in data.items()}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_profile(name: str, description: str) -> None:
    """Save or update one profile without adding it to Git."""
    profiles = load_profiles()
    profiles[name.strip()] = description.strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")


def delete_profile(name: str) -> None:
    profiles = load_profiles()
    profiles.pop(name, None)
    if profiles:
        PROFILE_FILE.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        PROFILE_FILE.unlink(missing_ok=True)
