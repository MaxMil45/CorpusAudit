"""Topic search for source-backed statistics from the public web."""

import streamlit as st

from corpus_audit_core.analysis import find_topic_statistics


def render_topic_statistics() -> None:
    st.subheader("Find statistics about a topic")
    st.write(
        "Discover number-bearing findings from studies, surveys, and reports. CorpusAudit searches several "
        "ways, pulls out relevant source passages, and links each finding so you can check the study yourself."
    )
    topic = st.text_input(
        "Topic",
        placeholder="e.g. golden retrievers, solar power, childhood asthma",
        key="topic_statistics_query",
    )
    focus = st.text_input(
        "Optional place, group, or time period",
        placeholder="e.g. worldwide, UK, in 2024, household pets",
        key="topic_statistics_focus",
        help="A narrower scope can reduce misleading results. It is included in the public search query.",
    )
    st.caption("Your topic is sent to public search providers. Search results may be incomplete or rate-limited.")

    if st.button("Find statistics", type="primary", disabled=not topic.strip()):
        with st.spinner("Searching source pages for figures and checking their wording…"):
            try:
                result = find_topic_statistics(topic, focus)
            except Exception as exc:
                if "context" in str(exc).casefold() and "token" in str(exc).casefold():
                    st.error(
                        "Ollama's context limit was reached. The app already trims source text; "
                        "try a shorter topic or use a model configured with a larger context."
                    )
                else:
                    st.error(f"Could not search for statistics: {exc}")
                return

        stats = result.get("statistics", [])
        sources = {source["id"]: source for source in result.get("sources", [])}
        if not stats:
            st.info(
                "I found search results, but couldn't extract a clear numerical finding from the pages I could read. "
                "Try a broader topic or remove the optional focus. Some sites block page reading."
            )
        else:
            st.markdown(f"### {len(stats)} source-backed result{'s' if len(stats) != 1 else ''}")
            for index, item in enumerate(stats, 1):
                source = sources.get(item["source_id"], {})
                with st.container(border=True):
                    # Keep model-produced text as plain text instead of treating it as Markdown.
                    st.write(f"{index}. {item['statistic']}")
                    st.caption(f"Scope: {item['scope']} · Year: {item['year']}")
                    st.write("Source wording:", item["supporting_excerpt"])
                    st.caption(source.get("text_kind", "Retrieved source text"))
                    if source.get("url"):
                        st.link_button(
                            f"Open source · {source.get('title', item['source_id'])}",
                            source["url"],
                        )

        if result.get("sources"):
            with st.expander(f"Search results reviewed ({len(result['sources'])})"):
                for source in result["sources"]:
                    st.link_button(source["title"], source["url"])
                    if source.get("snippet"):
                        st.caption(source["snippet"])

        st.caption(
            "A quoted passage helps you trace the figure; it does not establish that the study is high quality. "
            "Check the paper’s methods, date, population, and denominator before repeating the statistic."
        )
