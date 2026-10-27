"""Help a researcher screen and compare papers already in the local PDF library."""

import streamlit as st

from corpus_audit_core.analysis import explain_studies
from corpus_audit_core.documents import get_collection_stats, rank_sources_for_question


def _render_list(label: str, items) -> None:
    if not isinstance(items, list) or not items:
        return
    st.markdown(f"**{label}**")
    for item in items:
        st.write(f"• {item}")


def _render_study_result(result: dict) -> None:
    evidence = result.get("evidence", {})

    st.markdown("### Paper-by-paper summaries")
    for study in result.get("studies", []):
        source = study.get("source", "Selected paper")
        with st.container(border=True):
            st.markdown(f"#### {source}")
            st.caption(f"Suggested reading priority: {study.get('reading_priority', 'Maybe')}")
            if study.get("evidence_ids"):
                st.caption("Evidence passages: " + ", ".join(study["evidence_ids"]))

            for label, key in (
                ("Research question", "research_question"),
                ("Study design", "study_design"),
                ("Who or what was studied", "population_and_setting"),
                ("What the researchers did", "methods"),
                ("Why it may matter for your question", "relevance_to_question"),
            ):
                value = study.get(key)
                if value:
                    st.markdown(f"**{label}**")
                    st.write(value)

            _render_list("Main findings", study.get("main_findings"))
            _render_list("Limitations stated in the excerpts", study.get("limitations"))

            # Keep the source passages close to each summary, with their original PDF pages.
            source_passages = [
                (evidence_id, passage)
                for evidence_id, passage in evidence.items()
                if passage.get("source") == source
            ]
            if source_passages:
                with st.expander("Check the passages used for this summary"):
                    for evidence_id, passage in source_passages:
                        st.markdown(f"**{evidence_id} · PDF page {passage['page']}**")
                        st.write(passage["text"])

    comparison = result.get("comparison", {})
    if comparison:
        st.markdown("### How the papers compare")
        if comparison.get("overall_takeaway"):
            st.info(comparison["overall_takeaway"])
        _render_list("What they have in common", comparison.get("shared_ground"))
        _render_list("Important differences in scope or method", comparison.get("important_differences"))
        _render_list("Possible conflicts to investigate", comparison.get("possible_conflicts"))

        reference_ids = comparison.get("evidence_ids", [])
        if reference_ids:
            with st.expander("Comparison references"):
                for evidence_id in reference_ids:
                    passage = evidence.get(evidence_id)
                    if passage:
                        st.markdown(
                            f"**{evidence_id} · {passage['source']} · PDF page {passage['page']}**"
                        )
                        st.write(passage["text"])

    st.caption(
        "This is a screening aid based on selected PDF passages, not a substitute for reading the paper. "
        "A missing detail may be outside the excerpts rather than absent from the full paper."
    )


def render_study_explainer() -> None:
    st.subheader("Study explainer")
    st.write(
        "Search the reports in your library for a research question, choose up to three likely matches, "
        "then get a structured summary and a side-by-side comparison."
    )

    if get_collection_stats()["chunks"] == 0:
        st.info("Add PDFs in the sidebar first. Study Explainer uses your local indexed reports.")
        return

    with st.form("study_explainer_search"):
        topic = st.text_input(
            "Research question or topic",
            placeholder="e.g. Which interventions improve sleep quality in older adults?",
            key="study_explainer_topic",
        )
        # Form fields do not rerun the app on every keystroke, so keep submit clickable.
        find_papers = st.form_submit_button("Find matching papers")

    if find_papers:
        if not topic.strip():
            st.warning("Enter a research question or topic first.")
            return
        with st.spinner("Finding the reports that best match your question…"):
            try:
                candidates = rank_sources_for_question(topic)
            except Exception as exc:
                st.error(f"Could not search the PDF library: {exc}")
                return
        st.session_state["study_candidates"] = candidates
        st.session_state["study_topic_for_results"] = topic.strip()
        st.session_state["study_selected_sources"] = [
            item["source"] for item in candidates[:3]
        ]
        st.session_state.pop("study_result", None)
        st.session_state.pop("study_result_signature", None)
        if not candidates:
            st.info("No matching passages were found. Try different wording or a broader topic.")

    candidates = st.session_state.get("study_candidates", [])
    if candidates:
        st.markdown("#### Matching reports")
        st.caption("These are search suggestions, not a quality score. Choose up to three to screen.")
        for candidate in candidates:
            st.write(
                f"**{candidate['source']}** · {candidate['hits']} matching passages "
                f"· closest passage on page {candidate['best_page']}"
            )

        options = [item["source"] for item in candidates]
        # Keep selections valid if a new topic produced a different set of PDFs.
        selected_now = st.session_state.get("study_selected_sources", [])
        st.session_state["study_selected_sources"] = [
            source for source in selected_now if source in options
        ][:3]
        selected = st.multiselect(
            "Papers to explain",
            options=options,
            key="study_selected_sources",
            max_selections=3,
            help="Choose one paper for a summary, or two or three for a comparison.",
        )

        if st.button("Explain selected papers", type="primary", disabled=not selected):
            with st.spinner("Reading the selected papers and comparing their evidence…"):
                try:
                    result = explain_studies(
                        st.session_state.get("study_topic_for_results", topic), selected
                    )
                except Exception as exc:
                    st.error(f"Could not explain these papers: {exc}")
                    return
            st.session_state["study_result"] = result
            st.session_state["study_result_signature"] = (
                st.session_state.get("study_topic_for_results", topic),
                tuple(selected),
            )

    result = st.session_state.get("study_result")
    if result:
        current_signature = (
            st.session_state.get("study_topic_for_results", ""),
            tuple(st.session_state.get("study_selected_sources", [])),
        )
        if st.session_state.get("study_result_signature") != current_signature:
            st.info("You changed the topic or selected papers. Explain them again to refresh these summaries.")
        elif not result.get("studies"):
            st.info(result.get("message", "The model could not create summaries from the selected passages."))
        else:
            _render_study_result(result)
