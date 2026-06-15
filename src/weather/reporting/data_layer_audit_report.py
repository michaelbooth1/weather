"""Markdown rendering for the fleet data-layer audit."""

from __future__ import annotations

from pathlib import Path

try:
    from ..backtesting.backtest import fmt_num, markdown_table
except ImportError:  # pragma: no cover - compatibility-wrapper execution
    from weather.backtesting.backtest import fmt_num, markdown_table

def _fmt_pct(value):
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def _historical_table_rows(payload):
    rows = []
    for market in payload.get("markets") or []:
        for source, item in (market.get("sources") or {}).items():
            season = item.get("target_season") or {}
            period = item.get("period") or {}
            rows.append([
                market.get("market_id"),
                source,
                item.get("daily_days"),
                f"{season.get('covered_days', 0)}/{season.get('expected_days', 0)}",
                _fmt_pct(season.get("coverage_rate")),
                f"{period.get('covered_days', 0)}/{period.get('expected_days', 0)}",
                _fmt_pct(period.get("coverage_rate")),
                item.get("path"),
            ])
    return rows


def _nearby_composite_rows(historical):
    rows = []
    for market in historical.get("markets") or []:
        nearby = market.get("nearby_history") or {}
        supplemental = nearby.get("supplemental_sources") or []
        if not supplemental:
            continue
        composite = nearby.get("composite") or {}
        season = composite.get("target_season") or {}
        period = composite.get("period") or {}
        rows.append([
            market.get("market_id"),
            "ghcnh canonical + validated supplemental",
            len(supplemental),
            composite.get("supplemental_target_season_added_days"),
            f"{season.get('covered_days', 0)}/{season.get('expected_days', 0)}",
            _fmt_pct(season.get("coverage_rate")),
            f"{period.get('covered_days', 0)}/{period.get('expected_days', 0)}",
            _fmt_pct(period.get("coverage_rate")),
            ", ".join(item.get("station") or "-" for item in supplemental[:3]),
        ])
    return rows


def _nearby_source_rows(historical):
    rows = []
    for market in historical.get("markets") or []:
        nearby = market.get("nearby_history") or {}
        for item in nearby.get("supplemental_sources") or []:
            wu_season = ((item.get("bias_vs_wu") or {}).get("target_season") or {})
            metar_season = ((item.get("bias_vs_metar") or {}).get("target_season") or {})
            promotion_gate = item.get("promotion_gate") or {}
            rows.append([
                market.get("market_id"),
                item.get("source_id"),
                item.get("station"),
                item.get("station_name") or "-",
                fmt_num(item.get("distance_km"), 2),
                item.get("validation_status") or "-",
                item.get("promotion_state") or "-",
                promotion_gate.get("status") or "-",
                "; ".join(
                    f"{window.get('start')}..{window.get('end')}"
                    for window in item.get("adopted_date_windows") or []
                ) or "-",
                item.get("adds_target_season_days"),
                item.get("daily_days"),
                wu_season.get("days") or "-",
                fmt_num(wu_season.get("mae"), 3),
                _fmt_pct(wu_season.get("bucket_match_rate")),
                metar_season.get("days") or "-",
                fmt_num(metar_season.get("mae"), 3),
                _fmt_pct(metar_season.get("bucket_match_rate")),
                promotion_gate.get("reason") or "-",
                item.get("reason_for_adoption") or "-",
                item.get("path"),
            ])
    return rows


def _snapshot_market_rows(snapshot):
    return [
        [
            row.get("market_id"),
            row.get("market_day_count"),
            row.get("settled_days"),
            row.get("clean_days"),
            row.get("replay_days"),
            row.get("replay_status_days"),
            row.get("source_status_days"),
            row.get("feature_days"),
            row.get("component_days"),
            row.get("forecast_days"),
            row.get("forecast_payload_days"),
            row.get("clob_feature_days"),
            fmt_num(row.get("median_snapshots_per_day"), 1),
            fmt_num(row.get("median_gap_minutes"), 2),
            fmt_num(row.get("max_gap_minutes"), 1),
        ]
        for row in snapshot.get("by_market") or []
    ]


