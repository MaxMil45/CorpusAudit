"""Main claim-checking flow."""

import streamlit as st

from corpus_audit_core.analysis import audit_claim, audit_claim_on_web
from corpus_audit_core.documents import get_collection_stats, search_evidence
from .shared import render_pdf_passages


def _render_local_result(claim: str, passages: list[dict], result: dict) -> None:
    verdict = result.get("verdict", "Insufficient evidence")
    colors = {
        "Supported": "green",
        "Misleading": "orange",
        "Outdated": "orange",
        "Contradicted": "red",
        "Insufficient evidence": "gray",
    }
    st.markdown(f"### Verdict: :{colors.get(verdict, 'gray')}[{verdict}]")
    st.write(result.get("summary", "No summary returned."))

    with st.expander("How the evidence compares", expanded=True):
        st.markdown("**Claim scope**")
        st.write(result.get("claim_interpretation", claim))
        st.markdown("**What the reports say**")
        st.write(result.get("evidence_comparison", "No comparison returned."))
        caveats = result.get("caveats", [])
        if caveats:
            st.markdown("**Caveats**")
            for caveat in caveats:
                st.markdown(f"- {caveat}")

    render_pdf_passages(passages, result.get("evidence_ids", []))
    st.caption("Treat the verdict as a starting point. Check the cited passage and the source’s method.")


def _render_web_result(result: dict) -> None:
    st.markdown(result["answer"])
    sources = result.get("sources", [])
    if sources:
        with st.expander(f"Sources ({len(sources)})", expanded=True):
            for source in sources:
                st.link_button(f"{source['id']} · {source['title']}", source["url"])
                if source.get("snippet"):
                    st.caption(source["snippet"])
    st.caption("Open the source before relying on the verdict. Search snippets can be incomplete.")


def render_statistic_checker() -> None:
    st.subheader("Check a statistic")
    st.write("Paste the claim as you saw it. You can search the web without adding a PDF.")
    claim = st.text_area(
        "Statistic or claim",
        placeholder="Renewables supplied 80% of global electricity in 2024.",
        height=105,
    )
    source_mode = st.radio("Evidence source", ["Web search", "My PDF library"], horizontal=True)

    if source_mode == "Web search":
        st.caption("The claim is sent to public search providers; the AI analysis runs locally.")
    else:
        st.caption("This checks only the reports in your local library.")

    n_results = 6
    if source_mode == "My PDF library":
        n_results = st.slider("Passages to compare", 3, 10, 6)

    if st.button("Check this statistic", type="primary", disabled=not claim.strip()):
        if source_mode == "My PDF library" and get_collection_stats()["chunks"] == 0:
            st.info("Add a PDF in the sidebar first, or switch to Web search.")
            return

        with st.spinner("Finding the source and checking what the number measures…"):
            try:
                if source_mode == "Web search":
                    result = audit_claim_on_web(claim)
                    _render_web_result(result)
                else:
                    passages = search_evidence(claim, n_results=n_results)
                    result = audit_claim(claim, passages)
                    _render_local_result(claim, passages, result)
            except Exception as exc:
                st.error(f"Could not check this statistic: {exc}")
