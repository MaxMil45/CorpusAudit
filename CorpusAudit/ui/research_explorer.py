"""Question answering over the user's indexed PDF reports."""

import streamlit as st

from corpus_audit_core.analysis import ask_research_question
from corpus_audit_core.documents import get_collection_stats, search_evidence
from .shared import render_pdf_passages


def render_research_explorer() -> None:
    st.subheader("Explore your reports")
    st.write("Ask a question about the PDFs you have added to the library.")
    question = st.text_input(
        "Question",
        placeholder="What efficiency metric do the reports give for carbon capture?",
    )
    n_results = st.slider("Passages to use", 3, 10, 5, key="research_passages")
    st.caption("A year, country, or population can make an answer more precise.")

    if st.button("Search my reports", disabled=not question.strip()):
        if get_collection_stats()["chunks"] == 0:
            st.info("Add a PDF in the sidebar first.")
            return
        with st.spinner("Reading the relevant passages…"):
            try:
                passages = search_evidence(question, n_results=n_results)
                answer = ask_research_question(question, passages)
            except Exception as exc:
                st.error(f"Could not search the reports: {exc}")
                return

        st.markdown("#### Findings")
        st.write(answer.get("summary", "No summary returned."))
        if answer.get("key_findings"):
            for finding in answer["key_findings"]:
                st.markdown(f"- {finding}")
        if answer.get("what_it_measures"):
            st.markdown("**What it measures**")
            st.write(answer["what_it_measures"])
        for label, key in (
            ("Conditions and caveats", "conditions_and_caveats"),
            ("What remains unknown", "what_remains_unknown"),
        ):
            if answer.get(key):
                st.markdown(f"**{label}**")
                for item in answer[key]:
                    st.markdown(f"- {item}")
        render_pdf_passages(passages, answer.get("evidence_ids", []))
