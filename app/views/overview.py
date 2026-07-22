"""Read-only capital-canary homepage for the Streamlit app."""

from __future__ import annotations

import html
import logging
import math
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import streamlit as st


_DISPLAY_STATES = {"LOCKED", "PREFLIGHT", "PROBE", "LIVE", "PAUSED", "HALTED"}
_PROVENANCE_FIELDS = (
    ("Release", "release_id"),
    ("Release manifest hash", "release_manifest_sha256"),
    ("Activation hash", "activation_sha256"),
    ("Platform", "platform"),
    ("Account", "redacted_account_id"),
    ("Risk policy", "policy_id"),
    ("Risk policy hash", "policy_sha256"),
    ("Risk caps hash", "risk_caps_sha256"),
    ("Economics snapshot", "economics_snapshot_id"),
    ("Economics hash", "economics_sha256"),
    ("Permission snapshot", "permission_snapshot_id"),
    ("Permission hash", "permission_sha256"),
    ("Input snapshot", "input_snapshot_id"),
    ("Input snapshot hash", "input_snapshot_sha256"),
    ("Code hash", "code_sha256"),
    ("Dashboard schema", "dashboard_schema_version"),
    ("Source schema", "source_schema_version"),
    ("Status schema", "schema_version"),
    ("Status hash", "status_sha256"),
    ("Snapshot hash", "snapshot_hash"),
    ("Projection sequence", "sequence"),
    ("Positions hash", "positions_sha256"),
    ("Portfolio hash", "portfolio_sha256"),
)
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "credential",
    "mnemonic",
    "password",
    "passphrase",
    "private",
    "secret",
)
_LOGGER = logging.getLogger(__name__)


def _load_home_payload() -> dict:
    """Keep the provider lazy so the router never owns canary I/O."""
    from weather.reporting.market.capital_canary_dashboard import (
        load_capital_canary_dashboard,
    )

    payload = load_capital_canary_dashboard()
    return dict(payload) if isinstance(payload, Mapping) else {}


def _finite_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _boolean(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1", "enabled", "engaged", "current"}:
            return True
        if normalized in {"false", "no", "0", "disabled", "clear"}:
            return False
    if value in (0, 1):
        return bool(value)
    return None


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _rows(value, *, limit: int, keep_tail: bool = False) -> list[Mapping]:
    if not isinstance(value, list):
        return []
    selected = list(reversed(value[-limit:])) if keep_tail else value[:limit]
    return [row for row in selected if isinstance(row, Mapping)]


def _value(values: Mapping, *keys, fallback=None):
    for key in keys:
        if values.get(key) is not None:
            return values[key]
    return fallback


def _text(value, fallback: str = "Unknown") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _money(value) -> str:
    number = _finite_number(value)
    if number is None:
        return "Unknown"
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):,.2f}"


def _percent(value, *, signed: bool = False) -> str:
    number = _finite_number(value)
    if number is None:
        return "Unknown"
    magnitude = number * 100.0
    return f"{magnitude:+.1f}%" if signed else f"{magnitude:.1f}%"


def _quantity(value) -> str:
    number = _finite_number(value)
    if number is None:
        return "Unknown"
    return str(int(number)) if number.is_integer() else f"{number:,.4f}".rstrip("0").rstrip(".")


def _duration(value) -> str:
    seconds = _finite_number(value)
    if seconds is None:
        return "age unknown"
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f}s ago"
    if seconds < 3600:
        return f"{seconds / 60.0:.1f}m ago"
    return f"{seconds / 3600.0:.1f}h ago"


def _timestamp(value) -> str:
    if value in (None, ""):
        return "not yet available"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _label(value, fallback: str = "Unknown") -> str:
    text = _text(value, fallback).replace("_", " ").strip()
    return text.title() if text else fallback


def _status_name(payload: Mapping) -> str:
    status = _text(
        _value(payload, "display_state", "status", fallback="LOCKED"),
        "LOCKED",
    ).upper()
    return status if status in _DISPLAY_STATES else "LOCKED"


