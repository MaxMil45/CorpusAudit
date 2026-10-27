"""Overview of the indexed documents and current PDF limitations."""

import streamlit as st

from corpus_audit_core.documents import get_collection_stats


def render_evidence_library() -> None:
    st.subheader("Evidence library")
    stats = get_collection_stats()
    if not stats["sources"]:
        st.info("Your library is empty. Add PDFs in the sidebar to search your own reports.")
        return

    st.write(f"{stats['documents']} report(s) · {stats['chunks']} searchable passages")
    for source in stats["sources"]:
        st.markdown(f"- {source}")
    st.caption(f"Index location: `{stats['storage']}`")
    st.info("Scanned PDFs and complex tables may not be readable yet. Original PDFs are not deleted when you clear the index.")
