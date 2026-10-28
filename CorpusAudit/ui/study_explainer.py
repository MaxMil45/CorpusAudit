"""Help a researcher screen and compare papers already in the local PDF library."""

import re

import streamlit as st

from corpus_audit_core.analysis import explain_studies
from corpus_audit_core.documents import get_collection_stats, rank_sources_for_question

STUDY_RESULT_VERSION = 4


def _render_study_result(result: dict) -> None:
    evidence = result.get("evidence", {})
    comparison = result.get("comparison", {})
    studies = result.get("studies", [])
    paper_names = {
        study.get("document_id"): study.get("source", "Selected paper")
        for study in studies
    }

    # The comparison is plain prose now; never show an old/raw JSON response as a recommendation.
    comparison_text = comparison.get("comparison_text", "")
    comparison_note = comparison.get("comparison_note", "")
    if comparison_text:
        # Turn model-facing evidence IDs into filenames and PDF pages before display.
        readable_comparison = re.sub(
            r"\[(D\d+P\d+)\]",
            lambda match: (
                f"[{evidence[match.group(1)]['source']}, PDF page "
                f"{evidence[match.group(1)]['page']}]"
                if match.group(1) in evidence else ""
            ),
            comparison_text,
        )
        for document_id, source in paper_names.items():
            readable_comparison = re.sub(
                rf"\b{re.escape(document_id)}\b(?!P\d)",
                f"**{source}**",
                readable_comparison,
            )
        st.markdown(readable_comparison)
    else:
        st.markdown("### Shortlist recommendation")
        if comparison_note:
            if comparison_note.lstrip().startswith(("{", "[")):
                st.warning("This result contains an old, unreadable comparison. Run Explain selected papers again.")
            else:
                st.warning(comparison_note)
        elif comparison.get("overall_takeaway"):
            st.info(comparison["overall_takeaway"])
        else:
            st.info("The verified paper points are below. There was not enough information for a clear comparison.")

    if comparison_text:
        cited_ids = set(re.findall(r"\[(D\d+P\d+)\]", comparison_text))
        cited_passages = [
            (evidence_id, evidence[evidence_id])
            for evidence_id in cited_ids
            if evidence_id in evidence
        ]
        if cited_passages:
            with st.expander("Check the evidence cited in this comparison"):
                for evidence_id, passage in cited_passages:
                    st.markdown(f"**{passage['source']} · PDF page {passage['page']}**")
                    st.write(passage["text"])

    equations = [
        (study, point)
        for study in result.get("studies", [])
        for point in study.get("points", [])
        if point.get("category") == "Equation/algorithm"
    ]
    if equations:
        st.markdown("### Equations and algorithms to inspect")
        st.caption("These are copied from the indexed PDF text. Check the original page before implementing them.")
        for study, point in equations:
            passage = evidence.get(point["evidence_id"], {})
            where = point.get("locator", f"PDF page {passage.get('page', 'unknown')}")
            st.markdown(f"**{study['source']} · {where} · PDF page {passage.get('page', 'unknown')}**")
            if point.get("explanation"):
                st.write(point["explanation"])
            st.code(point["quote"], language="text")

    st.markdown("### Paper-by-paper summaries")
    for study in result.get("studies", []):
        source = study.get("source", "Selected paper")
        with st.container(border=True):
            st.markdown(f"#### {source}")
            if study.get("reading_priority"):
                st.caption(f"Suggested reading priority: {study['reading_priority']}")

            if study.get("model_note"):
                st.warning(study["model_note"])
            else:
                points = study.get("points", [])
                if not points:
                    st.info("No statements could be verified against the selected PDF passages.")
                for point in points:
                    if point["category"] == "Equation/algorithm":
                        continue  # Equations are collected above in one place for easy comparison.
                    passage = evidence.get(point["evidence_id"], {})
                    where = point.get("locator", f"PDF page {passage.get('page', 'unknown')}")
                    source_label = f"{source}, {where}, PDF page {passage.get('page', 'unknown')}"
                    if point.get("source_extract"):
                        if point.get("explanation"):
                            st.markdown(f"**What this passage means · {source_label}**")
                            st.write(point["explanation"])
                        else:
                            st.markdown(f"**Passage to review · {source_label}**")
                            st.caption("The local model could not explain this excerpt reliably.")
                        with st.expander(f"Read the exact wording · {source_label}"):
                            st.write(point["quote"])
                    else:
                        st.write(f"**{point['category']} · {source_label}**: {point['claim']}")
                    if not point.get("source_extract"):
                        with st.expander(f"Read the supporting wording · {source_label}"):
                            st.write(point["quote"])

            # Keep the source passages close to each summary, with their original PDF pages.
            source_passages = [
                (evidence_id, passage)
                for evidence_id, passage in evidence.items()
                if passage.get("source") == source
            ]
            if source_passages:
                with st.expander("Check the passages used for this summary"):
                    for evidence_id, passage in source_passages:
                        st.markdown(f"**{source} · PDF page {passage['page']}**")
                        st.write(passage["text"])

    st.caption(
        "This is a screening aid based on selected PDF passages, not a substitute for reading the paper. "
        "A missing detail may be outside the excerpts rather than absent from the full paper. "
        "A strongest fit is only relative to this shortlist and your stated goal."
    )


