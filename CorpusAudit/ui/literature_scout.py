"""Find research papers, follow citation links, and prepare a shortlist."""

import hashlib
import uuid
from datetime import date
from typing import Any

import streamlit as st

from corpus_audit_core.literature import (
    assess_paper_matches,
    delete_profile,
    explore_seed,
    find_seed_papers,
    load_profiles,
    save_profile,
    search_papers,
)

TRAIL_LIMIT = 8


def _new_trail_entry(label: str, result: dict[str, Any], query: str, profile: str) -> None:
    trail = st.session_state.get("literature_trail", [])
    entry = {
        "id": uuid.uuid4().hex[:10],
        "label": label[:48],
        "query": query,
        "profile": profile,
        "result": result,
        "matches": {},
    }
    trail.append(entry)
    st.session_state["literature_trail"] = trail[-TRAIL_LIMIT:]
    st.session_state["literature_current"] = entry
    st.session_state["literature_shortlist_ids"] = []


def _render_trail() -> None:
    trail = st.session_state.get("literature_trail", [])
    if not trail:
        return
    st.caption("Exploration trail · click a step to return to its results")
    visible = trail[-4:]
    columns = st.columns(len(visible))
    for index, (column, entry) in enumerate(zip(columns, visible)):
        with column:
            if st.button(entry["label"], key=f"literature_trail_{entry['id']}", use_container_width=True):
                st.session_state["literature_current"] = entry
                st.session_state["literature_shortlist_ids"] = []
                st.rerun()
    older = trail[:-4]
    if older:
        with st.expander("Older exploration steps"):
            for entry in older:
                if st.button(entry["label"], key=f"literature_older_{entry['id']}"):
                    st.session_state["literature_current"] = entry
                    st.session_state["literature_shortlist_ids"] = []
                    st.rerun()


def _profile_controls() -> str:
    profiles = load_profiles()
    choices = ["No saved profile", *sorted(profiles)]
    # Apply requested selection changes before Streamlit instantiates the selectbox.
    requested_selection = st.session_state.pop("_literature_profile_to_select", None)
    if requested_selection in choices:
        st.session_state["literature_profile_selected"] = requested_selection
    selected = st.selectbox("Saved project profile", choices, key="literature_profile_selected")
    if st.session_state.get("_literature_loaded_profile") != selected:
        st.session_state["literature_profile_name"] = "" if selected == choices[0] else selected
        st.session_state["literature_profile_description"] = profiles.get(selected, "")
        st.session_state["_literature_loaded_profile"] = selected

    left, right = st.columns([1, 2])
    with left:
        st.text_input("Profile name", key="literature_profile_name", placeholder="e.g. Face verification")
    with right:
        st.text_area(
            "Research goal and constraints",
            key="literature_profile_description",
            placeholder="e.g. Face verification in low-quality or occluded images; prioritize real-world benchmarks and methods that can run locally.",
            height=100,
            help="Profiles are stored in your ignored local data folder; they are not committed to Git.",
        )
    save_col, delete_col = st.columns([1, 1])
    with save_col:
        if st.button("Save project profile", key="save_literature_profile"):
            name = st.session_state.get("literature_profile_name", "").strip()
            description = st.session_state.get("literature_profile_description", "").strip()
            if not name or not description:
                st.warning("Add a profile name and a short description before saving.")
            else:
                save_profile(name, description)
                st.session_state["_literature_profile_to_select"] = name
                st.session_state["_literature_loaded_profile"] = None
                st.rerun()
    with delete_col:
        if selected != choices[0] and st.button("Delete selected profile", key="delete_literature_profile"):
            delete_profile(selected)
            st.session_state["_literature_profile_to_select"] = choices[0]
            st.session_state["_literature_loaded_profile"] = None
            st.rerun()
    return st.session_state.get("literature_profile_description", "").strip()


def _paper_label(paper: dict[str, Any]) -> str:
    year = paper.get("year") or "year unknown"
    authors = ", ".join(paper.get("authors", [])[:2])
    return f"{paper['title']} — {authors}, {year}" if authors else f"{paper['title']} — {year}"


