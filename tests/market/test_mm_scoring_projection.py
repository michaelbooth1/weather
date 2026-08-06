import csv
import json
from pathlib import Path

import pytest

from weather.market.mm_paper_scoring import load_quote_rows
from weather.market.mm_scoring_projection import (
    BASE_CANONICAL_FILENAME,
    BASE_PROJECTION_FILENAME,
    LIVE_APPEND_PREFIX_BINDING_MODE,
    MANIFEST_FILENAME,
    MODEL_VARIANT_CANONICAL_FILENAME,
    MODEL_VARIANT_PROJECTION_FILENAME,
    SCHEMA_VERSION,
    SCORING_COLUMNS,
    main,
    resolve_run_scoring_inputs,
    write_run_scoring_projections,
)


PROVENANCE_COLUMNS = (
    "schema_version",
    "model_variant_runtime_identity",
    "worker_release_commit",
    "worker_release_manifest_hash",
    "source_snapshot_id",
)


def _write_csv(path: Path, fieldnames, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def _append_csv_row(path: Path, row) -> None:
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_read_header(path))
        writer.writerow(row)


def _current_row(
    *,
    run_id: str,
    variant_id: str = "",
    target_date: str = "2026-07-18",
) -> dict[str, str]:
    row = {column: "" for column in SCORING_COLUMNS}
    row.update({
        "run_id": run_id,
        "target_date": target_date,
        "run_mode": "paper-live-forward",
        "generated_at_utc": f"{target_date}T16:00:00+00:00",
        "captured_at_utc": f"{target_date}T15:59:45+00:00",
        "capture_hour_local": "11",
        "policy_hash": "policy-current",
        "live_trade_permission": "False",
        "quote_permission": "True",
        "regime": "harvest",
        "reason_code": "QUOTE_HARVEST_MID",
        "market_id": "atlanta",
        "event_slug": (
            "highest-temperature-in-atlanta-on-july-18-2026"
            if target_date == "2026-07-18"
            else f"synthetic-high-temperature-on-{target_date}"
        ),
        "range_label": "90-91 F",
        "bin_kind": "range",
        "bin_value": "90",
        "bin_value_hi": "91",
        "clob_token_id": "token-atlanta-90",
        "fair_probability": "0.35",
        "market_mid": "0.32",
        "market_yes": "0.32",
        "edge": "0.03",
        "bid_price": "0.31",
        "bid_size": "5",
        "ask_price": "0.34",
        "ask_size": "5",
        "book_spread": "0.03",
        "book_imbalance_1pct": "0.10",
        "source_fresh": "True",
        "source_freshness_state": "fresh",
        "model_version": "maker-current",
        "served_model_version": "maker-current",
        "model_variant_id": variant_id,
        "model_variant_family": "test" if variant_id else "",
        "model_variant_role": "shadow" if variant_id else "",
        "model_variant_basket_id": "basket-current" if variant_id else "",
        "model_variant_probability_source": "counterfactual" if variant_id else "",
        "model_variant_counterfactual": "True" if variant_id else "False",
        "promotion_state": "shadow" if variant_id else "baseline",
        "event_gate_status": "PASS",
        "event_gate_action": "QUOTE",
        "event_gate_reason_code": "NO_RESTRICTED_EVENT",
        "event_gate_next_event_at_utc": f"{target_date}T19:00:00+00:00",
        "early_hour_guardrail_status": "PASS",
        "early_hour_guardrail_min_edge": "0.02",
        "early_hour_guardrail_size_multiplier": "1.0",
        "early_hour_guardrail_quote_widen_buffer": "0.0",
        "market_aware_overlay_probability": "0.35",
        "market_aware_overlay_edge": "0.03",
        "market_aware_overlay_used_for_risk_only": "True",
        "schema_version": "mm_run_v0.2",
        "model_variant_runtime_identity": json.dumps({
            "release": "bound",
            "payload": "x" * 16_384,
        }),
        "worker_release_commit": "a" * 40,
        "worker_release_manifest_hash": "b" * 64,
        "source_snapshot_id": "snapshot-current",
    })
    return row


def _write_current_run(
    runs_root: Path,
    run_id: str = "paper-run",
    *,
    target_date: str = "2026-07-18",
) -> Path:
    run_folder = runs_root / target_date / run_id
    columns = [*SCORING_COLUMNS, *PROVENANCE_COLUMNS]
    _write_csv(
        run_folder / BASE_CANONICAL_FILENAME,
        columns,
        [_current_row(run_id=run_id, target_date=target_date)],
    )
    _write_csv(
        run_folder / MODEL_VARIANT_CANONICAL_FILENAME,
        columns,
        [
            _current_row(
                run_id=run_id,
                variant_id="candidate-shadow",
                target_date=target_date,
            )
        ],
    )
    return run_folder


