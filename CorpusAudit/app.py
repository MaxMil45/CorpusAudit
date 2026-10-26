import os
import streamlit as st
from dotenv import load_dotenv

# Load settings before importing the pipeline, which reads OPENAI_MODEL at import time.
load_dotenv()

from corpus_audit import (
    index_uploaded_pdfs, search_evidence, ask_research_question,
    audit_claim, audit_claim_on_web, get_collection_stats, clear_index
)

st.set_page_config(page_title="CorpusAudit", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1080px;}
[data-testid="stMetric"] {padding: .8rem 1rem; border: 1px solid rgba(120, 130, 140, .22); border-radius: 8px;}
[data-testid="stExpander"] {border-radius: 8px;}
</style>
""", unsafe_allow_html=True)

st.title("CorpusAudit")
st.caption("Check the number. Read the source. See what it actually measures.")

with st.sidebar:
    st.header("Evidence library")
    st.caption("Add reports if you want to search your own material.")
    uploaded = st.file_uploader("Choose PDF reports", type=["pdf"], accept_multiple_files=True)
    if st.button("Add to library", type="primary", use_container_width=True):
        if not uploaded:
            st.warning("Choose a PDF to add first.")
        else:
            with st.spinner("Extracting text and indexing evidence..."):
                try:
                    result = index_uploaded_pdfs(uploaded)
                    st.success(
                        f"Indexed {result['chunks']} text chunks from {result['documents']} document(s)."
                        + (f" Replaced {result['replaced']} existing source(s)." if result["replaced"] else "")
                    )
                    for warning in result["warnings"]:
                        st.warning(warning)
                except Exception as exc:
                    st.error(f"Indexing failed: {exc}")

    stats = get_collection_stats()
    st.metric("Indexed evidence chunks", stats["chunks"])
    st.caption("Your library stays on this computer.")
    if st.button("Clear index", use_container_width=True):
        st.session_state["confirm_clear_index"] = True
    if st.session_state.get("confirm_clear_index"):
        st.warning("This removes the searchable index from this computer. It does not delete your PDF files.")
        confirm_col, cancel_col = st.columns(2)
        with confirm_col:
            if st.button("Remove index", type="primary", use_container_width=True):
                clear_index()
                st.session_state["confirm_clear_index"] = False
                st.rerun()
        with cancel_col:
            if st.button("Keep it", use_container_width=True):
                st.session_state["confirm_clear_index"] = False
                st.rerun()

    st.divider()
    st.markdown("**A quick start**")
    st.markdown("1. Paste a statistic into Statistic Checker.\n2. Open the source and check its definitions.\n3. Add PDFs if you want to search your own reports.")

if not os.getenv("OPENAI_API_KEY"):
    st.warning("Add an OpenAI API key in `.env` to use web search and AI summaries. PDF extraction and local search are still available without it.")

tab_research, tab_audit, tab_library = st.tabs(["Research Explorer", "Statistic Checker", "Evidence Library"])

with tab_research:
    st.subheader("Explore a topic")
    st.write("Ask a question about the reports in your library.")
    topic = st.text_input("Topic or research question", placeholder="What does the evidence say about carbon capture efficiency?")
    col1, col2 = st.columns([1, 3])
    with col1:
        research_k = st.slider("Evidence passages", min_value=3, max_value=10, value=5, key="research_k")
    with col2:
        st.caption("A year, country, or population can make the answer more precise.")
    if st.button("Search the reports", type="primary", key="research_button"):
        if not topic.strip():
            st.error("Enter a research question.")
        elif get_collection_stats()["chunks"] == 0:
            st.error("Upload and index some PDFs first.")
        else:
            with st.spinner("Reading the relevant passages..."):
                try:
                    passages = search_evidence(topic, n_results=research_k)
                    answer = ask_research_question(topic, passages)
                except Exception as exc:
                    st.error(f"Could not search the reports: {exc}")
                    passages = []
                    answer = None
            if answer:
                st.markdown("### Findings")
                st.markdown(answer.get("summary", "No summary returned."))
                if answer.get("key_findings"):
                    st.markdown("#### Key findings")
                    for finding in answer["key_findings"]:
                        st.markdown(f"- {finding}")
                if answer.get("what_it_measures"):
                    st.markdown("#### What it measures")
                    st.write(answer["what_it_measures"])
                for heading, key in (("Conditions and caveats", "conditions_and_caveats"), ("What remains unknown", "what_remains_unknown")):
                    if answer.get(key):
                        st.markdown(f"#### {heading}")
                        for item in answer[key]:
                            st.markdown(f"- {item}")
                st.markdown("### Passages to check")
                cited = answer.get("evidence_ids", [])
                for i, p in enumerate(passages, 1):
                    evidence_id = f"E{i}"
                    with st.expander(f"[{evidence_id}] {p['source']} · page {p['page']}", expanded=evidence_id in cited):
                        st.write(p["text"])
                        # Search distance is useful for ordering results, but is not confidence.
                        st.caption(f"Passage reference: {evidence_id} · Search distance: {p['distance_label']}")

with tab_audit:
    st.subheader("Check a statistic")
    st.write("Paste the statistic, ideally with the wording and date you saw. No upload is needed for a web search.")
    claim = st.text_area("Statistic or claim", placeholder="Renewables supplied 80% of global electricity in 2024.", height=110)
    source_mode = st.radio(
        "Look in",
        ["Web search", "My PDF library"],
        horizontal=True,
    )
    c1, c2 = st.columns(2)
    with c1:
        k = st.slider("Evidence passages", min_value=3, max_value=10, value=6, key="audit_k")
    with c2:
        st.caption("Include a place, year, or group if the original claim gives one.")
    if st.button("Check this statistic", type="primary", key="audit_button"):
        if not claim.strip():
            st.error("Paste a claim to audit.")
        elif source_mode == "My PDF library" and get_collection_stats()["chunks"] == 0:
            st.error("Add a PDF in the sidebar first, or switch to Web search.")
        else:
            with st.spinner("Looking for the original figure and checking its scope..."):
                try:
                    if source_mode == "Web search":
                        web_result = audit_claim_on_web(claim)
                        result = None
                        passages = []
                    else:
                        passages = search_evidence(claim, n_results=k)
                        result = audit_claim(claim, passages)
                        web_result = None
                except Exception as exc:
                    st.error(f"Could not check this statistic: {exc}")
                    passages = []
                    result = None
                    web_result = None
            if result is None and web_result is None:
                st.stop()
            if web_result is not None:
                st.markdown(web_result["answer"])
                if web_result["sources"]:
                    with st.expander("Sources found on the web", expanded=True):
                        for source in web_result["sources"]:
                            st.markdown(f"- [{source['title']}]({source['url']})")
                st.caption("Open the source before relying on the verdict. Web search and analysis use your OpenAI API account.")
            else:
                verdict = result.get("verdict", "Insufficient evidence")
                colors = {
                    "Supported": "green",
                    "Misleading": "orange",
                    "Outdated": "orange",
                    "Contradicted": "red",
                    "Insufficient evidence": "gray",
                }
                st.markdown(f"### Verdict: :{colors.get(verdict, 'gray')}[{verdict}]")
                st.markdown(result.get("summary", "No summary returned."))
                left, right = st.columns(2)
                with left:
                    st.markdown("#### Claim")
                    st.info(result.get("claim_interpretation", claim))
                with right:
                    st.markdown("#### What the evidence says")
                    st.success(result.get("evidence_comparison", "No comparison returned."))
                st.markdown("#### Caveats and conditions")
                caveats = result.get("caveats", [])
                if caveats:
                    for item in caveats:
                        st.markdown(f"- {item}")
                else:
                    st.write("No caveats identified. Check the source passages below.")
                st.markdown("#### Evidence")
                cited = result.get("evidence_ids", [])
                for i, p in enumerate(passages, 1):
                    label = f"[E{i}] {p['source']} — page {p['page']}"
                    with st.expander(label, expanded=(f"E{i}" in cited or str(i) in cited)):
                        st.write(p["text"])
                        st.caption(f"Reference ID: E{i} · Chunk ID: {p['id']}")
                st.caption("Treat this as a starting point. Check the cited passage and the source’s method.")

with tab_library:
    st.subheader("Indexed source inventory")
    st.write("These are the PDFs currently in your local library. Each passage keeps its filename and page number.")
    st.json(get_collection_stats())
    st.markdown("**Suggested source types**")
    st.markdown("- Government statistical releases\n- Peer-reviewed papers with clear methodology\n- Official technical reports\n- Datasets with documented definitions and time periods")
    st.info("If a report is scanned rather than text-based, CorpusAudit may not be able to read it yet.")
