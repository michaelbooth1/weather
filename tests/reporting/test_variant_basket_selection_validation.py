import csv
import json

from weather.reporting.validation.variant_basket_selection_validation import (
    NO_GO_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_payload,
    render_report,
    write_outputs,
)


def write_rows(path, rows):
    fieldnames = [
        "variant_id",
        "variant_family",
        "market_id",
        "target_date",
        "snapshot_id",
        "band_key",
        "probability",
        "current_probability",
        "market_yes",
        "outcome",
        "cutoff_regime",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row(variant, market, date, snapshot, prob, current, market_yes, outcome):
    return {
        "variant_id": variant,
        "variant_family": "test",
        "market_id": market,
        "target_date": date,
        "snapshot_id": snapshot,
        "band_key": "eq:70-71",
        "probability": prob,
        "current_probability": current,
        "market_yes": market_yes,
        "outcome": outcome,
    }


def test_selects_on_train_and_evaluates_later_dates(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    write_rows(a, [
        row("a", "m1", "2026-06-07", "s1", 0.9, 0.5, 0.8, 1),
        row("a", "m1", "2026-06-08", "s2", 0.2, 0.5, 0.8, 1),
    ])
    write_rows(b, [
        row("b", "m1", "2026-06-07", "s1", 0.1, 0.5, 0.8, 1),
        row("b", "m1", "2026-06-08", "s2", 0.9, 0.5, 0.8, 1),
    ])

    payload = build_payload([a, b], market_tol=0.003)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["acceptance"] == "blocked"
    result = payload["market_results"][0]
    assert result["selected_variant_id"] == "a"
    assert result["eval_oracle_variant_id"] == "b"
    assert result["selected_eval"]["delta_vs_current"] > 0


def test_known_failed_basket_no_go_blocks_repeat_without_new_evidence(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    write_rows(a, [
        row("a", "m1", "2026-06-07", "s1", 0.9, 0.5, 0.8, 1),
        row("a", "m1", "2026-06-08", "s2", 0.2, 0.5, 0.8, 1),
    ])
    write_rows(b, [
        row("b", "m1", "2026-06-07", "s1", 0.1, 0.5, 0.8, 1),
        row("b", "m1", "2026-06-08", "s2", 0.9, 0.5, 0.8, 1),
    ])
    first = build_payload([a, b], market_tol=0.003)
    rerun = build_payload([a, b], market_tol=0.003, known_no_go=first["no_go_disposition"])
    json_out = tmp_path / "payload.json"
    report_out = tmp_path / "payload.md"
    no_go_out = tmp_path / "no_go.json"
    write_outputs(rerun, json_out, report_out, no_go_out=no_go_out)
    report = report_out.read_text(encoding="utf-8")
    saved_no_go = json.loads(no_go_out.read_text(encoding="utf-8"))

    assert first["no_go_disposition"]["schema_version"] == NO_GO_SCHEMA_VERSION
    assert first["no_go_disposition"]["status"] == "NO_GO"
    assert rerun["known_no_go_guard"]["status"] == "BLOCK"
    assert any("known no-go disposition matched" in reason for reason in rerun["acceptance_reasons"])
    assert saved_no_go["schema_version"] == NO_GO_SCHEMA_VERSION
    assert "Blocked-Market Basket No-Go Disposition" in report
    assert "item-219-bottom-location-early-midday-winner-centering" in report
    assert "diagnostic_only" in report


def test_known_failed_basket_no_go_warns_when_new_market_day_exists(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    write_rows(a, [
        row("a", "m1", "2026-06-07", "s1", 0.9, 0.5, 0.8, 1),
        row("a", "m1", "2026-06-08", "s2", 0.2, 0.5, 0.8, 1),
    ])
    write_rows(b, [
        row("b", "m1", "2026-06-07", "s1", 0.1, 0.5, 0.8, 1),
        row("b", "m1", "2026-06-08", "s2", 0.9, 0.5, 0.8, 1),
    ])
    known = build_payload([a, b], market_tol=0.003)["no_go_disposition"]
    write_rows(a, [
        row("a", "m1", "2026-06-07", "s1", 0.9, 0.5, 0.8, 1),
        row("a", "m1", "2026-06-08", "s2", 0.2, 0.5, 0.8, 1),
        row("a", "m1", "2026-06-09", "s3", 0.2, 0.5, 0.8, 1),
    ])
    write_rows(b, [
        row("b", "m1", "2026-06-07", "s1", 0.1, 0.5, 0.8, 1),
        row("b", "m1", "2026-06-08", "s2", 0.9, 0.5, 0.8, 1),
        row("b", "m1", "2026-06-09", "s3", 0.9, 0.5, 0.8, 1),
    ])

    payload = build_payload([a, b], market_tol=0.003, known_no_go=known)

    assert payload["known_no_go_guard"]["status"] == "WARN"
    assert payload["known_no_go_guard"]["new_market_days"] == [
        {"market_id": "m1", "target_date": "2026-06-09"}
    ]


def test_current_control_can_be_selected(tmp_path):
    a = tmp_path / "a.csv"
    write_rows(a, [
        row("a", "m1", "2026-06-07", "s1", 0.1, 0.9, 0.8, 1),
        row("a", "m1", "2026-06-08", "s2", 0.1, 0.9, 0.8, 1),
    ])

    payload = build_payload([a], market_tol=0.003)

    result = payload["market_results"][0]
    assert result["selected_variant_id"] == "current"
    assert result["selected_eval"]["candidate_brier"] == result["selected_eval"]["current_brier"]


def test_report_mentions_oracle_is_diagnostic(tmp_path):
    a = tmp_path / "a.csv"
    write_rows(a, [
        row("a", "m1", "2026-06-07", "s1", 0.9, 0.5, 0.8, 1),
        row("a", "m1", "2026-06-08", "s2", 0.9, 0.5, 0.8, 1),
    ])
    payload = build_payload([a], market_tol=0.003)
    report = render_report(payload)
    assert "Eval oracle columns are diagnostic only" in report


def test_slice_policy_reports_train_selected_branch(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    write_rows(a, [
        {**row("a", "m1", "2026-06-07", "s1", 0.9, 0.5, 0.8, 1), "cutoff_regime": "early"},
        {**row("a", "m1", "2026-06-08", "s2", 0.9, 0.5, 0.8, 1), "cutoff_regime": "early"},
    ])
    write_rows(b, [
        {**row("b", "m1", "2026-06-07", "s1", 0.2, 0.5, 0.8, 1), "cutoff_regime": "early"},
        {**row("b", "m1", "2026-06-08", "s2", 0.2, 0.5, 0.8, 1), "cutoff_regime": "early"},
    ])

    payload = build_payload(
        [a, b],
        market_tol=0.003,
        slice_keys=("cutoff_regime",),
        min_slice_train_rows=1,
    )

    result = payload["slice_policy_results"][0]
    assert result["slice_key"] == "cutoff_regime"
    assert result["non_current_selection_count"] == 1
    assert result["non_current_selections"][0]["selected_variant_id"] == "a"


def test_leave_one_date_stability_reports_selection_counts(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    write_rows(a, [
        row("a", "m1", "2026-06-07", "s1", 0.9, 0.5, 0.8, 1),
        row("a", "m1", "2026-06-08", "s2", 0.9, 0.5, 0.8, 1),
        row("a", "m1", "2026-06-12", "s3", 0.1, 0.5, 0.8, 1),
    ])
    write_rows(b, [
        row("b", "m1", "2026-06-07", "s1", 0.1, 0.5, 0.8, 1),
        row("b", "m1", "2026-06-08", "s2", 0.1, 0.5, 0.8, 1),
        row("b", "m1", "2026-06-12", "s3", 0.9, 0.5, 0.8, 1),
    ])

    payload = build_payload([a, b], market_tol=0.003)
    result = payload["leave_one_date_results"][0]

    assert result["date_count"] == 3
    assert result["selected_variant_counts"]
    assert result["eval_oracle_variant_counts"]["a"] >= 1
    assert "Leave-One-Market-Day Stability" in render_report(payload)


def test_guard_policy_results_report_fixed_and_selected_scores(tmp_path):
    a = tmp_path / "a.csv"
    rows = []
    for day, early_prob, late_prob in [
        ("2026-06-07", 0.1, 0.9),
        ("2026-06-08", 0.1, 0.9),
        ("2026-06-12", 0.1, 0.9),
    ]:
        rows.append({
            **row("a", "m1", day, f"{day}-early", early_prob, 0.9, 0.8, 1),
            "cutoff_regime": "early",
        })
        rows.append({
            **row("a", "m1", day, f"{day}-late", late_prob, 0.1, 0.8, 1),
            "cutoff_regime": "late",
        })
    write_rows(a, rows)

    payload = build_payload([a], market_tol=0.003)
    result = payload["guard_policy_results"][0]
    report = render_report(payload)

    assert result["best_fixed_policy"] in {"midday_late", "not_early"}
    assert result["selected_policy_counts"]
    assert "Guarded Branch Policies" in report
