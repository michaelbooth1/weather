"""Read-only paper-bet homepage for the Streamlit app."""

from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.parse import urlsplit

import streamlit as st


_READY_STATUS = "READY"


def _load_home_payload() -> dict:
    """Keep the provider lazy so the router stays cheap and tests can patch it."""
    from weather.reporting.market.safe_bets import load_safe_bets_payload

    payload = load_safe_bets_payload()
    return dict(payload) if isinstance(payload, Mapping) else {}


def _finite_number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _money(value) -> str:
    number = _finite_number(value)
    return "-" if number is None else f"${number:,.2f}"


def _percent(value, *, signed: bool = False) -> str:
    number = _finite_number(value)
    if number is None:
        return "-"
    # Domain probabilities and edges are decimals. Tolerate preformatted percent
    # magnitudes defensively at this display boundary.
    magnitude = number * 100.0 if abs(number) <= 1.0 else number
    return f"{magnitude:+.1f}%" if signed else f"{magnitude:.1f}%"


def _duration(value) -> str:
    seconds = _finite_number(value)
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60.0:.1f}m"


def _count(value) -> str:
    number = _finite_number(value)
    if number is None:
        return "-"
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _timestamp(value) -> str:
    if value in (None, ""):
        return "not yet available"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _text(value, fallback: str = "-") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _candidate_link(candidate: Mapping) -> str:
    href = _text(candidate.get("market_url"), "")
    if not href:
        market_id = _text(candidate.get("market_id"), "")
        return f"/?market={market_id}" if market_id else "/?market=overview"
    parsed = urlsplit(href)
    if href.startswith("/?") or (parsed.scheme in {"http", "https"} and parsed.netloc):
        return href
    return "/?market=overview"


def _status_name(payload: Mapping) -> str:
    raw_status = payload.get("status")
    if isinstance(raw_status, Mapping):
        raw_status = raw_status.get("status") or raw_status.get("state")
    return _text(raw_status, "BLOCKED").upper()


def _candidate_rows(payload: Mapping) -> list[Mapping]:
    candidates = payload.get("recommendations")
    if candidates is None:
        candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [candidate for candidate in candidates[:3] if isinstance(candidate, Mapping)]


def _metric_value(metrics: Mapping, *keys, fallback=None):
    for key in keys:
        if metrics.get(key) is not None:
            return metrics[key]
    return fallback


def _candidate_value(candidate: Mapping, *keys, fallback=None):
    for key in keys:
        if candidate.get(key) is not None:
            return candidate[key]
    return fallback