def _render_paper_cards(
    papers: list[dict[str, Any]],
    matches: dict[str, dict[str, str]],
    follow_direction: str,
    current: dict[str, Any],
) -> None:
    for index, paper in enumerate(papers):
        safe_key = hashlib.sha1(paper["id"].encode()).hexdigest()[:10]
        authors = ", ".join(paper.get("authors", [])[:5]) or "Author details unavailable"
        details = [authors]
        if paper.get("venue"):
            details.append(paper["venue"])
        details.append(str(paper.get("year") or "Year not listed"))
        details.append(f"{paper.get('citation_count', 0):,} citations in OpenAlex")
        details.append("Open access copy listed" if paper.get("is_oa") else "No open access copy listed")
        with st.container(border=True):
            st.markdown(f"#### {paper['title']}")
            st.caption(" · ".join(details))
            if paper.get("doi_url"):
                st.link_button("Open DOI / publisher page", paper["doi_url"], key=f"doi_{safe_key}")
            elif paper.get("url"):
                st.link_button("Open paper record", paper["url"], key=f"record_{safe_key}")
            if paper.get("pdf_url"):
                st.link_button("Open listed PDF", paper["pdf_url"], key=f"pdf_{safe_key}")
            match = matches.get(paper["id"])
            if match:
                st.markdown("**Why it may match your project**")
                st.write(match["reason"])
                with st.expander("Check the abstract wording behind this match"):
                    st.write(match["abstract_quote"])
            for context_index, context in enumerate(paper.get("citation_contexts", [])[:2]):
                annotations = paper.get("citation_annotations", [])
                annotation = annotations[context_index] if context_index < len(annotations) else {}
                st.markdown(f"**Possible citation role · {annotation.get('role', 'Unclear')}**")
                st.caption("AI interpretation of a citation sentence; treat it as a lead, not proof of lineage.")
                st.write(context)
                if paper.get("api_intents"):
                    st.caption("Semantic Scholar labels: " + ", ".join(paper["api_intents"]))
                if annotation.get("basis"):
                    st.caption("Reason: " + annotation["basis"])
            if paper.get("abstract"):
                with st.expander(f"Read abstract · {paper['title'][:70]}"):
                    st.write(paper["abstract"])
            with st.expander(f"Follow citations · {paper['title'][:70]}"):
                st.caption("Choose whether to browse papers that cite it or works in its reference list.")
                if st.button("Explore this citation trail", key=f"follow_{safe_key}"):
                    with st.spinner("Following the citation links…"):
                        try:
                            next_result = explore_seed(paper, follow_direction)
                        except Exception as exc:
                            st.error(f"Could not follow this paper: {exc}")
                        else:
                            label_prefix = "Citing" if follow_direction == "Papers that cite it" else "References"
                            _new_trail_entry(
                                f"{label_prefix}: {paper['title']}", next_result,
                                paper["title"], current.get("profile", ""),
                            )
                            st.rerun()


def _render_current_results() -> None:
    current = st.session_state.get("literature_current")
    if not current:
        return
    result = current["result"]
    papers = result.get("papers", [])
    if not papers:
        st.info("No papers were returned for this step.")
        return

    if result.get("warning"):
        st.warning(result["warning"])
    if result.get("direction"):
        st.markdown(f"#### {result['direction']} · {result['seed']['title']}")
        st.caption("Citation records can be incomplete. A citation indicates a reference, not that the later paper validates or improves the seed.")
        st.caption(f"Showing {len(papers)} of {result.get('total', len(papers)):,} indexed connections.")
    else:
        st.markdown(f"#### Papers found · showing {len(papers)} of {result.get('total', len(papers)):,}")

    follow_direction = st.radio(
        "When following a result paper",
        ["Papers that cite it", "Papers it cites"],
        horizontal=True,
        key="literature_follow_direction",
    )
    matches = current.get("matches", {})
    _render_paper_cards(papers, matches, follow_direction, current)

    paper_by_id = {paper["id"]: paper for paper in papers}
    options = list(paper_by_id)
    st.multiselect(
        "Shortlist up to three papers",
        options=options,
        key="literature_shortlist_ids",
        max_selections=3,
        format_func=lambda paper_id: _paper_label(paper_by_id[paper_id]),
        help="Choose papers to assess against your project profile, then pass the shortlist to Study Explainer.",
    )
    selected_ids = st.session_state.get("literature_shortlist_ids", [])
    selected_papers = [paper_by_id[paper_id] for paper_id in selected_ids if paper_id in paper_by_id]
    assess_col, handoff_col = st.columns([1, 1])
    with assess_col:
        if st.button("Explain why these may match", disabled=not selected_papers, key="assess_literature_shortlist"):
            with st.spinner("Checking the selected abstracts against your research profile…"):
                new_matches = assess_paper_matches(
                    current.get("query", ""), current.get("profile", ""), selected_papers
                )
            current["matches"] = {**current.get("matches", {}), **new_matches}
            st.session_state["literature_current"] = current
            for entry in st.session_state.get("literature_trail", []):
                if entry["id"] == current["id"]:
                    entry["matches"] = current["matches"]
            st.rerun()
    with handoff_col:
        if st.button("Send shortlist to Study Explainer", type="primary", disabled=not selected_papers, key="handoff_literature_shortlist"):
            match_notes = current.get("matches", {})
            handoff_papers = []
            for paper in selected_papers:
                note = match_notes.get(paper["id"], {})
                handoff_papers.append({
                    "title": paper["title"], "year": paper.get("year"), "doi": paper.get("doi"),
                    "url": paper.get("url"), "abstract": paper.get("abstract", "")[:1000],
                    "match_reason": note.get("reason", "Selected from the scholarly search; abstract match has not been assessed."),
                })
            profile = current.get("profile", "")
            st.session_state["study_scout_handoff"] = {
                "query": current.get("query", ""), "profile": profile, "papers": handoff_papers,
            }
            st.session_state["study_explainer_topic"] = current.get("query", "")
            st.session_state["study_project_context"] = profile
            st.success("Shortlist context copied. Open Study Explainer and add the papers’ PDFs to your local library for passage-level review.")

    if result.get("total", 0) > len(papers):
        if st.button("Load more papers", key="load_more_literature"):
            with st.spinner("Loading the next result page…"):
                if result.get("direction"):
                    extra = explore_seed(
                        result["seed"], result["direction"],
                        limit=result.get("limit", 20), page=result.get("page", 1) + 1,
                    )
                else:
                    extra = search_papers(
                        current["query"], page=result.get("page", 1) + 1,
                        year_from=current.get("year_from"), open_access_only=current.get("open_access_only", False),
                    )
            existing = {paper["id"] for paper in papers}
            result["papers"] = papers + [paper for paper in extra["papers"] if paper["id"] not in existing]
            result["page"] = extra["page"]
            current["result"] = result
            st.session_state["literature_current"] = current
            trail = st.session_state.get("literature_trail", [])
            for entry in trail:
                if entry["id"] == current["id"]:
                    entry["result"] = result
            st.session_state["literature_trail"] = trail
            st.rerun()


