"""Markdown rendering for source-family inventory artifacts."""

from __future__ import annotations

from pathlib import Path

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table


DEFAULT_REPORT_OUT = data_path() / "backtest" / "source_family_inventory_report.md"


def _fmt_counts(mapping):
    return ", ".join(f"{key}: {value}" for key, value in (mapping or {}).items()) or "-"


def write_report(payload, report_out=DEFAULT_REPORT_OUT):
    report_out = Path(report_out)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    rows = payload.get("inventory") or []
    reader_summary = payload.get("historical_reader_summary") or {}

    lines = [
        "# Source Family Inventory",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: {payload.get('status')}",
        "Serving/release authorization: `false`",
        (
            "This inventory is a detached diagnostic artifact. Runtime "
            "current-input revalidation is required before any serving or release "
            "authorization."
        ),
        "",
        "## Summary",
        "",
    ]
    summary = payload.get("summary") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Families", summary.get("family_count")],
            ["Blocking families", summary.get("blocking_family_count")],
            ["Snapshot folders", summary.get("snapshot_folder_count")],
            ["Historical reader modes", _fmt_counts(summary.get("historical_reader_modes"))],
            ["Ablation variants", summary.get("ablation_variant_count")],
            ["Active model usage", summary.get("active_model_usage_status")],
            ["Active model features", summary.get("active_model_feature_count")],
            ["Active overlay families", ", ".join(summary.get("active_overlay_families") or []) or "-"],
            ["NBM station archive", summary.get("nbm_station_archive_status") or "-"],
            ["NBM station archive rows", summary.get("nbm_station_archive_rows")],
            ["Open-Meteo AQ archive", summary.get("open_meteo_aq_archive_status") or "-"],
            ["Open-Meteo AQ archive markets", summary.get("open_meteo_aq_archive_markets")],
            ["Open-Meteo global-model archive", summary.get("open_meteo_global_model_archive_status") or "-"],
            ["Open-Meteo global-model archive markets", summary.get("open_meteo_global_model_archive_markets")],
            ["Market expansion status", summary.get("market_expansion_status")],
        ],
    )
    open_meteo_archive = (payload.get("open_meteo_archive_evidence") or {}).get("open_meteo_expanded") or {}
    if open_meteo_archive:
        lines += ["", "## Open-Meteo AQ Archive", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", open_meteo_archive.get("historical_archive_status")],
                ["Root", open_meteo_archive.get("archive_root")],
                ["Markets", open_meteo_archive.get("market_count")],
                ["Covered markets", open_meteo_archive.get("covered_market_count")],
                ["Covered", ", ".join(open_meteo_archive.get("covered_markets") or []) or "-"],
                ["Missing", ", ".join(open_meteo_archive.get("missing_markets") or []) or "-"],
            ],
        )
    global_model_archive = (payload.get("open_meteo_archive_evidence") or {}).get("multi_model_guidance") or {}
    if global_model_archive:
        lines += ["", "## Open-Meteo Global Model Archive", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", global_model_archive.get("historical_archive_status")],
                ["Root", global_model_archive.get("archive_root")],
                ["Markets", global_model_archive.get("market_count")],
                ["Covered markets", global_model_archive.get("covered_market_count")],
                ["Covered", ", ".join(global_model_archive.get("covered_markets") or []) or "-"],
                ["Missing", ", ".join(global_model_archive.get("missing_markets") or []) or "-"],
            ],
        )
    nbm_station_archive = payload.get("nbm_station_archive") or {}
    if nbm_station_archive:
        lines += ["", "## NBM Station Archive", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", nbm_station_archive.get("status")],
                ["Root", nbm_station_archive.get("root")],
                ["Rows", nbm_station_archive.get("row_count")],
                ["Replay-safe rows", nbm_station_archive.get("replay_safe_row_count")],
                ["Failed rows", nbm_station_archive.get("failed_row_count")],
                ["Stations", ", ".join(nbm_station_archive.get("station_ids") or []) or "-"],
                ["Target dates", ", ".join(nbm_station_archive.get("target_dates") or []) or "-"],
            ],
        )
    if reader_summary:
        lines += ["", "## Historical Reader Sources", ""]
        families = reader_summary.get("families") or {}
        lines += markdown_table(
            ["Artifact Family", "Reads", "Rows", "Source Modes", "Fallback Reasons"],
            [
                [
                    family,
                    item.get("reads"),
                    item.get("rows"),
                    _fmt_counts(item.get("source_modes")),
                    _fmt_counts(item.get("fallback_reasons")),
                ]
                for family, item in families.items()
            ],
        )
    lines += ["", "## Inventory", ""]
    lines += markdown_table(
        [
            "Family",
            "Lineage",
            "Parity",
            "Ablation",
            "Decision",
            "Active input",
            "Active features",
            "Missing rate",
            "Live-only policy",
        ],
        [
            [
                row.get("family_id"),
                row.get("lineage_status"),
                row.get("train_serve_parity_status"),
                (row.get("ablation") or {}).get("status"),
                (row.get("promotion_decision") or {}).get("status"),
                "yes" if row.get("model_influence") else "no",
                row.get("active_model_feature_count"),
                fmt_num((row.get("feature_missingness") or {}).get("missing_rate"), 3),
                row.get("live_only_policy"),
            ]
            for row in rows
        ],
    )
    reanalysis = next((row for row in rows if row.get("family_id") == "reanalysis_synoptic"), None)
    reanalysis_lane = (reanalysis or {}).get("promotion_lane") or {}
    if reanalysis_lane:
        lines += ["", "## Reanalysis Promotion Lane", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", reanalysis_lane.get("status")],
                ["Policy", reanalysis_lane.get("policy")],
                ["Allowed markets", ", ".join(reanalysis_lane.get("allowed_markets") or []) or "-"],
                ["Quarantined markets", ", ".join(reanalysis_lane.get("quarantined_markets") or []) or "-"],
                ["Thin-margin markets", ", ".join(reanalysis_lane.get("thin_margin_markets") or []) or "-"],
                ["Reason", reanalysis_lane.get("reason")],
                ["Action", reanalysis_lane.get("action")],
            ],
        )
    artifact_lane = (reanalysis or {}).get("artifact_promotion_lane") or {}
    consistency = (reanalysis or {}).get("artifact_lane_consistency") or {}
    if artifact_lane or consistency:
        lines += ["", "## Reanalysis Artifact Promotion Lane", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Consistency", consistency.get("status")],
                ["Consistency reason", consistency.get("reason")],
                ["Status", artifact_lane.get("status")],
                ["Policy", artifact_lane.get("policy")],
                ["Allowed markets", ", ".join(artifact_lane.get("allowed_markets") or []) or "-"],
                ["Quarantined markets", ", ".join(artifact_lane.get("quarantined_markets") or []) or "-"],
                [
                    "Blocked reanalysis fields",
                    ", ".join(artifact_lane.get("blocked_feature_columns") or []) or "-",
                ],
                ["Reason", artifact_lane.get("reason")],
                ["Action", artifact_lane.get("action")],
            ],
        )
    reanalysis_details = ((reanalysis or {}).get("ablation") or {}).get("market_details") or []
    if reanalysis_details:
        lines += ["", "## Reanalysis Market Gates", ""]
        lines += markdown_table(
            ["Market", "Rows", "Full Brier", "Ablated Brier", "Delta Brier", "Gate"],
            [
                [
                    row.get("market_id"),
                    row.get("rows"),
                    fmt_num(row.get("full_brier"), 4),
                    fmt_num(row.get("ablated_brier"), 4),
                    fmt_signed(row.get("delta_brier"), 4),
                    row.get("decision"),
                ]
                for row in sorted(
                    reanalysis_details,
                    key=lambda item: (
                        float(item.get("delta_brier") or 0.0),
                        str(item.get("market_id") or ""),
                    ),
                    reverse=True,
                )
            ],
        )
    preflight = payload.get("promotion_preflight") or {}
    ablation_contract = preflight.get("ablation_evidence_contract") or {}
    blocking_evidence = preflight.get("blocking_evidence") or []
    evidence_details = "; ".join(
        f"{row.get('artifact')}: {row.get('status')}"
        + (
            " (" + "; ".join(row.get("blockers") or []) + ")"
            if row.get("blockers")
            else ""
        )
        for row in blocking_evidence
    )
    lines += ["", "## Promotion Preflight", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", preflight.get("status")],
            ["Blocked families", ", ".join(preflight.get("blocked_families") or []) or "-"],
            ["Ablation evidence contract", ablation_contract.get("status") or "MISSING"],
            ["Blocking evidence", evidence_details or "-"],
            ["Inventory command", preflight.get("inventory_command")],
            ["Ablation command", preflight.get("ablation_command")],
        ],
    )
    expansion = payload.get("market_expansion_scorecard") or {}
    lines += ["", "## Market Expansion Scorecard", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", expansion.get("status")],
            ["Candidates", expansion.get("candidate_count")],
            ["Blocked", expansion.get("blocked_count")],
        ],
    )
    report_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_out
