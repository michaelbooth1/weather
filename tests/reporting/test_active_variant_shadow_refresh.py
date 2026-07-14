import csv
import json
from pathlib import Path
from unittest.mock import patch

from weather.reporting.candidate_lifecycle.active_variant_shadow_refresh import (
    build_payload,
    execute_registry_prediction_exports,
    main,
)


def _write_rows(path: Path, variant_id: str, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "variant_id",
        "variant_family",
        "uses_market_features",
        "is_control",
        "market_id",
        "target_date",
        "snapshot_id",
        "band_key",
        "probability",
        "current_probability",
        "market_yes",
        "outcome",
        "captured_at_local",
        "cutoff_regime",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "variant_id": variant_id,
                "variant_family": "source_family",
                "uses_market_features": "False",
                "is_control": "False",
                "target_date": "2026-06-13",
                "current_probability": "0.50",
                "market_yes": "0.50",
                "outcome": "1",
                "captured_at_local": "2026-06-13T08:00:00-04:00",
                "cutoff_regime": "early",
                **row,
            })


def _variant(variant_id: str, export_path: Path, *, lifecycle="active", runtime="pooled_candidate_replay", recipe=None):
    row = {
        "variant_id": variant_id,
        "variant_family": "source_family" if recipe is None else "route_family",
        "lifecycle": lifecycle,
        "track": "no_market",
        "roles": ["candidate", "no-market"],
        "active_for_headline": True,
        "live_capture_enabled": True,
        "counts_toward_weather_model_promotion": False,
        "artifact_required": False,
        "prediction_function": "weather.tests:predict",
        "prediction_mode": "band_binary",
        "export_family": "source_family" if recipe is None else "route_family",
        "default_export_path": str(export_path),
        "live_runtime": runtime,
    }
    if recipe is not None:
        row["route_recipe_path"] = str(recipe)
    return row


def _registry(path: Path, variants: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "schema_version": "model_variant_registry_v0.1",
            "variants": variants,
        }),
        encoding="utf-8",
    )


def _fake_pooled_execute(variant, contract, **_kwargs):
    return {
        "variant_id": variant["variant_id"],
        "live_runtime": contract["live_runtime"],
        "prediction_function": contract["prediction_function"],
        "status": "OK",
        "output_path": contract["default_export_path"],
        "detail": "prewritten test export",
    }


def test_candidate_row_route_composite_runtime_emits_active_routed_rows(tmp_path):
    source_a = tmp_path / "source_a.csv"
    source_b = tmp_path / "source_b.csv"
    composite = tmp_path / "composite.csv"
    recipe = tmp_path / "recipe.json"
    registry = tmp_path / "config" / "model_variant_registry.json"
    corpus = tmp_path / "backtest" / "promotion_corpus.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_text("{}", encoding="utf-8")

    base_rows = [
        {"market_id": "nyc", "snapshot_id": "nyc-s1", "band_key": "eq:80", "probability": "0.61"},
        {"market_id": "seattle", "snapshot_id": "sea-s1", "band_key": "eq:82", "probability": "0.20"},
    ]
    alternate_rows = [
        {"market_id": "nyc", "snapshot_id": "nyc-s1", "band_key": "eq:80", "probability": "0.11"},
        {"market_id": "seattle", "snapshot_id": "sea-s1", "band_key": "eq:82", "probability": "0.82"},
    ]
    _write_rows(source_a, "source_a_v1", base_rows)
    _write_rows(source_b, "source_b_v1", alternate_rows)
    recipe.write_text(
        json.dumps({
            "schema_version": "candidate_row_route_composite_v0.1",
            "source_variant_ids": ["source_a_v1", "source_b_v1"],
            "routes": [
                {"match": {"market_id": "seattle"}, "source_variant_id": "source_b_v1"},
                {"match": {}, "source_variant_id": "source_a_v1"},
            ],
        }),
        encoding="utf-8",
    )
    _registry(
        registry,
        [
            _variant("source_a_v1", source_a),
            _variant("source_b_v1", source_b),
            _variant(
                "route_composite_v1",
                composite,
                runtime="candidate_row_route_composite",
                recipe=recipe,
            ),
        ],
    )

    with patch(
        "weather.reporting.candidate_lifecycle.active_variant_shadow_refresh._execute_pooled_candidate_replay_contract",
        side_effect=_fake_pooled_execute,
    ):
        execution = execute_registry_prediction_exports(registry_path=registry, corpus_path=corpus)
    payload = build_payload(execution["source_paths"], registry_path=registry, execution=execution)

    with composite.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_market = {row["market_id"]: row for row in rows}

    assert execution["status"] == "OK"
    assert payload["status"] in {"OK", "WARN"}
    assert payload["blockers"] == []
    assert payload["registry"]["missing_active_variant_ids"] == []
    assert by_market["nyc"]["probability"] == "0.61"
    assert by_market["nyc"]["route_source_variant_id"] == "source_a_v1"
    assert by_market["seattle"]["probability"] == "0.82"
    assert by_market["seattle"]["route_source_variant_id"] == "source_b_v1"
    canonical_route_rows = [
        row for row in payload["multi_variant_shadow"]["rows"]
        if row["variant_id"] == "route_composite_v1"
    ]
    assert {row["route_source_variant_id"] for row in canonical_route_rows} == {
        "source_a_v1",
        "source_b_v1",
    }


