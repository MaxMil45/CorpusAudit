"""Shared local paths and Chroma collection setup."""

from pathlib import Path

import chromadb

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DB_DIR = DATA_DIR / "chroma"
COLLECTION_NAME = "corpus_audit_evidence"

DB_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_CLIENT = chromadb.PersistentClient(path=str(DB_DIR))


def get_collection():
    """Return the persistent collection, creating it on first use."""
    return CHROMA_CLIENT.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection() -> None:
    """Remove the index, then recreate an empty collection."""
    try:
        CHROMA_CLIENT.delete_collection(COLLECTION_NAME)
    except Exception:
        # A missing collection is already the state the caller wants.
        pass
    get_collection()