def render_study_explainer() -> None:
    # Older saved results contain the raw JSON comparison that this update fixes.
    if st.session_state.get("study_result_version") != STUDY_RESULT_VERSION:
        st.session_state.pop("study_result", None)
        st.session_state.pop("study_result_signature", None)
        st.session_state["study_result_version"] = STUDY_RESULT_VERSION

    st.subheader("Study explainer")
    st.write(
        "Search the reports in your library for a research question, choose up to three likely matches, "
        "then get a structured summary and a side-by-side comparison. For recognition research, include "
        "the task you care about, such as fine-grained object recognition or face verification."
    )
    with st.expander("What the screening looks for"):
        st.write(
            "Task match; datasets and benchmarks; metrics and reported results; comparison baselines; "
            "and limitations. Object classification, object detection, face verification, and face "
            "identification are treated as different tasks. A point appears only when its supporting "
            "quote is found in the reviewed PDF passages; an omitted point may still appear elsewhere in the paper."
        )

    if get_collection_stats()["chunks"] == 0:
        st.info("Add PDFs in the sidebar first. Study Explainer uses your local indexed reports.")
        return

    priority_options = [
        "Exact match to the recognition task",
        "Relevant dataset or benchmark",
        "Clear metrics and comparison baselines",
        "Robustness in real-world conditions",
        "Speed, memory use, or deployment practicality",
    ]

    with st.form("study_explainer_search"):
        topic = st.text_input(
            "Research question or topic",
            placeholder="e.g. Which papers best evaluate fine-grained object recognition?",
            key="study_explainer_topic",
        )
        project_context = st.text_area(
            "What are you trying to build? (optional)",
            placeholder="e.g. A system that combines detailed object recognition with face verification in crowded, low-quality images.",
            height=75,
            key="study_project_context",
        )
        st.caption(
            "Be specific about the task and conditions: for example, face verification in low-quality images "
            "or object recognition on fine-grained benchmark datasets."
        )
        priorities = st.multiselect(
            "What should matter most in the comparison?",
            options=priority_options,
            default=priority_options[:3],
            key="study_review_priorities",
            help="These priorities guide the explanation; a paper still needs evidence in its excerpts.",
        )
        # Form fields do not rerun the app on every keystroke, so keep submit clickable.
        find_papers = st.form_submit_button("Find matching papers")

    if find_papers:
        if not topic.strip():
            st.warning("Enter a research question or topic first.")
            return
        with st.spinner("Checking each indexed report for matching pages…"):
            try:
                ranking_query = f"{topic}\n{project_context}".strip()
                candidates = rank_sources_for_question(ranking_query)
            except Exception as exc:
                st.error(f"Could not search the PDF library: {exc}")
                return
        st.session_state["study_candidates"] = candidates
        st.session_state["study_topic_for_results"] = topic.strip()
        st.session_state["study_project_context_for_results"] = project_context.strip()
        st.session_state["study_priorities_for_results"] = list(priorities)
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
        st.caption(
            f"Ranked {len(candidates)} reports from your library by topic relevance. "
            "This is not a paper-quality score; choose up to three to screen."
        )
        for candidate in candidates[:12]:
            st.write(
                f"**{candidate['source']}** · closest passage on page {candidate['best_page']}"
            )
        if len(candidates) > 12:
            with st.expander(f"View the other {len(candidates) - 12} ranked reports"):
                for candidate in candidates[12:]:
                    st.write(f"{candidate['source']} · closest passage on page {candidate['best_page']}")

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
            help="Search the full ranked list by typing a filename. Choose one for a summary or two or three to compare.",
        )

        if st.button("Explain selected papers", type="primary", disabled=not selected):
            with st.spinner("Reading the selected papers and comparing their evidence…"):
                try:
                    result = explain_studies(
                        st.session_state.get("study_topic_for_results", topic),
                        selected,
                        st.session_state.get("study_priorities_for_results", []),
                        st.session_state.get("study_project_context_for_results", ""),
                    )
                except Exception as exc:
                    st.error(f"Could not explain these papers: {exc}")
                    return
            st.session_state["study_result"] = result
            st.session_state["study_result_version"] = STUDY_RESULT_VERSION
            st.session_state["study_result_signature"] = (
                st.session_state.get("study_topic_for_results", topic),
                tuple(selected),
                tuple(st.session_state.get("study_priorities_for_results", [])),
                st.session_state.get("study_project_context_for_results", ""),
            )

    result = st.session_state.get("study_result")
    if result:
        current_signature = (
            st.session_state.get("study_topic_for_results", ""),
            tuple(st.session_state.get("study_selected_sources", [])),
            tuple(st.session_state.get("study_priorities_for_results", [])),
            st.session_state.get("study_project_context_for_results", ""),
        )
        if st.session_state.get("study_result_signature") != current_signature:
            st.info("You changed the topic or selected papers. Explain them again to refresh these summaries.")
        elif not result.get("studies"):
            st.info(result.get("message", "The model could not create summaries from the selected passages."))
        else:
            priorities_used = st.session_state.get("study_priorities_for_results", [])
            if priorities_used:
                st.caption("Priorities used: " + " · ".join(priorities_used))
            _render_study_result(result)
