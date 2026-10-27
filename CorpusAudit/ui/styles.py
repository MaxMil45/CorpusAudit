"""Shared page styling and title."""

import streamlit as st


def render_page_header() -> None:
    st.markdown(
        """
        <style>
        .block-container { max-width: 1080px; padding-top: 1.5rem; padding-bottom: 3rem; }
        [data-testid="stExpander"] { border-radius: 8px; }
        [data-testid="stMetric"] { border: 1px solid rgba(120, 130, 140, .22); border-radius: 8px; padding: .7rem 1rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("CorpusAudit")
    st.caption("Check a statistic, then follow it back to the evidence.")