def render_literature_scout() -> None:
    st.subheader("Literature Scout")
    st.write(
        "Find papers by research question or follow references from a paper you already know. "
        "Search records come from OpenAlex; citation sentences are added from Semantic Scholar when available."
    )
    st.caption(
        "Search questions and seed titles/DOIs go to the public scholarly indexes. Your saved profile stays local "
        "and guides the optional local-model abstract check. Indexes may miss papers; citation links and match notes are clues, not quality judgments."
    )

    _render_trail()
    with st.expander("Set a project profile", expanded=not bool(load_profiles())):
        profile = _profile_controls()
    if not profile:
        profile = st.session_state.get("literature_profile_description", "").strip()

    mode = st.radio(
        "How do you want to explore?",
        ["Search by research question", "Explore from a seed paper"],
        horizontal=True,
        key="literature_mode",
    )

    if mode == "Search by research question":
        with st.form("literature_search_form"):
            query = st.text_input(
                "Research question",
                placeholder="e.g. Face verification under occlusion using real-world benchmarks",
                key="literature_query",
            )
            year_text = st.text_input("Published from year (optional)", placeholder="e.g. 2022")
            open_access_only = st.checkbox("Only show records with an open-access copy listed")
            search_clicked = st.form_submit_button("Find papers", type="primary")
        if search_clicked:
            if not query.strip():
                st.warning("Enter a research question first.")
            else:
                try:
                    year_from = int(year_text) if year_text.strip() else None
                    if year_from and (year_from < 1900 or year_from > date.today().year):
                        raise ValueError("Enter a year between 1900 and this year.")
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    with st.spinner("Searching the scholarly index…"):
                        try:
                            result = search_papers(query.strip(), year_from=year_from, open_access_only=open_access_only)
                        except Exception as exc:
                            st.error(f"Paper search failed: {exc}")
                        else:
                            result["direction"] = ""
                            _new_trail_entry(f"Search: {query.strip()}", result, query.strip(), profile)
                            current = st.session_state["literature_current"]
                            current.update({"year_from": year_from, "open_access_only": open_access_only})
                            st.session_state["literature_current"] = current
                            st.session_state["literature_trail"][-1] = current

    else:
        with st.form("literature_seed_form"):
            seed_query = st.text_input(
                "Seed paper title or DOI",
                placeholder="e.g. ArcFace or 10.1109/CVPR.2019.00482",
                key="literature_seed_query",
            )
            find_seed_clicked = st.form_submit_button("Find seed paper")
        if find_seed_clicked:
            if not seed_query.strip():
                st.warning("Enter a paper title or DOI.")
            else:
                with st.spinner("Looking up the seed paper…"):
                    try:
                        seeds = find_seed_papers(seed_query)
                    except Exception as exc:
                        st.error(f"Seed lookup failed: {exc}")
                    else:
                        st.session_state["literature_seed_candidates"] = seeds
                        st.session_state["literature_seed_query_for_results"] = seed_query.strip()
                        if not seeds:
                            st.info("No seed paper matched. Try the exact title or DOI.")

        seeds = st.session_state.get("literature_seed_candidates", [])
        if seeds:
            seed_by_id = {seed["id"]: seed for seed in seeds}
            seed_id = st.selectbox(
                "Choose the seed paper",
                list(seed_by_id),
                format_func=lambda item: _paper_label(seed_by_id[item]),
                key="literature_seed_selected",
            )
            direction = st.radio(
                "Follow which direction?",
                ["Papers that cite it", "Papers it cites"],
                horizontal=True,
                key="literature_citation_direction",
            )
            seed = seed_by_id[seed_id]
            if st.button("Explore citation trail", type="primary", key="explore_literature_seed"):
                with st.spinner("Following the citation links…"):
                    try:
                        result = explore_seed(seed, direction)
                    except Exception as exc:
                        st.error(f"Could not follow this citation trail: {exc}")
                    else:
                        label = f"Seed: {seed['title']}"
                        _new_trail_entry(label, result, st.session_state.get("literature_seed_query_for_results", seed["title"]), profile)

    _render_current_results()
