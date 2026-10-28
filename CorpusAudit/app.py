import streamlit as st
from dotenv import load_dotenv

# Load optional local settings first, because the model/search modules read them at import time.
load_dotenv()

from ui.evidence_library import render_evidence_library
from ui.research_explorer import render_research_explorer
from ui.sidebar import render_sidebar
from ui.statistic_checker import render_statistic_checker
from ui.study_explainer import render_study_explainer
from ui.topic_statistics import render_topic_statistics
from ui.styles import render_page_header


def main() -> None:
    st.set_page_config(page_title="CorpusAudit", layout="wide")
    render_page_header()
    render_sidebar()

    # The short descriptions make it clear which tab needs a claim, a topic, or uploaded PDFs.
    cards = st.columns(4)
    for column, title, description in zip(
        cards,
        ("Check a claim", "Find figures", "Explore your reports", "Screen studies"),
        (
            "Bring a statistic you have already seen.",
            "Start with a subject and discover reported numbers.",
            "Search the PDFs saved in your local library.",
            "Rank your library, then screen up to three papers at a time.",
        ),
    ):
        with column:
            with st.container(border=True):
                st.markdown(f"**{title}**")
                st.caption(description)

    # Keep the web workflows separate from the user's private, locally indexed reports.
    check_tab, find_tab, reports_tab, library_tab, studies_tab = st.tabs(
        ["Check a statistic", "Find statistics", "Explore reports", "Evidence library", "Study explainer"]
    )
    with check_tab:
        render_statistic_checker()
    with find_tab:
        render_topic_statistics()
    with reports_tab:
        render_research_explorer()
    with library_tab:
        render_evidence_library()
    with studies_tab:
        render_study_explainer()

    st.caption("Check a claim, discover figures, or screen papers in your local report library.")


main()
