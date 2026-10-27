"""Compatibility exports; implementation lives in corpus_audit_core."""

from corpus_audit_core.analysis import (
    _format_evidence,
    ask_research_question,
    audit_claim,
    audit_claim_on_web,
)
from corpus_audit_core.documents import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    _chunk_text,
    _clean_text,
    _extract_pdf,
    clear_index,
    get_collection_stats,
    index_uploaded_pdfs,
    search_evidence,
)
from corpus_audit_core.llm import ask_json as _ask_json
from corpus_audit_core.settings import COLLECTION_NAME, DB_DIR
from corpus_audit_core.prompts import (
    LOCAL_AUDIT_INSTRUCTIONS as AUDIT_INSTRUCTIONS,
    RESEARCH_INSTRUCTIONS,
    WEB_AUDIT_INSTRUCTIONS,
)
