"""Decision-first roadmap view for the two-page Streamlit frontend."""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from app.table_utils import arrow_safe_dataframe


def _timestamp(value):
    if not value:
        return "not recorded"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _completion(summary):
    total = int(summary.get("total_item_count") or 0)
    closed = int(summary.get("closed_item_count") or 0)
    return 0.0 if total <= 0 else min(1.0, max(0.0, closed / total))


def _active_rows(items):
    rows = []
    for item in items or []:
        checked = int(item.get("checked_checklist_count") or 0)
        remaining = int(item.get("open_checklist_count") or 0)
        checklist = f"{checked} done / {remaining} open" if checked or remaining else "not tracked"
        rows.append({
            "Item": f"#{item.get('number')}",
            "Workstream": item.get("title") or "Untitled item",
            "Status": "In progress" if item.get("status") == "PARTIAL" else "Open",
            "Dependency marker": "HELD" if item.get("blocked") else "CLEAR",
            "Disposition": item.get("disposition") or "No disposition recorded",
            "Checklist": checklist,
            "Updated": item.get("date") or "-",
        })
    return rows


def render_roadmap_page():
    from weather.reporting.roadmap.roadmap_backlog import summarize_roadmap_status

    @st.cache_data(ttl=30, show_spinner=False)
    def cached_summary():
        return summarize_roadmap_status()

    summary = cached_summary()
    active_items = summary.get("active_items") or []
    clear_items = [item for item in active_items if not item.get("blocked")]
    held_items = [item for item in active_items if item.get("blocked")]
    completion = _completion(summary)

    st.markdown(
        """
        <style>
        .roadmap-kicker {
          color:#31708f;font-size:.78rem;font-weight:800;letter-spacing:.12em;
          text-transform:uppercase;margin-bottom:.25rem
        }
        .roadmap-hero {
          padding:1.25rem 1.35rem;border:1px solid #c9dce5;border-radius:16px;
          background:linear-gradient(135deg,#eef8fb 0%,#f7fbf4 62%,#fff8df 100%);
          margin:.35rem 0 1rem
        }
        .roadmap-hero strong {color:#174a5b;font-size:1.1rem}
        .roadmap-hero p {color:#40515a;margin:.35rem 0 0;max-width:72ch}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="roadmap-kicker">Build system / source of truth</div>',
        unsafe_allow_html=True,
    )
    st.title("Roadmap")
    st.markdown(
        '<div class="roadmap-hero"><strong>Focus on unfinished work.</strong>'
        '<p>Completed history remains searchable in the repository. This page keeps '
        'the active queue visible, separates dependency-held work, and never turns '
        'a clear marker into an automatic priority.</p></div>',
        unsafe_allow_html=True,
    )

    metrics = st.columns(4)
    metrics[0].metric("Active work", summary.get("active_item_count", 0))
    metrics[1].metric("Clear path", summary.get("active_unblocked_item_count", 0))
    metrics[2].metric("Dependency held", summary.get("active_blocked_item_count", 0))
    metrics[3].metric(
        "Roadmap integrity",
        "PASS" if not summary.get("lint_error_count") else "CHECK",
        delta=f"{summary.get('lint_error_count', 0)} lint errors",
        delta_color="off",
    )

    closed = int(summary.get("closed_item_count") or 0)
    total = int(summary.get("total_item_count") or 0)
    st.progress(completion, text=f"Historical completion: {closed} of {total} tracked items")
    st.caption(
        f"Generated {_timestamp(summary.get('generated_at_utc'))}. "
        f"{summary.get('partial_item_count', 0)} items are in progress and "
        f"{summary.get('open_item_count', 0)} are open."
    )

    if summary.get("lint_error_count"):
        st.error(
            "Roadmap integrity checks are failing. Treat the queue as advisory until the "
            "numbered items and index are repaired."
        )
    elif summary.get("status") != "OK":
        st.warning("Roadmap status is not OK even though no lint-error count was supplied.")
    else:
        st.success("Numbered items and the roadmap index agree.")

    if not active_items:
        st.success("No active roadmap work remains.")
        return

    st.subheader("Active work queue")
    st.caption(
        "CLEAR means the item has no explicit BLOCK marker. It does not override sequencing, "
        "risk gates, or operator judgment."
    )
    clear_tab, held_tab, all_tab = st.tabs(
        [
            f"Clear path ({len(clear_items)})",
            f"Dependency held ({len(held_items)})",
            f"All active ({len(active_items)})",
        ]
    )
    with clear_tab:
        if clear_items:
            st.dataframe(
                arrow_safe_dataframe(_active_rows(clear_items)),
                hide_index=True,
                width="stretch",
            )
        else:
            st.info("Every active item currently carries a dependency marker.")
    with held_tab:
        if held_items:
            st.dataframe(
                arrow_safe_dataframe(_active_rows(held_items)),
                hide_index=True,
                width="stretch",
            )
        else:
            st.success("No active item currently carries a dependency marker.")
    with all_tab:
        st.dataframe(
            arrow_safe_dataframe(_active_rows(active_items)),
            hide_index=True,
            width="stretch",
        )
