"""Owner cockpit: Money / Work / Health / Exam on one read-only page."""

from __future__ import annotations

import streamlit as st

from app.table_utils import arrow_safe_dataframe


def _text(value, fallback="-"):
    return fallback if value in (None, "") else str(value)


def _load_cockpit_snapshot():
    from weather.reporting.market.cockpit_snapshot import collect_cockpit_snapshot

    return collect_cockpit_snapshot()


def _unavailable(column, section):
    if section.get("available"):
        return False
    column.warning(f"Unavailable: {_text(section.get('reason'), 'no reason recorded')}")
    return True


def _money(column, money):
    column.subheader("Money")
    if _unavailable(column, money):
        return
    column.metric("Cash (pUSD)", _text(money.get("cash_pusd")), delta=_text(money.get("status"), "no status"),
                  delta_color="off")
    if money.get("pnl_pusd") is None:
        column.metric("Campaign P&L (pUSD)", "INCOMPLETE")
        column.caption(_text(money.get("pnl_reason")))
    else:
        column.metric("Campaign P&L (pUSD)", money["pnl_pusd"])
    if money.get("bleed_limit_reached"):
        column.error("Bleed limit reached")
    column.caption(
        f"Positions {money.get('position_count')}, open orders {_text(money.get('open_order_count'), 'unknown')}, "
        f"unredeemed {money.get('unredeemed_count')}. Captured {_text(money.get('captured_at_utc'))}."
    )
    rewards = money.get("rewards") or {}
    if rewards.get("available"):
        column.metric(f"Rewards {rewards['date']} UTC", _text(rewards.get("total_pusd"), "unparsed"))
        if not rewards.get("payment_verified"):
            column.caption("Reward accrual; payment not verified.")
    else:
        column.caption(f"Rewards unavailable: {_text(rewards.get('reason'))}")
    if money.get("errors"):
        column.caption("Reader errors: " + ", ".join(money["errors"]))


def _work(column, work):
    column.subheader("Work")
    if _unavailable(column, work):
        return
    column.metric("Open missions", work["open_count"], delta=f"{work['record_count']} records", delta_color="off")
    column.metric("Waiting on owner", len(work["waiting_on_owner"]),
                  delta=f"{work['overdue_owner_count']} over 3 days", delta_color="inverse")
    for row in work["waiting_on_owner"]:
        line = f"{row['id']}: {row['question']} ({row['age_days']} d)"
        (column.error if row["overdue"] else column.info)(line)
    if work["by_status"]:
        column.dataframe(
            arrow_safe_dataframe([{"Status": key, "Missions": value} for key, value in work["by_status"].items()]),
            hide_index=True, width="stretch",
        )
    column.caption("Ready to land: " + (", ".join(work["ready_to_land"]) or "none"))
    if work["check_issues"]:
        column.warning(f"{len(work['check_issues'])} registry check issues")
        column.caption("; ".join(work["check_issues"][:5]))


def _health(column, health):
    column.subheader("Health")
    host = health.get("host") or {}
    if not _unavailable(column, host):
        column.metric("Watchdog", _text(host.get("verdict"), "unknown"),
                      delta=_text(host.get("top_severity"), "no alerts"), delta_color="off")
        column.caption(f"Streak {_text(host.get('streak'))}, today {_text(host.get('today'))}, "
                       f"window {_text(host.get('window'))}, {_text(host.get('age_minutes'))} min old.")
        if host.get("stale"):
            column.warning("Watchdog record is stale")
        if host.get("alerts"):
            column.dataframe(arrow_safe_dataframe(host["alerts"]), hide_index=True, width="stretch")
    disk = health.get("disk") or {}
    if not _unavailable(column, disk):
        slope = disk.get("slope_gib_per_day")
        column.metric("Free disk (GiB)", disk["free_gib"],
                      delta=None if slope is None else f"{slope} GiB/day")
        days = disk.get("days_to") or {}
        column.caption(f"Days to 50 GiB: {_text(days.get('50'), 'not falling')}; "
                       f"to 40 GiB: {_text(days.get('40'), 'not falling')}. {_text(disk.get('slope_reason'))}")
    maker = health.get("maker_evidence") or {}
    if not _unavailable(column, maker):
        status = maker.get("status") or {}
        column.metric("88a capture", _text(status.get("state"), "no status"),
                      delta=f"{len(maker['closed_dates'])} closed UTC dates", delta_color="off")
        if maker.get("unsealed_past_dates"):
            column.warning("Past dates not sealed: " + ", ".join(maker["unsealed_past_dates"]))


def _exam(column, exam):
    column.subheader("Exam")
    if _unavailable(column, exam):
        return
    for row in exam["exams"]:
        column.metric(row["candidate"], row["phase"], delta=f"look {row['look']} ({row['days_to_look']} d)",
                      delta_color="off")
        closed = row.get("panel_days_closed")
        column.caption(
            f"Panel {row['panel'][0]}..{row['panel'][1]}; closed 88a panel dates "
            f"{_text(closed, 'unknown')}/{row['panel_days_total']}. {row['source']}."
        )
    column.info(exam["embargo"])


def render_cockpit_page():
    """Render the owner's default page; no mutation controls, fail closed."""

    st.title("Owner Cockpit")
    st.caption("Read-only: no order, cancel, credential, Scheduler or promotion controls. "
               "Every source is optional and says why when it is missing.")
    body = st.empty()
    try:
        snapshot = _load_cockpit_snapshot()
        with body.container():
            st.caption(f"Snapshot {snapshot['generated_at_utc']}")
            money, work, health, exam = st.columns(4)
            _money(money, snapshot["money"])
            _work(work, snapshot["work"])
            _health(health, snapshot["health"])
            _exam(exam, snapshot["exam"])
    except Exception as exc:  # noqa: BLE001 - owner UI must fail closed; drop any partial render
        body.empty()
        st.error(f"Cockpit failed safely: {type(exc).__name__}: {exc}")