def test_candidate_row_route_composite_runtime_rejects_inactive_source(tmp_path):
    source_a = tmp_path / "source_a.csv"
    source_b = tmp_path / "source_b.csv"
    composite = tmp_path / "composite.csv"
    recipe = tmp_path / "recipe.json"
    registry = tmp_path / "config" / "model_variant_registry.json"
    corpus = tmp_path / "backtest" / "promotion_corpus.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_text("{}", encoding="utf-8")
    _write_rows(source_a, "source_a_v1", [
        {"market_id": "nyc", "snapshot_id": "nyc-s1", "band_key": "eq:80", "probability": "0.61"},
    ])
    _write_rows(source_b, "source_b_v1", [
        {"market_id": "nyc", "snapshot_id": "nyc-s1", "band_key": "eq:80", "probability": "0.11"},
    ])
    recipe.write_text(
        json.dumps({
            "schema_version": "candidate_row_route_composite_v0.1",
            "source_variant_ids": ["source_a_v1", "source_b_v1"],
            "routes": [{"match": {}, "source_variant_id": "source_b_v1"}],
        }),
        encoding="utf-8",
    )
    _registry(
        registry,
        [
            _variant("source_a_v1", source_a),
            _variant("source_b_v1", source_b, lifecycle="shadow"),
            _variant(
                "route_composite_v1",
                composite,
                runtime="candidate_row_route_composite",
                recipe=recipe,
            ),
        ],
    )

    with patch(
        "weather.reporting.candidate_lifecycle.active_variant_shadow_refresh._execute_pooled_candidate_replay_contract",
        side_effect=_fake_pooled_execute,
    ):
        execution = execute_registry_prediction_exports(registry_path=registry, corpus_path=corpus)

    assert execution["status"] == "ERROR"
    assert not composite.exists()
    assert any("source variant is not active/headline-countable" in blocker for blocker in execution["blockers"])


def test_active_timesplit_logistic_runtime_executes_registry_export(tmp_path):
    rows_out = tmp_path / "timesplit_rows.csv"
    registry = tmp_path / "config" / "model_variant_registry.json"
    corpus = tmp_path / "backtest" / "promotion_corpus.json"
    corpus.parent.mkdir(parents=True)
    corpus.write_text("{}", encoding="utf-8")
    variant = _variant(
        "item224_active_timesplit_logistic_repair_v0_1",
        rows_out,
        runtime="active_timesplit_logistic_repair",
    )
    variant["input_rows_path"] = str(tmp_path / "source_rows.csv")
    _registry(registry, [variant])

    def fake_build_payload(**kwargs):
        rows_out_path = Path(kwargs["rows_out"])
        _write_rows(rows_out_path, "item224_active_timesplit_logistic_repair_v0_1", [
            {"market_id": "nyc", "snapshot_id": "nyc-s1", "band_key": "eq:80", "probability": "0.61"},
        ])
        return {
            "eval_rows": 1,
            "aggregate": {"delta_vs_market": -0.01},
        }

    with patch(
        "weather.reporting.research.item224_active_timesplit_logistic_repair.build_payload",
        side_effect=fake_build_payload,
    ):
        execution = execute_registry_prediction_exports(registry_path=registry, corpus_path=corpus)

    assert execution["status"] == "OK"
    assert execution["source_paths"] == [str(rows_out)]
    assert execution["executions"][0]["live_runtime"] == "active_timesplit_logistic_repair"
    assert execution["executions"][0]["status"] == "OK"
    assert "delta_vs_market=-0.01" in execution["executions"][0]["detail"]


def _pinned_manifest_entry(slug: str, target_date: str) -> dict:
    return {
        "event_slug": slug,
        "market_id": slug.split("-in-")[1].rsplit("-on-", 1)[0],
        "target_date": target_date,
        "settlement_bucket": 25,
        "settlement_unit": "F",
        "settlement_source": "test",
        "quality_grade": "complete",
        "snapshot_ids": ["snap1"],
        "snapshot_count": 1,
        "row_count": 3,
        "replay_record_hashes": {"snap1": "rh"},
        "tape_row_hashes": {"snap1": "th"},
        "label_hash": "lh",
    }