def test_backfill_cli_is_idempotent_and_writes_compact_current_schema_pair(
    tmp_path,
    capsys,
):
    runs_root = tmp_path / "mm_runs"
    run_folder = _write_current_run(runs_root)
    canonical_paths = (
        run_folder / BASE_CANONICAL_FILENAME,
        run_folder / MODEL_VARIANT_CANONICAL_FILENAME,
    )
    canonical_before = {path: path.read_bytes() for path in canonical_paths}

    assert main(["backfill", "--runs-root", str(runs_root)]) == 0
    first = json.loads(capsys.readouterr().out)

    assert first["schema_version"] == SCHEMA_VERSION
    assert first["written_run_count"] == 1
    assert first["skipped_run_count"] == 0
    assert first["error_run_count"] == 0
    assert first["runs"][0]["status"] == "WROTE"
    assert first["runs"][0]["input_mode"] == "projection"
    assert 0 < first["runs"][0]["projected_vs_canonical_byte_ratio"] < 1
    assert {path: path.read_bytes() for path in canonical_paths} == canonical_before

    projection_paths = (
        run_folder / BASE_PROJECTION_FILENAME,
        run_folder / MODEL_VARIANT_PROJECTION_FILENAME,
    )
    for path in projection_paths:
        assert _read_header(path) == list(SCORING_COLUMNS)
        assert "model_variant_runtime_identity" not in _read_header(path)
        assert "worker_release_manifest_hash" not in _read_header(path)

    published_before = {
        path: path.read_bytes()
        for path in (*projection_paths, run_folder / MANIFEST_FILENAME)
    }
    assert main(["backfill", "--runs-root", str(runs_root)]) == 0
    second = json.loads(capsys.readouterr().out)

    assert second["written_run_count"] == 0
    assert second["skipped_run_count"] == 1
    assert second["error_run_count"] == 0
    assert second["runs"][0]["status"] == "SKIPPED_VALID"
    assert {
        path: path.read_bytes()
        for path in (*projection_paths, run_folder / MANIFEST_FILENAME)
    } == published_before
    assert {path: path.read_bytes() for path in canonical_paths} == canonical_before


def test_invalid_projection_member_falls_back_to_both_canonical_tapes(tmp_path):
    run_folder = _write_current_run(tmp_path / "mm_runs")
    receipt = write_run_scoring_projections(run_folder)
    assert receipt["input_mode"] == "projection"

    variant_projection = run_folder / MODEL_VARIANT_PROJECTION_FILENAME
    variant_projection.write_text("wrong_header\nwrong_value\n", encoding="utf-8")
    resolved = resolve_run_scoring_inputs(run_folder)

    assert resolved["input_mode"] == "canonical_fallback"
    assert resolved["projection_valid"] is False
    assert resolved["projection_reason"] == "model_variant_projection_binding_mismatch"
    assert resolved["input_paths"] == {
        "base": str(run_folder / BASE_CANONICAL_FILENAME),
        "model_variant": str(run_folder / MODEL_VARIANT_CANONICAL_FILENAME),
    }
    assert resolved["input_bytes"] == resolved["canonical_bytes"]
    assert resolved["projected_vs_canonical_byte_ratio"] == 1.0


def test_live_append_prefix_scores_captured_rows_after_file_grows(tmp_path):
    run_folder = _write_current_run(
        tmp_path / "mm_runs",
        target_date="2099-08-20",
    )
    exact = resolve_run_scoring_inputs(run_folder)
    captured = resolve_run_scoring_inputs(
        run_folder,
        live_append_prefix=True,
    )
    quote_path = run_folder / BASE_CANONICAL_FILENAME
    appended = _current_row(run_id="paper-run", target_date="2099-08-20")
    appended["generated_at_utc"] = "2099-08-20T16:01:00+00:00"
    _append_csv_row(quote_path, appended)

    with pytest.raises(RuntimeError, match="size_bytes binding mismatch"):
        load_quote_rows(
            [run_folder],
            input_paths_by_folder={str(run_folder): quote_path},
            input_bindings_by_folder={
                str(run_folder): exact["input_bindings"]["base"]
            },
        )

    binding = captured["input_bindings"]["base"]
    assert binding["binding_mode"] == LIVE_APPEND_PREFIX_BINDING_MODE
    assert binding["captured_mtime_ns"] > 0
    assert binding["size_bytes"] < quote_path.stat().st_size
    rows, _configs = load_quote_rows(
        [run_folder],
        input_paths_by_folder={str(run_folder): quote_path},
        input_bindings_by_folder={str(run_folder): binding},
    )
    assert len(rows) == 1
    assert rows[0]["generated_at_utc"] == "2099-08-20T16:00:00+00:00"


