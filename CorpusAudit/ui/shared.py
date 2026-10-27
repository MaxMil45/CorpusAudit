"""Reusable evidence display helpers."""

import streamlit as st


def render_pdf_passages(passages, cited_ids=()) -> None:
    if not passages:
        st.info("No matching passages were found in this library.")
        return

    st.markdown("#### Passages from your reports")
    for index, passage in enumerate(passages, 1):
        evidence_id = f"E{index}"
        with st.expander(
            f"[{evidence_id}] {passage['source']} · page {passage['page']}",
            expanded=evidence_id in cited_ids,
        ):
            st.write(passage["text"])
            st.caption(f"Passage {evidence_id} · search distance {passage['distance_label']} (ranking aid, not confidence)")
