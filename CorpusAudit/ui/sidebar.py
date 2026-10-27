"""Local evidence library controls."""

import streamlit as st

from corpus_audit_core.documents import clear_index, get_collection_stats, index_uploaded_pdfs


def render_sidebar() -> None:
    with st.sidebar:
        st.header("Your PDF library")
        st.caption("Optional: add reports to search them alongside the web checker.")
        uploads = st.file_uploader("Choose PDF reports", type=["pdf"], accept_multiple_files=True)
        if st.button("Add reports", type="primary", use_container_width=True):
            if not uploads:
                st.warning("Choose at least one PDF first.")
            else:
                with st.spinner("Reading reports and building the local index…"):
                    try:
                        result = index_uploaded_pdfs(uploads)
                        st.success(
                            f"Added {result['documents']} report(s) and {result['chunks']} passages."
                            + (f" Replaced {result['replaced']} existing report(s)." if result["replaced"] else "")
                        )
                        for warning in result["warnings"]:
                            st.warning(warning)
                    except Exception as exc:
                        st.error(f"Could not add the reports: {exc}")

        stats = get_collection_stats()
        st.metric("Reports in library", stats["documents"])
        st.caption(f"{stats['chunks']} searchable passages · stored on this computer")

        # Ask for a second click so a mis-tap cannot wipe the local search index.
        if st.button("Clear index", use_container_width=True):
            st.session_state["confirm_clear_index"] = True
        if st.session_state.get("confirm_clear_index"):
            st.warning("This clears the searchable index, not your original PDF files.")
            confirm, cancel = st.columns(2)
            with confirm:
                if st.button("Clear it", type="primary", use_container_width=True):
                    clear_index()
                    st.session_state["confirm_clear_index"] = False
                    st.rerun()
            with cancel:
                if st.button("Keep it", use_container_width=True):
                    st.session_state["confirm_clear_index"] = False
                    st.rerun()

        st.divider()
        with st.expander("Local AI setup"):
            st.markdown("Install [Ollama](https://ollama.com/download), then download the model:")
            st.code("ollama pull qwen3:4b-instruct", language="powershell")
            st.caption("The model runs on your computer. Its first download is about 2.5 GB.")