def test_live_append_prefix_excludes_partial_final_record(tmp_path):
    run_folder = _write_current_run(
        tmp_path / "mm_runs",
        target_date="2099-08-20",
    )
    quote_path = run_folder / BASE_CANONICAL_FILENAME
    complete_size = quote_path.stat().st_size
    with quote_path.open("ab") as handle:
        handle.write(b"paper-run,unfinished")

    captured = resolve_run_scoring_inputs(
        run_folder,
        live_append_prefix=True,
    )
    binding = captured["input_bindings"]["base"]

    assert binding["size_bytes"] == complete_size
    assert binding["captured_file_size_bytes"] > binding["size_bytes"]
    rows, _configs = load_quote_rows(
        [run_folder],
        input_paths_by_folder={str(run_folder): quote_path},
        input_bindings_by_folder={str(run_folder): binding},
    )
    assert len(rows) == 1


def test_live_append_prefix_rejects_newline_inside_unfinished_quoted_record(
    tmp_path,
):
    run_folder = _write_current_run(
        tmp_path / "mm_runs",
        target_date="2099-08-20",
    )
    quote_path = run_folder / BASE_CANONICAL_FILENAME
    with quote_path.open("ab") as handle:
        handle.write(b'paper-run,"unfinished\n')

    captured = resolve_run_scoring_inputs(
        run_folder,
        live_append_prefix=True,
    )
    binding = captured["input_bindings"]["base"]

    with pytest.raises(csv.Error, match="unexpected end of data"):
        load_quote_rows(
            [run_folder],
            input_paths_by_folder={str(run_folder): quote_path},
            input_bindings_by_folder={str(run_folder): binding},
        )


def test_live_append_prefix_rejects_rewrite_inside_captured_bytes(tmp_path):
    run_folder = _write_current_run(
        tmp_path / "mm_runs",
        target_date="2099-08-20",
    )
    quote_path = run_folder / BASE_CANONICAL_FILENAME
    captured = resolve_run_scoring_inputs(
        run_folder,
        live_append_prefix=True,
    )
    binding = captured["input_bindings"]["base"]
    original = quote_path.read_bytes()
    rewritten = original.replace(b"atlanta", b"atlantb", 1)
    assert len(rewritten) == len(original)
    quote_path.write_bytes(rewritten)

    with pytest.raises(RuntimeError, match="prefix hash binding mismatch"):
        load_quote_rows(
            [run_folder],
            input_paths_by_folder={str(run_folder): quote_path},
            input_bindings_by_folder={str(run_folder): binding},
        )


@pytest.mark.parametrize(
    ("columns", "expected_reason"),
    [
        (
            list(SCORING_COLUMNS[:-1]),
            "base_canonical_columns_missing:market_aware_overlay_used_for_risk_only",
        ),
        (
            [*SCORING_COLUMNS, "min_order_size"],
            "base_canonical_compatibility_aliases:min_order_size",
        ),
    ],
)
def test_malformed_or_legacy_alias_source_fails_closed(
    tmp_path,
    columns,
    expected_reason,
):
    run_folder = tmp_path / "mm_runs" / "2026-07-18" / "bad-run"
    row = _current_row(run_id="bad-run")
    row["min_order_size"] = "1"
    _write_csv(run_folder / BASE_CANONICAL_FILENAME, columns, [row])

    with pytest.raises(ValueError) as exc_info:
        write_run_scoring_projections(run_folder)

    assert str(exc_info.value) == expected_reason
    resolved = resolve_run_scoring_inputs(run_folder)
    assert resolved["input_mode"] == "canonical_fallback"
    assert resolved["projection_reason"] == expected_reason
    assert resolved["input_paths"]["base"] == str(
        run_folder / BASE_CANONICAL_FILENAME
    )
    assert not (run_folder / MANIFEST_FILENAME).exists()
    assert not (run_folder / BASE_PROJECTION_FILENAME).exists()