def write_report(path, payload):
    path = Path(path)
    snapshot = payload.get("snapshots") or {}
    loop = payload.get("loop") or {}
    clob_loop = payload.get("clob_loop") or {}
    historical = payload.get("historical") or {}
    gates = payload.get("gates") or []
    gate_counts = payload.get("gate_summary") or {}
    gap_investigation = payload.get("historical_gap_investigation") or {}
    lines = [
        "# Data Layer Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Gate status: `{gate_counts.get('status')}`",
        "",
        "## Executive Summary",
        "",
        (
            "The weather/model loop and the fast CLOB book loop are separate by "
            "design: weather/model snapshots stay on a 5-10 minute cadence while "
            "book depth is captured on a faster supervised path."
        ),
        "",
        "## Loop And Snapshot Cadence",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Loop state", loop.get("state")],
            ["Configured interval", f"{loop.get('configured_interval_minutes')} min"],
            ["Heartbeat age", f"{loop.get('heartbeat_age_min')} min"],
            ["Last snapshot age", f"{loop.get('last_snapshot_age_min')} min"],
            ["CLOB loop state", clob_loop.get("state")],
            ["CLOB configured interval", f"{clob_loop.get('configured_interval_seconds')} sec"],
            ["CLOB fast interval", f"{clob_loop.get('fast_interval_seconds')} sec"],
            ["CLOB heartbeat age", f"{clob_loop.get('heartbeat_age_seconds')} sec"],
            ["CLOB last books age", f"{clob_loop.get('last_books_age_seconds')} sec"],
            ["CLOB error markets", ", ".join(clob_loop.get("error_markets") or []) or "-"],
            ["Snapshot folders", snapshot.get("folder_count")],
            ["Total snapshots", snapshot.get("total_snapshots")],
            ["Total band rows", snapshot.get("total_band_rows")],
            ["Clean folders", snapshot.get("clean_folder_count")],
            ["Median snapshots/folder", fmt_num(snapshot.get("median_snapshots_per_folder"), 1)],
            ["Median capture gap", f"{fmt_num(snapshot.get('median_capture_gap_minutes'), 2)} min"],
            ["Max capture gap", f"{fmt_num(snapshot.get('max_capture_gap_minutes'), 1)} min"],
            ["Market token IDs persisted", snapshot.get("has_market_token_ids")],
            ["Source-status rows", (snapshot.get("source_status") or {}).get("row_count")],
            ["Source stale/failed rate", _fmt_pct((snapshot.get("source_status") or {}).get("stale_or_failed_rate"))],
            ["CLOB feature rows", (snapshot.get("clob_features") or {}).get("row_count")],
            ["CLOB book available rate", _fmt_pct((snapshot.get("clob_features") or {}).get("book_available_rate"))],
            ["Forecast payload rows", (snapshot.get("forecast_payloads") or {}).get("row_count")],
        ],
    )
    lines += [
        "",
        "## Audit Gates",
        "",
    ]
    lines += markdown_table(
        ["Gate", "Status", "Severity", "Threshold", "Evidence", "Action"],
        [
            [
                row.get("name"),
                row.get("status"),
                row.get("severity"),
                row.get("threshold") or "-",
                row.get("evidence"),
                row.get("action") or "-",
            ]
            for row in gates
        ],
    )
    lines += [
        "",
        "## Snapshot Artifacts By Market",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Days", "Settled", "Clean", "Replay", "Replay Status",
            "Source Status", "Features", "Components", "Forecasts",
            "Payloads", "CLOB Feat", "Median Snaps", "Median Gap", "Max Gap",
        ],
        _snapshot_market_rows(snapshot),
    )
    lines += [
        "",
        "## Low-Fill Snapshot Fields",
        "",
    ]
    lines += markdown_table(
        ["Field", "Nonempty", "Total", "Fill Rate"],
        [
            [
                row.get("field"),
                row.get("nonempty"),
                row.get("total"),
                _fmt_pct(row.get("fill_rate")),
            ]
            for row in snapshot.get("low_fill_fields") or []
        ],
    )
    lines += [
        "",
        "## Historical Coverage",
        "",
        f"Full audit period: `{historical.get('start')}` to `{historical.get('end')}`.",
        f"Target season: {historical.get('target_season_window')}.",
        "",
    ]
    lines += markdown_table(
        [
            "Market", "Source", "Daily Rows", "Season Covered", "Season Rate",
            "Full Covered", "Full Rate", "Path",
        ],
        _historical_table_rows(historical),
    )
    nearby_composite_rows = _nearby_composite_rows(historical)
    nearby_source_rows = _nearby_source_rows(historical)
    if nearby_composite_rows or nearby_source_rows:
        lines += [
            "",
            "## Nearby Historical Sources",
            "",
            (
                "Supplemental nearby stations are kept separate from canonical settlement/source roots. "
                "They are useful when they add missing days with acceptable overlap bias, and should stay "
                "provenance-labelled in training features."
            ),
            "",
        ]
        if nearby_composite_rows:
            lines += markdown_table(
                [
                    "Market", "Composite", "Supp Sources", "Season Added",
                    "Season Covered", "Season Rate", "Full Covered", "Full Rate",
                    "Stations",
                ],
                nearby_composite_rows,
            )
        if nearby_source_rows:
            lines += [
                "",
                "### Supplemental Station Bias",
                "",
            ]
            lines += markdown_table(
                [
                    "Market", "Source ID", "Station", "Name", "Distance Km",
                    "Validation", "Promotion", "Gate", "Adopted Windows", "Season Added",
                    "Daily Rows", "WU Days", "WU MAE", "WU Bucket Match",
                    "METAR Days", "METAR MAE", "METAR Bucket Match",
                    "Gate Reason", "Reason", "Path",
                ],
                nearby_source_rows,
            )
    lines += [
        "",
        "## Historical Gap Investigation",
        "",
    ]
    toronto_candidates = gap_investigation.get("toronto_available_ghcnh_candidates") or []
    wu_candidates = gap_investigation.get("us_available_wu_candidates") or []
    toronto_bias = gap_investigation.get("toronto_alt_ghcnh_bias") or {}
    wu_bias = (((toronto_bias.get("comparisons") or {}).get("wu") or {}).get("target_season") or {})
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Probe path", gap_investigation.get("path") or "-"],
            ["Probe generated", gap_investigation.get("generated_at_utc") or "-"],
            ["Toronto available GHCNh candidates", len(toronto_candidates)],
            ["US available WU candidates", len(wu_candidates)],
            ["Toronto alternate bias path", toronto_bias.get("path") or "-"],
            ["Toronto alternate target-season WU days", wu_bias.get("days") or "-"],
            ["Toronto alternate target-season WU MAE C", wu_bias.get("mae_c") or "-"],
            ["Toronto alternate target-season bucket match", _fmt_pct(wu_bias.get("bucket_match_rate"))],
        ],
    )
    if toronto_candidates:
        lines += ["", "### Toronto GHCNh Candidates", ""]
        lines += markdown_table(
            ["GHCN ID", "Name", "Available Probe Years", "Distance2"],
            [
                [
                    (item.get("station") or {}).get("GHCN_ID"),
                    (item.get("station") or {}).get("NAME"),
                    ",".join(str(year) for year in item.get("available_years") or []),
                    fmt_num(item.get("distance2"), 4),
                ]
                for item in toronto_candidates[:8]
            ],
        )
    lines += [
        "",
        "## Market Microstructure References",
        "",
    ]
    lines += markdown_table(
        ["Capability", "URL", "Why It Matters"],
        [
            [item.get("name"), item.get("url"), item.get("why")]
            for item in payload.get("microstructure_reference") or []
        ],
    )
    lines += [
        "",
        "## Recommendations",
        "",
    ]
    lines += markdown_table(
        ["Priority", "Recommendation", "Evidence", "Action", "Roadmap"],
        [
            [
                item.get("priority"),
                item.get("title"),
                item.get("evidence"),
                item.get("action"),
                item.get("roadmap_item") or "-",
            ]
            for item in payload.get("recommendations") or []
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