def _candidate_link(candidate: Mapping) -> str:
    """Return only a local evidence route or an official HTTPS market URL."""
    href = _text(candidate.get("market_url"), "")
    if href:
        parsed = urlsplit(href)
        if parsed.path == "/" and not parsed.netloc:
            query = parse_qs(parsed.query, keep_blank_values=False)
            if set(query) == {"market"} and len(query["market"]) == 1:
                return f"/?{urlencode({'market': query['market'][0]})}"
        if (
            parsed.scheme == "https"
            and parsed.netloc.lower() in {"polymarket.com", "www.polymarket.com"}
        ):
            return href

    event_slug = _text(candidate.get("event_slug"), "")
    if event_slug and re.fullmatch(r"[A-Za-z0-9_-]+", event_slug):
        return f"https://polymarket.com/event/{quote(event_slug, safe='-_')}"

    market_id = _text(candidate.get("market_id"), "")
    if market_id:
        return f"/?{urlencode({'market': market_id})}"
    return "/?market=overview"


def _render_status(payload: Mapping) -> tuple[str, bool]:
    status = _status_name(payload)
    source_status = _text(payload.get("source_status"), "UNKNOWN").upper()
    freshness = _mapping(payload.get("freshness"))
    stale = _boolean(freshness.get("stale")) is not False
    message = _text(
        payload.get("status_message"),
        "Capital placement is disabled until every authority and evidence gate passes.",
    )
    operational = source_status == "FRESH" and not stale and status in {"PROBE", "LIVE"}
    status_class = "canary-status-live" if operational else "canary-status-stop"

    st.markdown('<span class="canary-kicker">$75 CAPITAL CANARY / READ ONLY</span>', unsafe_allow_html=True)
    st.title("Safest bets right now")
    st.caption(
        "A read-only tracker for the capped capital canary. This page cannot place, "
        "cancel, size, or modify an order."
    )
    st.caption(
        "A market price above 90% is consensus, not proof of safety or model edge. "
        "Every candidate still has to clear evidence, freshness, liquidity, and after-cost gates."
    )
    st.markdown(
        '<div class="canary-status" role="status" aria-live="polite">'
        f'<strong class="{status_class}">{html.escape(status)}</strong>'
        f'<span>Source {html.escape(source_status)}</span>'
        f'<span>As of {html.escape(_timestamp(payload.get("as_of_utc")))}</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    if operational:
        st.success(message)
    elif status == "PREFLIGHT":
        st.info(message)
    elif status == "PAUSED":
        st.warning(message)
    else:
        st.error(message)

    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if warning:
                st.warning(_text(warning))

    if stale:
        st.warning(
            "Dashboard projections are stale or unverified. Last-known risk remains visible; "
            "targets and worker-submission claims are hidden."
        )
    return status, stale


def _render_safety(payload: Mapping, *, stale: bool) -> None:
    heartbeat = _mapping(payload.get("heartbeat"))
    safety = _mapping(payload.get("safety"))
    readiness = _mapping(payload.get("readiness"))
    kill_switch = _boolean(safety.get("kill_switch_engaged"))
    submission_enabled = _boolean(safety.get("order_submission_enabled"))
    heartbeat_freshness = _text(heartbeat.get("freshness"), "UNKNOWN").upper()

    if stale:
        submission_text = "HIDDEN (STALE)"
    elif submission_enabled is True:
        submission_text = "ENABLED FOR WORKER"
    elif submission_enabled is False:
        submission_text = "DISABLED"
    else:
        submission_text = "UNKNOWN"

    if kill_switch is True:
        kill_switch_text = "ENGAGED"
    elif kill_switch is False:
        kill_switch_text = "CLEAR"
    else:
        kill_switch_text = "UNKNOWN"

    classification = _value(
        readiness,
        "classification",
        fallback=_value(safety, "authority_state", fallback="Unknown"),
    )
    cells = (
        (
            "Heartbeat",
            f"{_timestamp(heartbeat.get('at_utc'))} · {_duration(heartbeat.get('age_seconds'))}",
            heartbeat_freshness,
        ),
        ("Kill switch", kill_switch_text, "Fail closed on unknown state"),
        (
            "Reconciliation",
            _label(safety.get("reconciliation_state")),
            "Account and ledger agreement",
        ),
        (
            "Activation",
            _label(safety.get("activation_status")),
            f"Expires {_timestamp(safety.get('activation_expires_at_utc'))}",
        ),
        ("Worker submission gate", submission_text, "No controls are exposed here"),
        (
            "Readiness classification",
            _label(classification),
            "Classification never grants authority",
        ),
    )
    cards = []
    for title, value, note in cells:
        cards.append(
            '<div class="canary-control">'
            f"<span>{html.escape(title)}</span>"
            f"<strong>{html.escape(value)}</strong>"
            f"<small>{html.escape(note)}</small>"
            "</div>"
        )
    st.markdown("## Bot and safety state")
    st.markdown(
        f'<section class="canary-control-grid" aria-label="Bot and safety state">{"".join(cards)}</section>',
        unsafe_allow_html=True,
    )


def _render_account(payload: Mapping) -> None:
    account = _mapping(payload.get("account") or payload.get("fund"))
    freshness = _mapping(payload.get("freshness"))
    portfolio_stale = _boolean(freshness.get("portfolio_data_stale")) is not False
    cap = _value(account, "capital_ceiling_usdc", "budget_usdc", fallback=75.0)
    metric_specs = (
        ("Campaign ceiling", _money(cap)),
        (
            "Net liquidation",
            _money(_value(account, "net_liquidation_value_usdc", "equity_usdc")),
        ),
        ("Cash", _money(_value(account, "cash_usdc", "available_usdc"))),
        ("Reserve", _money(account.get("reserve_usdc"))),
        (
            "Unresolved max loss",
            _money(
                _value(
                    account,
                    "unresolved_worst_case_loss_usdc",
                    "unresolved_loss_usdc",
                )
            ),
        ),
        ("Cap utilization", _percent(account.get("cap_utilization"))),
    )
    st.markdown("## Capital snapshot")
    for offset in range(0, len(metric_specs), 3):
        columns = st.columns(3)
        for column, (label, value) in zip(columns, metric_specs[offset : offset + 3]):
            column.metric(label, value)
    st.caption(
        "Unknown account values remain unknown; they are never converted to zero. "
        "The $75 campaign ceiling is lifetime funding, not a target allocation."
    )
    if portfolio_stale:
        st.warning(
            "Portfolio data is stale or unverified. Account and performance values are "
            "last known, not assumed current."
        )


def _render_performance(payload: Mapping) -> None:
    performance = _mapping(payload.get("performance"))
    freshness = _mapping(payload.get("freshness"))
    portfolio_stale = _boolean(freshness.get("portfolio_data_stale")) is not False
    metric_specs = (
        (
            "Settled realized P&L",
            _money(performance.get("settled_realized_pnl_usdc")),
        ),
        (
            "Executable-bid unrealized P&L",
            _money(performance.get("unrealized_executable_bid_pnl_usdc")),
        ),
        ("Fees paid", _money(performance.get("fees_usdc"))),
        ("Drawdown", _money(performance.get("drawdown_usdc"))),
        (
            "Market-following counterfactual",
            _money(performance.get("market_following_pnl_usdc")),
        ),
        ("No-trade counterfactual", _money(performance.get("no_trade_pnl_usdc"))),
    )
    st.markdown("## Performance and counterfactuals")
    for offset in range(0, len(metric_specs), 3):
        columns = st.columns(3)
        for column, (label, value) in zip(columns, metric_specs[offset : offset + 3]):
            column.metric(label, value)
    st.caption(
        "Settled realized P&L and executable-bid mark-to-market P&L are separate measures. "
        "Neither is treated as proof of model edge."
    )
    if portfolio_stale:
        st.caption("Performance values are from the last-known portfolio projection.")


def _render_target(target: Mapping) -> None:
    market = _text(
        _value(target, "range_label", "market_label", fallback="Weather contract")
    )
    target_date = _text(target.get("target_date"), "date unavailable")
    side = _label(target.get("side"), "Side unknown")
    decision = _label(target.get("decision"), "Held")
    hold_reason = _text(target.get("hold_reason"), "No hold reason reported")
    link = html.escape(_candidate_link(target), quote=True)
    aria = html.escape(f"{decision} canary evaluation for {market} on {target_date}", quote=True)
    st.markdown(
        f"""
        <article class="canary-target" aria-label="{aria}">
          <div class="canary-card-topline">
            <span class="canary-side-pill">{html.escape(side)}</span>
            <span class="canary-decision">WORKER DECISION: {html.escape(decision.upper())}</span>
          </div>
          <h3>{html.escape(market)}</h3>
          <div class="canary-card-date">Target date {html.escape(target_date)}</div>
          <div class="canary-stat-grid">
            <div><span>Executable ask</span><strong>{html.escape(_percent(target.get("executable_ask")))}</strong></div>
            <div><span>Hard maximum price</span><strong>{html.escape(_percent(target.get("max_price")))}</strong></div>
            <div><span>Fair-value lower bound</span><strong>{html.escape(_percent(target.get("fair_value_lower_bound")))}</strong></div>
            <div><span>After-cost edge/share</span><strong>{html.escape(_money(target.get("after_cost_edge_per_share")))}</strong></div>
            <div><span>Expected after-cost ROI</span><strong>{html.escape(_percent(target.get("expected_after_cost_roi"), signed=True))}</strong></div>
            <div><span>Capped maximum loss</span><strong>{html.escape(_money(target.get("max_loss_usdc")))}</strong></div>
          </div>
          <div class="canary-hold"><strong>Hold / decision reason:</strong> {html.escape(hold_reason)}</div>
          <a class="canary-market-link" href="{link}" target="_self" aria-label="Open market evidence for {html.escape(market, quote=True)}">Open market evidence</a>
        </article>
        """,
        unsafe_allow_html=True,
    )


def _render_targets(payload: Mapping, *, stale: bool) -> None:
    st.markdown("## Bot-evaluated targets")
    if stale:
        st.info(
            "Targets are hidden because authority or status data is stale. "
            "Stale evidence cannot become an order-enabled claim."
        )
        return
    targets = _rows(payload.get("targets"), limit=3)
    if not targets:
        st.info("No capital-qualified target is visible. The bot remains on hold.")
        return
    columns = st.columns(len(targets), gap="large")
    for column, target in zip(columns, targets):
        with column:
            _render_target(target)


def _render_position(position: Mapping, *, stale: bool) -> None:
    market = _text(
        _value(position, "range_label", "market_label", fallback="Weather contract")
    )
    target_date = _text(position.get("target_date"), "date unavailable")
    side = _label(_value(position, "side", "outcome"), "Side unknown")
    settlement = _label(position.get("settlement_state"), "Unsettled")
    stale_badge = '<span class="canary-stale-pill">LAST KNOWN</span>' if stale else ""
    link = html.escape(_candidate_link(position), quote=True)
    aria = html.escape(f"{side} position for {market} on {target_date}", quote=True)
    st.markdown(
        f"""
        <article class="canary-position" aria-label="{aria}">
          <div class="canary-card-topline">
            <span class="canary-side-pill">{html.escape(side)}</span>{stale_badge}
          </div>
          <h3>{html.escape(market)}</h3>
          <div class="canary-card-date">Target date {html.escape(target_date)} · {html.escape(settlement)}</div>
          <div class="canary-stat-grid">
            <div><span>Quantity</span><strong>{html.escape(_quantity(position.get("quantity")))}</strong></div>
            <div><span>Average entry</span><strong>{html.escape(_percent(position.get("average_entry_price")))}</strong></div>
            <div><span>Entry notional</span><strong>{html.escape(_money(position.get("entry_notional_usdc")))}</strong></div>
            <div><span>Worst-case loss</span><strong>{html.escape(_money(position.get("worst_case_loss_usdc")))}</strong></div>
            <div><span>Executable bid</span><strong>{html.escape(_percent(position.get("executable_bid")))}</strong></div>
            <div><span>Executable-bid unrealized P&amp;L</span><strong>{html.escape(_money(position.get("unrealized_executable_bid_pnl_usdc")))}</strong></div>
          </div>
          <div class="canary-card-date">Updated {html.escape(_timestamp(position.get("updated_at_utc")))}</div>
          <a class="canary-market-link" href="{link}" target="_self" aria-label="Open position evidence for {html.escape(market, quote=True)}">Open position evidence</a>
        </article>
        """,
        unsafe_allow_html=True,
    )


def _render_positions(payload: Mapping) -> None:
    freshness = _mapping(payload.get("freshness"))
    position_stale = _boolean(freshness.get("position_data_stale")) is not False
    positions = _rows(payload.get("positions"), limit=8)
    st.markdown("## Positions and unresolved exposure")
    if position_stale:
        st.warning(
            "Position data is stale. Last-known exposure is not assumed flat, "
            "including when no position rows are available."
        )
    elif not positions:
        st.info("No reconciled open positions were reported by the latest fresh projection.")
        return

    if not positions:
        return
    columns = st.columns(min(2, len(positions)), gap="large")
    for index, position in enumerate(positions):
        with columns[index % len(columns)]:
            _render_position(position, stale=position_stale)


def _render_activity(payload: Mapping) -> None:
    activity = _rows(
        payload.get("activity") or payload.get("recent_activity"),
        limit=12,
        keep_tail=True,
    )
    st.markdown("## Recent canary activity")
    if not activity:
        st.info("No canary lifecycle, reconciliation, order, settlement, or risk event is available yet.")
        return
    items = []
    for event in activity:
        event_type = _label(_value(event, "event_type", "state", fallback="Event"))
        code = _label(event.get("code"), "")
        detail = _text(event.get("detail"), "No detail reported")
        identifier = _text(
            _value(event, "event_id", "market_id", "order_id", fallback=""),
            "",
        )
        metadata = f" · {identifier}" if identifier else ""
        code_text = f" · {code}" if code else ""
        items.append(
            '<li class="canary-activity-item">'
            f'<time>{html.escape(_timestamp(event.get("occurred_at_utc")))}</time>'
            f"<strong>{html.escape(event_type + code_text)}</strong>"
            f"<span>{html.escape(detail + metadata)}</span>"
            "</li>"
        )
    st.markdown(
        f'<ol class="canary-activity" aria-label="Recent canary activity">{"".join(items)}</ol>',
        unsafe_allow_html=True,
    )


def _render_blockers(payload: Mapping) -> None:
    blockers = payload.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        return
    items = []
    for blocker in blockers[:20]:
        if isinstance(blocker, Mapping):
            code = _label(blocker.get("code"), "Safety gate")
            detail = _text(blocker.get("detail"), "No detail reported")
        else:
            code = _label(blocker, "Safety gate")
            detail = "Capital placement remains disabled."
        items.append(
            '<li class="canary-blocker">'
            f"<strong>{html.escape(code)}</strong>"
            f"<span>{html.escape(detail)}</span>"
            "</li>"
        )
    st.markdown("## Safety blocks")
    st.markdown(
        f'<ul class="canary-blockers" aria-label="Active safety blocks">{"".join(items)}</ul>',
        unsafe_allow_html=True,
    )


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _render_provenance(payload: Mapping) -> None:
    provenance = dict(_mapping(payload.get("provenance")))
    provenance.setdefault("dashboard_schema_version", payload.get("schema_version"))
    rows = []
    for label, key in _PROVENANCE_FIELDS:
        value = provenance.get(key)
        if (
            value in (None, "")
            or _is_sensitive_key(key)
            or isinstance(value, (Mapping, list, tuple, set))
        ):
            continue
        rows.append(
            "<div>"
            f"<dt>{html.escape(label)}</dt>"
            f"<dd>{html.escape(_text(value))}</dd>"
            "</div>"
        )

    high_water = provenance.get("ledger_high_water_marks")
    if not isinstance(high_water, Mapping):
        high_water = provenance.get("ledger_high_water")
    if isinstance(high_water, Mapping):
        values = []
        for key, value in sorted(high_water.items(), key=lambda item: str(item[0])):
            if _is_sensitive_key(key) or isinstance(value, (list, tuple, set)):
                continue
            if isinstance(value, Mapping):
                sequence = value.get("sequence")
                record_hash = value.get("record_hash")
                if sequence is not None:
                    values.append(f"{key}.sequence={sequence}")
                if record_hash is not None:
                    values.append(f"{key}.record_hash={record_hash}")
            else:
                values.append(f"{key}={value}")
        if values:
            rows.append(
                "<div><dt>Ledger high-water marks</dt>"
                f"<dd>{html.escape(', '.join(values))}</dd></div>"
            )

    with st.expander("Audit lineage and provenance"):
        st.caption(
            "This page reads bounded, redacted projections. It never resolves credentials, "
            "grants authority, or submits orders."
        )
        if not rows:
            st.write("No allowlisted provenance is available yet.")
            return
        st.markdown(
            f'<dl class="canary-provenance">{"".join(rows)}</dl>',
            unsafe_allow_html=True,
        )


def _render_page_body(payload: Mapping) -> None:
    status, stale = _render_status(payload)
    _render_safety(payload, stale=stale)
    _render_account(payload)
    _render_targets(payload, stale=stale)
    _render_positions(payload)
    _render_performance(payload)
    _render_activity(payload)
    _render_blockers(payload)
    _render_provenance(payload)

    st.markdown(
        f"""
        <div class="canary-nav">
          <span>{"Last reported" if stale else "Current"} state: <strong>{html.escape(status)}</strong></span>
          <a href="/?market=mm" target="_self">Paper evidence</a>
          <a href="/?market=ops" target="_self">Operations</a>
          <a href="/?history" target="_self">Settlement history</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_overview_page(live_refresh_seconds: int) -> None:
    st.markdown(
        """
        <style>
        :root {
          --canary-bg: #08111f;
          --canary-panel: #14243a;
          --canary-panel-deep: #0d1b2d;
          --canary-ink: #edf4fa;
          --canary-muted: #a6b6c7;
          --canary-teal: #5ee0d2;
          --canary-green: #91ddb0;
          --canary-amber: #f2c879;
          --canary-red: #ff9f9f;
          --canary-border: rgba(117, 211, 201, 0.24);
        }
        [data-testid="stAppViewContainer"] {
          background: radial-gradient(circle at 82% 0%, #1b3854 0, #0c1b2d 34%, var(--canary-bg) 100%);
          color: var(--canary-ink);
        }
        [data-testid="stHeader"] { background: rgba(8, 17, 31, 0.84); }
        [data-testid="stSidebar"] { background: #0d1929; }
        [data-testid="stMetric"] {
          background: rgba(20, 36, 58, 0.8);
          border: 1px solid rgba(166, 182, 199, 0.17);
          border-radius: 12px;
          padding: 0.85rem 1rem;
        }
        [data-testid="stMetricLabel"] p { color: var(--canary-muted) !important; }
        [data-testid="stMetricValue"] { color: var(--canary-ink) !important; font-size: 1.55rem !important; }
        [data-testid="stAlert"] p { color: #d2dfeb !important; }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p { color: #b7c4d2 !important; }
        .canary-kicker {
          display: inline-block;
          color: var(--canary-teal);
          background: rgba(94, 224, 210, 0.11);
          border: 1px solid rgba(94, 224, 210, 0.29);
          border-radius: 999px;
          padding: 0.32rem 0.72rem;
          font-size: 0.72rem;
          font-weight: 800;
          letter-spacing: 0.09em;
        }
        .canary-status {
          align-items: center;
          color: var(--canary-muted);
          display: flex;
          flex-wrap: wrap;
          gap: 0.7rem 1rem;
          margin: 0.3rem 0 1rem;
        }
        .canary-status strong { border-radius: 999px; padding: 0.28rem 0.7rem; }
        .canary-status-live { background: rgba(145, 221, 176, 0.14); color: var(--canary-green); }
        .canary-status-stop { background: rgba(255, 159, 159, 0.12); color: var(--canary-red); }
        .canary-control-grid {
          display: grid;
          gap: 0.7rem;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin: 0.15rem 0 1.25rem;
        }
        .canary-control {
          background: rgba(20, 36, 58, 0.75);
          border: 1px solid rgba(166, 182, 199, 0.16);
          border-radius: 12px;
          padding: 0.8rem 0.9rem;
        }
        .canary-control span, .canary-control small { color: var(--canary-muted); display: block; }
        .canary-control span { font-size: 0.78rem; }
        .canary-control strong { color: var(--canary-ink); display: block; margin: 0.12rem 0; }
        .canary-control small { font-size: 0.72rem; }
        .canary-target, .canary-position {
          background: linear-gradient(155deg, rgba(24, 44, 68, 0.96), rgba(13, 27, 45, 0.97));
          border: 1px solid var(--canary-border);
          border-radius: 16px;
          box-shadow: 0 16px 38px rgba(0, 0, 0, 0.2);
          margin: 0.25rem 0 1rem;
          padding: 1.1rem;
        }
        .canary-card-topline { align-items: center; display: flex; flex-wrap: wrap; gap: 0.55rem; justify-content: space-between; }
        .canary-side-pill, .canary-stale-pill {
          border-radius: 999px;
          font-size: 0.72rem;
          font-weight: 800;
          padding: 0.27rem 0.6rem;
        }
        .canary-side-pill { background: var(--canary-teal); color: #05201d; }
        .canary-stale-pill { background: rgba(242, 200, 121, 0.16); color: var(--canary-amber); }
        .canary-decision { color: var(--canary-muted); font-size: 0.72rem; letter-spacing: 0.04em; }
        .canary-target h3, .canary-position h3 { color: var(--canary-ink); font-size: 1.2rem; margin: 0.9rem 0 0.1rem; }
        .canary-card-date, .canary-hold { color: var(--canary-muted); font-size: 0.8rem; }
        .canary-hold { line-height: 1.45; }
        .canary-stat-grid { display: grid; gap: 0.58rem; grid-template-columns: 1fr 1fr; margin: 1rem 0; }
        .canary-stat-grid div { background: rgba(7, 18, 31, 0.52); border-radius: 9px; padding: 0.65rem; }
        .canary-stat-grid span { color: var(--canary-muted); display: block; font-size: 0.73rem; }
        .canary-stat-grid strong { color: var(--canary-ink); display: block; font-size: 0.96rem; margin-top: 0.1rem; }
        .canary-market-link { color: var(--canary-teal) !important; display: inline-block; font-weight: 650; margin-top: 0.8rem; text-decoration: none; }
        .canary-market-link:focus-visible, .canary-nav a:focus-visible { outline: 3px solid #fff; outline-offset: 4px; border-radius: 3px; }
        .canary-activity, .canary-blockers { list-style: none; margin: 0; padding: 0; }
        .canary-activity-item, .canary-blocker {
          background: rgba(20, 36, 58, 0.66);
          border-left: 3px solid rgba(94, 224, 210, 0.55);
          border-radius: 0 9px 9px 0;
          display: grid;
          gap: 0.18rem;
          margin: 0.48rem 0;
          padding: 0.7rem 0.85rem;
        }
        .canary-activity-item time, .canary-activity-item span, .canary-blocker span { color: var(--canary-muted); font-size: 0.8rem; }
        .canary-activity-item strong, .canary-blocker strong { color: var(--canary-ink); }
        .canary-blocker { border-left-color: rgba(255, 159, 159, 0.7); }
        .canary-provenance { margin: 0; }
        .canary-provenance div { border-bottom: 1px solid rgba(166, 182, 199, 0.12); display: grid; gap: 0.8rem; grid-template-columns: minmax(9rem, 0.35fr) 1fr; padding: 0.45rem 0; }
        .canary-provenance dt { color: var(--canary-muted); }
        .canary-provenance dd { color: var(--canary-ink); margin: 0; overflow-wrap: anywhere; }
        .canary-nav { border-top: 1px solid rgba(166, 182, 199, 0.18); color: var(--canary-muted); display: flex; flex-wrap: wrap; gap: 1.1rem; margin-top: 2rem; padding-top: 1rem; }
        .canary-nav a { color: var(--canary-teal) !important; text-decoration: none; }
        @media (max-width: 760px) {
          .canary-control-grid { grid-template-columns: 1fr; }
          .canary-stat-grid { grid-template-columns: 1fr; }
          .canary-provenance div { grid-template-columns: 1fr; gap: 0.15rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    @st.fragment(run_every=f"{live_refresh_seconds}s")
    def render_overview() -> None:
        try:
            payload = _load_home_payload()
        except Exception:
            _LOGGER.exception("Capital-canary homepage adapter failed")
            payload = {
                "schema_version": "capital_canary_dashboard_v0.1",
                "source_status": "INVALID",
                "display_state": "LOCKED",
                "status_message": (
                    "The capital-canary adapter failed safely. Worker submission state is "
                    "unknown and capital placement must remain disabled."
                ),
                "freshness": {
                    "stale": True,
                    "position_data_stale": True,
                    "not_assumed_flat": True,
                },
                "safety": {
                    "capital_locked": True,
                    "order_submission_enabled": False,
                },
                "blockers": [
                    {
                        "code": "homepage_adapter_error",
                        "detail": "Read-only dashboard projection could not be validated.",
                    }
                ],
            }
        _render_page_body(payload)

    render_overview()
    st.stop()