def test_windowed_corpus_manifest_keeps_newest_dates_and_valid_hash(tmp_path):
    # The 2026-07-05 chain spent 11.2h replaying every registry variant over
    # the full 249-market-day corpus; the evidence window must cap that by
    # pinning only the newest N distinct dates while staying a VALID manifest
    # (load_manifest re-verifies corpus_hash).
    from weather.reporting.candidate_lifecycle.active_variant_shadow_refresh import (
        windowed_corpus_manifest,
    )
    from weather.reporting.promotion.promotion_corpus import (
        corpus_hash,
        load_manifest,
        write_manifest,
    )

    entries = [
        _pinned_manifest_entry(f"highest-temperature-in-nyc-on-june-{day}-2026", f"2026-06-{day:02d}")
        for day in range(1, 11)
    ]
    manifest = {
        "schema_version": "promotion_corpus_v0.1",
        "generated_at_utc": "2026-07-06T00:00:00+00:00",
        "as_of": "2026-07-06",
        "snapshots_root": str(tmp_path),
        "quality_grades": ["complete", "manual_override"],
        "admit_promotion_countable": True,
        "include_reconstructed": False,
        "allow_unsettled": False,
        "min_snapshots": 1,
        "market_filter": None,
        "entries": entries,
        "summary": {},
        "skipped": [],
        "corpus_hash": corpus_hash(entries),
    }
    source_path = tmp_path / "promotion_corpus.json"
    write_manifest(manifest, source_path)
    out_path = tmp_path / "window_corpus.json"

    info = windowed_corpus_manifest(source_path, out_path, window_dates=3)

    assert info["windowed"] is True
    assert info["path"] == str(out_path)
    assert info["market_day_count"] == 3
    assert info["window_date_min"] == "2026-06-08"
    assert info["window_date_max"] == "2026-06-10"
    # The windowed manifest must round-trip the pinned-corpus validator.
    reloaded = load_manifest(out_path)
    assert len(reloaded["entries"]) == 3
    assert reloaded["evidence_window"]["source_market_day_count"] == 10
    assert reloaded["evidence_window"]["source_corpus_hash"] == manifest["corpus_hash"]


def test_windowed_corpus_manifest_passthrough_when_window_covers_corpus(tmp_path):
    from weather.reporting.candidate_lifecycle.active_variant_shadow_refresh import (
        windowed_corpus_manifest,
    )
    from weather.reporting.promotion.promotion_corpus import corpus_hash, write_manifest

    entries = [
        _pinned_manifest_entry("highest-temperature-in-nyc-on-june-1-2026", "2026-06-01"),
        _pinned_manifest_entry("highest-temperature-in-nyc-on-june-2-2026", "2026-06-02"),
    ]
    manifest = {
        "schema_version": "promotion_corpus_v0.1",
        "entries": entries,
        "corpus_hash": corpus_hash(entries),
    }
    source_path = tmp_path / "promotion_corpus.json"
    write_manifest(manifest, source_path)
    out_path = tmp_path / "window_corpus.json"

    # Window wider than the corpus: use the original manifest untouched.
    info = windowed_corpus_manifest(source_path, out_path, window_dates=14)
    assert info["windowed"] is False
    assert info["path"] == str(source_path)
    assert not out_path.exists()

    # Window disabled: same passthrough.
    disabled = windowed_corpus_manifest(source_path, out_path, window_dates=0)
    assert disabled["windowed"] is False
    assert disabled["path"] == str(source_path)


def test_cli_execute_registry_contracts_writes_json_handoff(tmp_path):
    export = tmp_path / "backtest" / "fresh_active.csv"
    registry = tmp_path / "config" / "model_variant_registry.json"
    corpus = tmp_path / "backtest" / "promotion_corpus.json"
    json_out = tmp_path / "backtest" / "active_variant_shadow.json"
    registry.parent.mkdir(parents=True)
    corpus.parent.mkdir(parents=True)
    corpus.write_text("{}", encoding="utf-8")
    _registry(
        registry,
        [
            _variant(
                "active_v",
                export,
                runtime="pooled_candidate_replay",
            ),
        ],
    )

    def fake_execute(variant, contract, **_kwargs):
        _write_rows(export, variant["variant_id"], [
            {"market_id": "nyc", "snapshot_id": "nyc-s1", "band_key": "eq:80", "probability": "0.61"},
        ])
        return {
            "variant_id": variant["variant_id"],
            "live_runtime": contract["live_runtime"],
            "prediction_function": contract["prediction_function"],
            "status": "OK",
            "output_path": str(export),
        }

    with patch(
        "weather.reporting.candidate_lifecycle.active_variant_shadow_refresh._execute_pooled_candidate_replay_contract",
        side_effect=fake_execute,
    ):
        payload = main([
            "--execute-registry-contracts",
            "--variant-registry",
            str(registry),
            "--corpus-path",
            str(corpus),
            "--window-corpus-out",
            str(tmp_path / "backtest" / "active_variant_shadow_window_corpus.json"),
            "--long-out",
            str(tmp_path / "backtest" / "active_variant_shadow_long.csv"),
            "--attribution-sidecar-out",
            str(tmp_path / "backtest" / "active_variant_shadow_attribution.jsonl"),
            "--json-out",
            str(json_out),
            "--report-out",
            str(tmp_path / "backtest" / "active_variant_shadow_report.md"),
        ])

    saved = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["status"] in {"OK", "WARN"}
    assert payload["execution"]["status"] == "OK"
    assert payload["execution"]["source_paths"] == [str(export)]
    assert payload["evidence_window"]["path"] == str(corpus)
    assert saved["execution"]["source_paths"] == [str(export)]
    assert saved["evidence_window"]["path"] == str(corpus)