def _render_candidate(candidate: Mapping) -> None:
    side = html.escape(
        _text(_candidate_value(candidate, "side_label", "display_side", "side"), "PAPER BET")
    )
    market = html.escape(
        _text(candidate.get("market_label") or candidate.get("city_label"), "Weather market")
    )
    target_date = html.escape(_text(candidate.get("target_date"), "date pending"))
    range_label = html.escape(
        _text(_candidate_value(candidate, "range_label", "native_range_label"), "Native range unavailable")
    )
    market_link = html.escape(_candidate_link(candidate), quote=True)
    evidence_days = _count(
        _candidate_value(candidate, "independent_target_days", "independent_days", "evidence_days")
    )
    samples = _count(
        _candidate_value(candidate, "settled_sample_size", "sample_size", "evidence_sample_size")
    )
    skill = _percent(_candidate_value(candidate, "after_fee_skill", "skill_after_fees"), signed=True)
    model_age = _duration(_candidate_value(candidate, "model_age_seconds", "model_age_s"))
    book_age = _duration(_candidate_value(candidate, "book_age_seconds", "book_age_s"))
    strategy_id = html.escape(
        _text(_candidate_value(candidate, "strategy_id", "strategy_name"), "paper policy")
    )
    strategy_status = html.escape(_text(candidate.get("strategy_status"), "paper"))

    st.markdown(
        f"""
        <div class="safe-bet-card">
          <div class="safe-card-topline">
            <span class="safe-side-pill">{side}</span>
            <span class="safe-paper-label">CAPPED PAPER POSITION</span>
          </div>
          <div class="safe-market">{market}</div>
          <div class="safe-contract">{range_label}</div>
          <div class="safe-date">Settlement date: {target_date}</div>
          <div class="safe-stat-grid">
            <div><span>Executable ask</span><strong>{_percent(_candidate_value(candidate, "executable_price", "entry_price"))}</strong></div>
            <div><span>Conservative estimate</span><strong>{_percent(_candidate_value(candidate, "conservative_probability", "conservative_win_probability"))}</strong></div>
            <div><span>After-cost edge</span><strong>{_percent(_candidate_value(candidate, "after_cost_ev_per_share", "after_cost_edge"), signed=True)}</strong></div>
            <div><span>Paper stake</span><strong>{_money(_candidate_value(candidate, "paper_stake_usdc", "paper_allocation_usdc"))}</strong></div>
            <div><span>Maximum loss</span><strong>{_money(_candidate_value(candidate, "max_loss_usdc", "paper_stake_usdc", "paper_allocation_usdc"))}</strong></div>
            <div><span>Profit if right</span><strong>{_money(_candidate_value(candidate, "profit_if_right_usdc", "profit_if_wins_usdc"))}</strong></div>
          </div>
          <div class="safe-evidence">
            Paper arm: {strategy_id} / {strategy_status}<br>
            Evidence: {html.escape(evidence_days)} independent days / {html.escape(samples)} samples
            &nbsp;&middot;&nbsp; after-fee skill {html.escape(skill)}<br>
            Freshness: model {html.escape(model_age)} / order book {html.escape(book_age)}
          </div>
          <a class="safe-market-link" href="{market_link}" target="_self">Open market evidence</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_status(status: str, payload: Mapping) -> None:
    message = _text(payload.get("status_message") or payload.get("message"), "")
    if status == "LOADING":
        st.warning(message or "A paper-run file is still being copied. Waiting for one complete, validated run.")
    elif status == "NO_DATA":
        st.info(message or "Waiting for the first complete paper-taker run on this workstation.")
    elif status == "STALE":
        st.warning(message or "The latest paper evidence is stale. No bets are shown until it refreshes.")
    elif status == "NO_BETS":
        st.info(message or "No bets clear every safety gate right now.")
    else:
        st.error(message or "Safety gates blocked this shortlist. No bets are shown.")


def _render_metrics(payload: Mapping, candidate_count: int) -> None:
    metrics = payload.get("fund")
    if not isinstance(metrics, Mapping):
        metrics = payload.get("paper_metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    columns = st.columns(5)
    columns[0].metric(
        "Test budget",
        _money(
            _metric_value(
                metrics,
                "budget_usdc",
                "fund_usdc",
                "paper_fund_usdc",
                "test_fund_usdc",
                "starting_fund_usdc",
            )
        ),
    )
    columns[1].metric(
        "Paper spent",
        _money(
            _metric_value(
                metrics,
                "spent_usdc",
                "capital_at_risk_usdc",
                "paper_committed_usdc",
                "staked_usdc",
                "allocated_usdc",
            )
        ),
    )
    columns[2].metric(
        "Remaining",
        _money(_metric_value(metrics, "remaining_usdc", "available_usdc")),
    )
    columns[3].metric(
        "Paper net P&L",
        _money(_metric_value(metrics, "net_pnl_usdc", "mark_to_market_pnl_usdc")),
    )
    columns[4].metric("Passing bets", candidate_count)


def _render_blockers(payload: Mapping) -> None:
    blockers = payload.get("blocker_counts")
    if not isinstance(blockers, Mapping) or not blockers:
        st.caption("No rejected-candidate counts were reported by the latest complete run.")
        return
    rows = []
    for reason, count in sorted(
        blockers.items(), key=lambda item: (-(_finite_number(item[1]) or 0), str(item[0]))
    ):
        rows.append(f"**{html.escape(_text(reason).replace('_', ' ').title())}:** {html.escape(_text(count, '0'))}")
    st.markdown(" &nbsp;&nbsp; ".join(rows), unsafe_allow_html=True)


def _render_provenance(payload: Mapping) -> None:
    provenance = payload.get("provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    with st.expander("Data provenance and safety gates"):
        st.caption(
            "This page reads persisted paper-run output. It cannot place orders, change releases, "
            "or bypass freshness and evidence gates."
        )
        if not provenance:
            st.write("No provenance was available for this run.")
            return
        for key, value in sorted(provenance.items()):
            if isinstance(value, (dict, list)):
                rendered = json.dumps(value, sort_keys=True, default=str)
            else:
                rendered = _text(value)
            st.markdown(f"**{html.escape(str(key).replace('_', ' ').title())}:** `{html.escape(rendered)}`")


def _render_page_body(payload: Mapping) -> None:
    status = _status_name(payload)
    candidates = _candidate_rows(payload) if status == _READY_STATUS else []
    as_of_value = (
        payload.get("as_of_utc")
        if "as_of_utc" in payload
        else payload.get("generated_at_utc")
    )
    generated_at = _timestamp(as_of_value)
    status_class = "safe-status-ready" if status == _READY_STATUS else "safe-status-warn"

    st.markdown('<span class="safe-kicker">PAPER FUND / READ ONLY</span>', unsafe_allow_html=True)
    st.title("Safest bets right now")
    st.caption("Paper-only, settlement-scored shortlist. No outcome is guaranteed.")
    st.caption(
        "Market prices above 90% remain eligible only when evidence, freshness, liquidity, "
        "and after-cost value all clear their gates."
    )
    st.markdown(
        f'<div class="safe-asof">Gate status: <strong class="{status_class}">{html.escape(status)}</strong> &nbsp;&middot;&nbsp; '
        f'As of {html.escape(generated_at)}</div>',
        unsafe_allow_html=True,
    )

    _render_metrics(payload, len(candidates))

    if candidates:
        card_columns = st.columns(len(candidates), gap="large")
        for column, candidate in zip(card_columns, candidates):
            with column:
                _render_candidate(candidate)
    else:
        _render_status("NO_BETS" if status == _READY_STATUS else status, payload)

    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if warning:
                st.warning(str(warning))

    st.markdown("### Why other bets were held back")
    _render_blockers(payload)
    _render_provenance(payload)

    st.markdown(
        """
        <div class="safe-nav">
          <span>Continue investigating:</span>
          <a href="/?market=mm" target="_self">Paper runs</a>
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
          --safe-navy: #0b1729;
          --safe-navy-soft: #15243a;
          --safe-ink: #eaf1f8;
          --safe-muted: #9eafc1;
          --safe-teal: #4fd1c5;
          --safe-green: #8bd3a6;
          --safe-border: rgba(111, 211, 199, 0.23);
        }
        [data-testid="stAppViewContainer"] {
          background: radial-gradient(circle at 80% 0%, #18304a 0, #0b1729 34%, #08111f 100%);
          color: var(--safe-ink);
        }
        [data-testid="stHeader"] { background: rgba(8, 17, 31, 0.82); }
        [data-testid="stSidebar"] { background: #0d1929; }
        [data-testid="stMetric"] {
          background: rgba(21, 36, 58, 0.78);
          border: 1px solid rgba(158, 175, 193, 0.15);
          border-radius: 12px;
          padding: 0.85rem 1rem;
        }
        [data-testid="stMetricLabel"] p { color: var(--safe-muted) !important; }
        [data-testid="stMetricValue"] {
          color: var(--safe-ink) !important;
          font-size: 1.75rem !important;
        }
        [data-testid="stAlert"] p { color: #c8d8e9 !important; }
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
          color: #b7c4d2 !important;
        }
        .safe-kicker {
          display: inline-block;
          color: var(--safe-teal);
          background: rgba(79, 209, 197, 0.11);
          border: 1px solid rgba(79, 209, 197, 0.28);
          border-radius: 999px;
          padding: 0.3rem 0.7rem;
          font-size: 0.72rem;
          font-weight: 750;
          letter-spacing: 0.09em;
        }
        .safe-asof { color: var(--safe-muted); margin: 0.1rem 0 1.35rem; }
        .safe-status-ready { color: var(--safe-green); }
        .safe-status-warn { color: #f2c879; }
        .safe-bet-card {
          min-height: 29rem;
          background: linear-gradient(155deg, rgba(24, 44, 68, 0.96), rgba(13, 27, 45, 0.96));
          border: 1px solid var(--safe-border);
          border-radius: 17px;
          box-shadow: 0 18px 45px rgba(0, 0, 0, 0.22);
          padding: 1.25rem;
          margin: 0.4rem 0 1.3rem;
        }
        .safe-card-topline { display: flex; justify-content: space-between; align-items: center; gap: 0.6rem; }
        .safe-side-pill {
          color: #05201d;
          background: var(--safe-teal);
          border-radius: 999px;
          padding: 0.28rem 0.62rem;
          font-size: 0.74rem;
          font-weight: 800;
          white-space: nowrap;
        }
        .safe-paper-label { color: var(--safe-muted); font-size: 0.64rem; letter-spacing: 0.06em; }
        .safe-market { color: var(--safe-muted); font-size: 0.9rem; margin-top: 1.15rem; }
        .safe-contract { color: var(--safe-ink); font-size: 1.45rem; font-weight: 750; line-height: 1.15; margin-top: 0.2rem; }
        .safe-date { color: var(--safe-muted); font-size: 0.78rem; margin-top: 0.35rem; }
        .safe-stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.65rem; margin: 1.25rem 0; }
        .safe-stat-grid div { background: rgba(7, 18, 31, 0.5); border-radius: 10px; padding: 0.7rem; }
        .safe-stat-grid span { color: var(--safe-muted); display: block; font-size: 0.69rem; }
        .safe-stat-grid strong { color: var(--safe-ink); display: block; font-size: 1.03rem; margin-top: 0.1rem; }
        .safe-evidence { color: var(--safe-muted); font-size: 0.75rem; line-height: 1.55; min-height: 3.4rem; }
        .safe-market-link {
          display: inline-block;
          color: var(--safe-teal) !important;
          border-bottom: 1px solid rgba(79, 209, 197, 0.4);
          margin-top: 0.9rem;
          text-decoration: none;
          font-weight: 650;
        }
        .safe-nav {
          border-top: 1px solid rgba(158, 175, 193, 0.18);
          color: var(--safe-muted);
          display: flex;
          flex-wrap: wrap;
          gap: 1.15rem;
          margin-top: 2rem;
          padding: 1.15rem 0 0.25rem;
        }
        .safe-nav a { color: var(--safe-teal) !important; text-decoration: none; }
        @media (max-width: 640px) {
          .safe-bet-card { min-height: auto; }
          .safe-stat-grid { grid-template-columns: 1fr; }
          .safe-card-topline { align-items: flex-start; flex-direction: column; }
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
            # The sync can expose a partial file between atomic units. The home
            # page remains usable and, critically, never displays older bets.
            payload = {
                "status": "LOADING",
                "message": "The latest paper-run evidence is incomplete. Waiting for sync to finish.",
            }
        _render_page_body(payload)

    render_overview()
    st.stop()
