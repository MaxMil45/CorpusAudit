"""PDF extraction, local indexing, retrieval, and library maintenance."""

import hashlib
import re
from pathlib import Path
from typing import Any

import pymupdf as fitz

from .settings import COLLECTION_NAME, DB_DIR, get_collection, reset_collection

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 180


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split extracted page text while keeping a little context between passages."""
    text = _clean_text(text)
    if not text:
        return []

    # A little overlap keeps a sentence near a cut from losing its surrounding context.
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Prefer a sentence or whitespace boundary when it is not too early.
            boundary = max(
                text.rfind(". ", start, end),
                text.rfind("\n", start, end),
                text.rfind(" ", start, end),
            )
            if boundary > start + int(size * 0.6):
                end = boundary + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _extract_pdf(uploaded_file) -> tuple[list[dict[str, Any]], str | None]:
    """Extract selectable text and retain the page number for every passage."""
    name = Path(uploaded_file.name).name
    try:
        data = uploaded_file.getvalue()
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        return [], f"Could not open {name}: {exc}"

    extracted = []
    # The filename groups passages from one report; the content hash distinguishes revisions.
    source_key = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:24]
    content_hash = hashlib.sha256(data).hexdigest()
    try:
        # Keep the page number on every chunk so answers can be checked in the original PDF.
        for page_index, page in enumerate(pdf):
            text = _clean_text(page.get_text("text"))
            for chunk_index, chunk in enumerate(_chunk_text(text)):
                digest = hashlib.sha256(
                    f"{source_key}:{content_hash}:{page_index + 1}:{chunk_index}:{chunk}".encode("utf-8")
                ).hexdigest()[:32]
                extracted.append({
                    "id": digest,
                    "text": chunk,
                    "metadata": {
                        "source": name,
                        "source_key": source_key,
                        "content_sha256": content_hash,
                        "page": page_index + 1,
                        "chunk": chunk_index,
                    },
                })
    except Exception as exc:
        return [], f"Could not extract {name}: {exc}"
    finally:
        pdf.close()

    warning = None if extracted else f"No selectable text found in {name}. It may be a scanned PDF and need OCR."
    return extracted, warning


def _remove_source_chunks(source_name: str, source_key: str) -> int:
    """Remove current and legacy chunks for a source filename."""
    collection = get_collection()
    ids = set()
    for where in ({"source_key": source_key}, {"source": source_name}):
        records = collection.get(where=where, include=["metadatas"])
        ids.update(records.get("ids", []))
    if ids:
        collection.delete(ids=list(ids))
    return len(ids)


def index_uploaded_pdfs(uploaded_files) -> dict[str, Any]:
    """Replace the indexed version of each uploaded filename with its latest text."""
    all_chunks = []
    warnings = []
    documents = set()
    replaced = 0

    for uploaded in uploaded_files:
        chunks, warning = _extract_pdf(uploaded)
        if warning:
            warnings.append(warning)
        if not chunks:
            continue

        source_name = Path(uploaded.name).name
        source_key = chunks[0]["metadata"]["source_key"]
        # A filename identifies one source in this library; remove older passages
        # before adding a new edition so the search cannot mix their figures.
        replaced += int(_remove_source_chunks(source_name, source_key) > 0)
        documents.add(source_name)
        all_chunks = [item for item in all_chunks if item["metadata"]["source_key"] != source_key]
        all_chunks.extend(chunks)

    if all_chunks:
        get_collection().upsert(
            ids=[item["id"] for item in all_chunks],
            documents=[item["text"] for item in all_chunks],
            metadatas=[item["metadata"] for item in all_chunks],
        )
    return {
        "documents": len(documents),
        "chunks": len(all_chunks),
        "replaced": replaced,
        "warnings": warnings,
    }


def search_evidence(query: str, n_results: int = 5) -> list[dict[str, Any]]:
    """Return the closest passages; Chroma distance is a ranking aid, not certainty."""
    collection = get_collection()
    count = collection.count()
    if count == 0:
        return []

    result = collection.query(query_texts=[query], n_results=min(n_results, count))
    docs = result.get("documents", [[]])[0]
    ids = result.get("ids", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0] if result.get("distances") else [None] * len(docs)
    return [
        {
            "id": doc_id,
            "text": doc,
            "source": metadata.get("source", "Unknown source"),
            "page": metadata.get("page", "?"),
            "distance": distance,
            "distance_label": f"{distance:.3f}" if isinstance(distance, (float, int)) else "n/a",
        }
        for doc_id, doc, metadata, distance in zip(ids, docs, metadatas, distances)
    ]


def rank_sources_for_question(query: str, max_sources: int = 12) -> list[dict[str, Any]]:
    """Rank indexed PDFs by how closely their passages match a topic or question."""
    # Looking across many passages helps surface several papers instead of repeating one paper.
    passages = search_evidence(query, n_results=80)
    matches: dict[str, dict[str, Any]] = {}
    for passage in passages:
        source = passage["source"]
        match = matches.setdefault(source, {"source": source, "hits": 0, "best_distance": None, "best_page": passage["page"]})
        match["hits"] += 1
        distance = passage.get("distance")
        if isinstance(distance, (int, float)) and (
            match["best_distance"] is None or distance < match["best_distance"]
        ):
            match["best_distance"] = distance
            match["best_page"] = passage["page"]

    return sorted(
        matches.values(),
        key=lambda item: (
            item["best_distance"] if item["best_distance"] is not None else float("inf"),
            -item["hits"],
        ),
    )[:max_sources]


def get_source_passages(source_name: str) -> list[dict[str, Any]]:
    """Read all stored passages for one PDF and put them back in page order."""
    records = get_collection().get(
        where={"source": source_name},
        include=["documents", "metadatas"],
    )
    passages = []
    for passage_id, text, metadata in zip(
        records.get("ids", []),
        records.get("documents", []),
        records.get("metadatas", []),
    ):
        passages.append({
            "id": passage_id,
            "text": text,
            "source": metadata.get("source", source_name),
            "page": metadata.get("page", 0),
            "chunk": metadata.get("chunk", 0),
        })
    return sorted(passages, key=lambda item: (item["page"], item["chunk"]))


def get_collection_stats() -> dict[str, Any]:
    collection = get_collection()
    count = collection.count()
    if count == 0:
        return {"chunks": 0, "documents": 0, "sources": [], "collection": COLLECTION_NAME, "storage": str(DB_DIR)}
    records = collection.get(include=["metadatas"])
    sources = sorted({m.get("source", "Unknown") for m in records.get("metadatas", [])})
    return {
        "chunks": count,
        "documents": len(sources),
        "sources": sources,
        "collection": COLLECTION_NAME,
        "storage": str(DB_DIR),
    }


def clear_index() -> None:
    reset_collection()
