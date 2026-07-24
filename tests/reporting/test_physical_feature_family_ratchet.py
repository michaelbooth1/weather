import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from weather.reporting.source_gates.physical_feature_family_ratchet import (
    build_ratchet,
    main,
    render_report,
    resolve_output_paths,
    write_outputs,
)
from weather.reporting.source_gates.source_artifact_binding import stable_json_artifact
from weather.reporting.source_gates.source_family_contracts import (
    EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS,
)
from tests.reporting.source_family_contract_fixtures import (
    operational_ablation_payload,
    operational_inventory,
)


def _family_row(
    family_id,
    *,
    lineage="PASS",
    parity="PASS",
    ablation_status="PRESENT",
    delta=0.02,
    active_count=1,
    active_status="ACTIVE_FEATURES",
    model_influence=True,
    live_only=False,
    policy="training_and_serving",
):
    variant = {
        "forecast_baseline": "all_forecasts",
        "open_meteo_expanded": "open_meteo",
        "mrms_precip": "mrms_precip",
        "marine_context": "marine_context",
    }.get(
        family_id,
        EXPECTED_SOURCE_FAMILY_ABLATION_VARIANTS[family_id][0],
    )
    return {
        "family_id": family_id,
        "label": family_id.replace("_", " ").title(),
        "owner": "test",
        "source_keys": [family_id],
        "lineage_artifacts": ["source_status_long.csv", "features_long.csv"],
        "lineage_status": lineage,
        "train_serve_parity_status": parity,
        "historical_archive_status": "test_archive",
        "live_only": live_only,
        "live_only_policy": policy,
        "model_influence": model_influence,
        "configured_model_influence": True,
        "active_model_usage_status": active_status,
        "active_model_feature_count": active_count,
        "active_model_feature_columns": [f"{family_id}_feature"] if active_count else [],
        "missing_required_parity_feature_columns": [],
        "feature_missingness": {"missing_rate": 0.0, "by_market": [], "by_cutoff_hour": []},
        "ablation": {
            "status": ablation_status,
            "variant": variant,
            "n": 24,
            "rows": 24,
            "days": 2,
            "delta": delta,
            "days_source_helped": 2,
            "days_source_hurt": 0,
            "settlement_scored": True,
            "evidence_source": "candidate_replay",
        },
    }


def _slice_rows(variant, delta=0.02):
    return [
        {
            "variant": variant,
            "slice": "market",
            "market_id": "atlanta",
            "n": 12,
            "days": 2,
            "base_brier": 0.2,
            "variant_brier": 0.22,
            "delta": delta,
        },
        {
            "variant": variant,
            "slice": "cutoff_regime",
            "cutoff_regime": "early",
            "n": 12,
            "days": 2,
            "base_brier": 0.2,
            "variant_brier": 0.22,
            "delta": delta,
        },
        {
            "variant": variant,
            "slice": "market_cutoff_regime",
            "market_id": "atlanta",
            "cutoff_regime": "early",
            "n": 12,
            "days": 2,
            "base_brier": 0.2,
            "variant_brier": 0.22,
            "delta": delta,
        },
        {
            "variant": variant,
            "slice": "settlement_distance",
            "settlement_distance": "exact",
            "n": 12,
            "days": 2,
            "base_brier": 0.2,
            "variant_brier": 0.22,
            "delta": delta,
        },
    ]


def _ablation_payload(variants, slice_effects):
    payload = operational_ablation_payload(variants)
    summary_by_variant = {
        row["variant"]: row for row in payload["variants"]
    }
    grouped = {}
    for row in slice_effects:
        grouped.setdefault((row["variant"], row["slice"]), []).append(row)
    normalized_slices = []
    for (variant, kind), rows in grouped.items():
        summary = summary_by_variant[variant]
        summary["base_brier"] = 0.2
        summary["variant_brier"] = 0.2 + float(summary["delta"])
        if kind == "market":
            markets = sorted(
                {
                    row["market_day"].split()[0]
                    for row in payload["day_effects"][variant]
                }
            )
            templates = [
                {
                    **rows[0],
                    "market_id": market_id,
                }
                for market_id in markets
            ]
        else:
            templates = rows
        base_n, extra_n = divmod(summary["n"], len(templates))
        for index, template in enumerate(templates):
            normalized_slices.append(
                {
                    **template,
                    "n": base_n + (index < extra_n),
                    "base_brier": summary["base_brier"],
                    "variant_brier": summary["variant_brier"],
                    "delta": summary["delta"],
                }
            )
    payload["slice_effects"] = normalized_slices
    payload["summary"]["slice_effect_count"] = len(normalized_slices)
    return payload


def _write_bound_inputs(inventory_path, ablation_path, inventory_payload, ablation_payload):
    ablation_path.write_text(json.dumps(ablation_payload), encoding="utf-8")
    _, ablation_receipt = stable_json_artifact(ablation_path)
    inventory_payload["ablation_input_receipt"] = ablation_receipt
    by_variant = {
        row["variant"]: row for row in ablation_payload.get("variants") or []
    }
    for inventory_row in inventory_payload.get("inventory") or []:
        if (
            (inventory_row.get("promotion_decision") or {}).get("status")
            != "PROMOTION_CANDIDATE"
        ):
            continue
        ablation = inventory_row.get("ablation") or {}
        source = by_variant.get(ablation.get("variant"))
        if source is None:
            continue
        ablation.update(
            {
                "status": "PRESENT",
                "settlement_scored": True,
                "rows": source.get("n", source.get("rows")),
                "days": source.get("market_days", source.get("days")),
                "delta": source.get("delta"),
                "base_brier": source.get("base_brier"),
                "variant_brier": source.get("variant_brier"),
                "days_source_helped": source.get(
                    "market_days_source_helped",
                    source.get("days_source_helped"),
                ),
                "days_source_hurt": source.get(
                    "market_days_source_hurt",
                    source.get("days_source_hurt"),
                ),
                "evidence_source": "source_family_ablation",
                "evidence_contract": inventory_payload[
                    "ablation_evidence_contract"
                ],
            }
        )
    inventory_path.write_text(json.dumps(inventory_payload), encoding="utf-8")


class TestPhysicalFeatureFamilyRatchet(unittest.TestCase):
    def test_builds_strict_family_statuses_and_excludes_clob_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            _write_bound_inputs(
                inventory,
                ablation,
                operational_inventory(
                    [
                            _family_row("forecast_baseline", delta=0.02),
                            _family_row("open_meteo_expanded", delta=0.02),
                            _family_row("nws_grid", lineage="PARTIAL_SOURCE_STATUS", parity="LINEAGE_BLOCKED", active_count=0),
                            _family_row(
                                "multi_model_guidance",
                                active_count=0,
                                active_status="NOT_USED_BY_ACTIVE_ARTIFACT",
                                live_only=True,
                                policy="live_only_diagnostic_until_backfilled",
                                delta=0.0,
                            ),
                            _family_row(
                                "mrms_precip",
                                active_count=0,
                                active_status="USAGE_ACTIVE_ARTIFACT_EMPTY",
                                delta=0.0,
                            ),
                            _family_row("marine_context", ablation_status="MISSING", delta=None),
                            _family_row("reanalysis_synoptic", delta=-0.01),
                            _family_row("clob_microstructure", delta=0.0),
                    ]
                ),
                _ablation_payload(
                    [
                            {"variant": "all_forecasts", "delta": 0.02},
                            {"variant": "open_meteo", "delta": 0.02},
                    ],
                    _slice_rows("all_forecasts", 0.02),
                ),
            )

            payload = build_ratchet(
                source_family_inventory=inventory,
                source_family_ablation=ablation,
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            by_family = {row["family_id"]: row for row in payload["families"]}
            report = render_report(payload)
            read_only_data_root = root / "read-only-data"
            read_only_data_root.mkdir()
            json_out, report_out = write_outputs(
                payload,
                root / "ratchet.json",
                root / "ratchet.md",
                source_family_inventory=inventory,
                source_family_ablation=ablation,
                read_only_data_root=read_only_data_root,
            )
            json_exists = json_out.exists()
            report_exists = report_out.exists()

        self.assertEqual(payload["schema_version"], "physical_feature_family_ratchet_v0.2")
        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(by_family["forecast_baseline"]["status"], "PROMOTION_ELIGIBLE")
        self.assertEqual(by_family["open_meteo_expanded"]["status"], "ISOLATED_REPLAY_BLOCK")
        self.assertEqual(by_family["nws_grid"]["status"], "LINEAGE_BLOCKED")
        self.assertEqual(by_family["multi_model_guidance"]["status"], "LIVE_ONLY")
        self.assertEqual(by_family["mrms_precip"]["status"], "MISSING_ACTIVE_ARTIFACT")
        self.assertEqual(by_family["marine_context"]["status"], "ISOLATED_REPLAY_BLOCK")
        self.assertEqual(by_family["reanalysis_synoptic"]["status"], "ISOLATED_REPLAY_BLOCK")
        self.assertEqual(payload["excluded_market_overlay_families"][0]["family_id"], "clob_microstructure")
        self.assertIn("forecast_baseline", payload["rollup"]["ready_for_retraining"])
        self.assertIn("Settlement-Sliced Lift And Harm", report)
        self.assertTrue(json_exists)
        self.assertTrue(report_exists)

    def test_prefers_current_ablation_variant_summary_over_inventory_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            _write_bound_inputs(
                inventory,
                ablation,
                operational_inventory([_family_row("forecast_baseline", delta=-0.01)]),
                _ablation_payload(
                    [
                            {
                                "variant": "all_forecasts",
                                "n": 48,
                                "market_days": 4,
                                "delta": 0.03,
                                "market_days_source_helped": 4,
                                "market_days_source_hurt": 0,
                            }
                    ],
                    _slice_rows("all_forecasts", 0.02),
                ),
            )

            payload = build_ratchet(
                source_family_inventory=inventory,
                source_family_ablation=ablation,
                generated_at_utc="2026-06-23T00:00:00+00:00",
            )
            family = next(row for row in payload["families"] if row["family_id"] == "forecast_baseline")

        self.assertEqual(family["status"], "PROMOTION_ELIGIBLE")
        self.assertEqual(family["ablation"]["delta"], 0.03)
        self.assertEqual(family["ablation"]["evidence_source"], "source_family_ablation")

    def test_family_decision_uses_selected_ablation_variant_slices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            family = _family_row("forecast_baseline", delta=0.02)
            family["ablation"]["variant"] = "all_forecasts"
            _write_bound_inputs(
                inventory,
                ablation,
                operational_inventory([family]),
                _ablation_payload(
                    [
                            {
                                "variant": "all_forecasts",
                                "n": 48,
                                "market_days": 4,
                                "delta": 0.03,
                                "market_days_source_helped": 4,
                                "market_days_source_hurt": 0,
                            },
                            {
                                "variant": "open_meteo",
                                "n": 48,
                                "market_days": 4,
                                "delta": -0.02,
                                "market_days_source_helped": 0,
                                "market_days_source_hurt": 4,
                            },
                    ],
                    _slice_rows("all_forecasts", 0.02)
                    + _slice_rows("open_meteo", -0.02),
                ),
            )

            payload = build_ratchet(
                source_family_inventory=inventory,
                source_family_ablation=ablation,
                generated_at_utc="2026-06-24T00:00:00+00:00",
            )
            family = next(row for row in payload["families"] if row["family_id"] == "forecast_baseline")

        self.assertEqual(family["status"], "PROMOTION_ELIGIBLE")
        self.assertEqual(family["decision_ablation_variants"], ["all_forecasts"])
        self.assertEqual(family["settlement_slice_summary"]["harmful_slice_count"], 0)
        self.assertEqual(
            {
                row["variant"]
                for row in payload["settlement_sliced_lift"]
                if row["family_id"] == "forecast_baseline"
            },
            {"all_forecasts"},
        )

    def test_unreceipted_item27_market_details_are_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            family = _family_row("reanalysis_synoptic", delta=0.0)
            family["ablation"].update(
                {
                    "variant": "reanalysis_synoptic",
                    "evidence_source": "item27_feature_value_gate",
                    "market_details": [
                        {
                            "market_id": "atlanta",
                            "path": str(root / "mutable-unreceipted-item27.json"),
                            "rows": 30,
                            "full_brier": 0.27,
                            "ablated_brier": 0.33,
                            "delta_brier": 0.06,
                        }
                    ],
                }
            )
            _write_bound_inputs(
                inventory,
                ablation,
                operational_inventory([family]),
                _ablation_payload(
                    [{"variant": "all_forecasts", "delta": 0.01}],
                    [],
                ),
            )

            payload = build_ratchet(
                source_family_inventory=inventory,
                source_family_ablation=ablation,
                generated_at_utc="2026-06-24T00:00:00+00:00",
            )
            family = next(row for row in payload["families"] if row["family_id"] == "reanalysis_synoptic")

        self.assertEqual(family["status"], "ISOLATED_REPLAY_BLOCK")
        self.assertEqual(
            family["blockers"],
            [
                "item27 market_details evidence is diagnostic-only and unreceipted"
            ],
        )
        self.assertEqual(family["settlement_slice_summary"]["slice_count"], 0)
        self.assertEqual(family["settlement_slice_summary"]["required_slice_kinds_present"], [])
        self.assertEqual(
            family["settlement_slice_summary"]["missing_required_slice_kinds"],
            [
                "cutoff_regime",
                "market",
                "market_cutoff_regime",
                "settlement_distance",
            ],
        )
        self.assertEqual(
            family["ablation"]["unreceipted_market_details_policy"],
            "DIAGNOSTIC_ONLY_NOT_CONSUMED",
        )
        self.assertNotIn(
            "reanalysis_synoptic",
            payload["rollup"]["ready_for_retraining"],
        )

    def test_output_paths_reject_aliases_inputs_data_root_and_stale_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            read_only_data_root = root / "read-only-data"
            read_only_data_root.mkdir()
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            inventory.write_text("{}", encoding="utf-8")
            ablation.write_text("{}", encoding="utf-8")
            report = root / "ratchet.md"

            with self.subTest("companion alias"):
                with self.assertRaisesRegex(ValueError, "must not alias"):
                    resolve_output_paths(
                        json_out=report,
                        report_out=report,
                        source_family_inventory=inventory,
                        source_family_ablation=ablation,
                        read_only_data_root=read_only_data_root,
                    )

            with self.subTest("input alias"):
                with self.assertRaisesRegex(ValueError, "aliases the source-family inventory"):
                    resolve_output_paths(
                        json_out=inventory,
                        report_out=report,
                        source_family_inventory=inventory,
                        source_family_ablation=ablation,
                        read_only_data_root=read_only_data_root,
                    )

            with self.subTest("read-only data root"):
                with self.assertRaisesRegex(ValueError, "inside the read-only data root"):
                    resolve_output_paths(
                        json_out=read_only_data_root / "nested" / ".." / "ratchet.json",
                        report_out=report,
                        source_family_inventory=inventory,
                        source_family_ablation=ablation,
                        read_only_data_root=read_only_data_root,
                    )

            stale = root / "stale.json"
            stale.write_text("do not overwrite", encoding="utf-8")
            with self.subTest("stale output"):
                with self.assertRaisesRegex(ValueError, "already exists"):
                    resolve_output_paths(
                        json_out=stale,
                        report_out=report,
                        source_family_inventory=inventory,
                        source_family_ablation=ablation,
                        read_only_data_root=read_only_data_root,
                    )
            self.assertEqual(stale.read_text(encoding="utf-8"), "do not overwrite")

    def test_write_outputs_serializes_before_report_then_json_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            read_only_data_root = root / "read-only-data"
            read_only_data_root.mkdir()
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            inventory.write_text("{}", encoding="utf-8")
            ablation.write_text("{}", encoding="utf-8")
            calls = []
            payload = {"status": "BLOCK", "summary": {}, "contract": {}, "families": []}

            with (
                mock.patch(
                    "weather.reporting.source_gates.physical_feature_family_ratchet.render_report",
                    side_effect=lambda value: calls.append(("serialize_report", value))
                    or "report\n",
                ),
                mock.patch(
                    "weather.reporting.source_gates.physical_feature_family_ratchet.atomic_write_text_exclusive",
                    side_effect=lambda path, text: calls.append(
                        ("publish_report", Path(path), text)
                    ),
                ),
                mock.patch(
                    "weather.reporting.source_gates.physical_feature_family_ratchet.atomic_write_json_exclusive",
                    side_effect=lambda path, value: calls.append(
                        ("publish_json", Path(path), value)
                    ),
                ),
            ):
                write_outputs(
                    payload,
                    root / "outputs" / "ratchet.json",
                    root / "outputs" / "ratchet.md",
                    source_family_inventory=inventory,
                    source_family_ablation=ablation,
                    read_only_data_root=read_only_data_root,
                )

            self.assertEqual(
                [call[0] for call in calls],
                ["serialize_report", "publish_report", "publish_json"],
            )

            with (
                mock.patch(
                    "weather.reporting.source_gates.physical_feature_family_ratchet.render_report"
                ) as render,
                mock.patch(
                    "weather.reporting.source_gates.physical_feature_family_ratchet.atomic_write_text_exclusive"
                ) as write_report,
                mock.patch(
                    "weather.reporting.source_gates.physical_feature_family_ratchet.atomic_write_json_exclusive"
                ) as write_json,
            ):
                with self.assertRaises(ValueError):
                    write_outputs(
                        {"not_finite": float("nan")},
                        root / "invalid" / "ratchet.json",
                        root / "invalid" / "ratchet.md",
                        source_family_inventory=inventory,
                        source_family_ablation=ablation,
                        read_only_data_root=read_only_data_root,
                    )
                render.assert_not_called()
                write_report.assert_not_called()
                write_json.assert_not_called()

    def test_cli_forwards_read_only_root_and_inputs_to_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            read_only_data_root = root / "read-only-data"
            read_only_data_root.mkdir()
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            inventory.write_text("{}", encoding="utf-8")
            ablation.write_text("{}", encoding="utf-8")
            json_out = root / "ratchet.json"
            report_out = root / "ratchet.md"
            payload = {"status": "BLOCK"}

            with (
                mock.patch(
                    "weather.reporting.source_gates.physical_feature_family_ratchet.build_ratchet",
                    return_value=payload,
                ) as build,
                mock.patch(
                    "weather.reporting.source_gates.physical_feature_family_ratchet.write_outputs",
                    return_value=(json_out, report_out),
                ) as write,
            ):
                result = main(
                    [
                        "--source-family-inventory",
                        str(inventory),
                        "--source-family-ablation",
                        str(ablation),
                        "--read-only-data-root",
                        str(read_only_data_root),
                        "--json-out",
                        str(json_out),
                        "--report-out",
                        str(report_out),
                    ]
                )

            self.assertIs(result, payload)
            build.assert_called_once_with(
                source_family_inventory=inventory.resolve(),
                source_family_ablation=ablation.resolve(),
            )
            write.assert_called_once_with(
                payload,
                json_out.resolve(),
                report_out.resolve(),
                source_family_inventory=inventory.resolve(),
                source_family_ablation=ablation.resolve(),
                read_only_data_root=read_only_data_root.resolve(),
            )

    def test_research_only_source_ablation_cannot_be_promotion_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            _write_bound_inputs(
                inventory,
                ablation,
                operational_inventory([_family_row("forecast_baseline", delta=0.04)]),
                {
                    "schema_version": "source_family_ablation_v0.2",
                    "research_only": True,
                    "promotion_preflight_evidence_authorization": False,
                    "model_binding": {
                        "status": "RESEARCH_UNBOUND",
                        "serving_or_release_authorization": False,
                    },
                    "variants": [
                        {"variant": "all_forecasts", "n": 48, "days": 4, "delta": 0.04},
                    ],
                    "slice_effects": _slice_rows("all_forecasts", 0.04),
                },
            )

            payload = build_ratchet(
                source_family_inventory=inventory,
                source_family_ablation=ablation,
                generated_at_utc="2026-07-23T00:00:00+00:00",
            )
            family = next(row for row in payload["families"] if row["family_id"] == "forecast_baseline")

        self.assertEqual(payload["status"], "BLOCK")
        self.assertEqual(
            payload["inputs"]["ablation_evidence_contract"]["status"], "BLOCK"
        )
        self.assertEqual(family["status"], "ISOLATED_REPLAY_BLOCK")
        self.assertNotEqual(family["status"], "PROMOTION_ELIGIBLE")

    def test_inactive_diagnostic_family_does_not_block_on_lineage_or_parity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory = root / "source_family_inventory.json"
            ablation = root / "source_family_ablation.json"
            _write_bound_inputs(
                inventory,
                ablation,
                operational_inventory(
                    [
                            _family_row(
                                "nws_grid",
                                lineage="PARTIAL_SOURCE_STATUS",
                                parity="LINEAGE_BLOCKED",
                                active_count=0,
                                active_status="NOT_USED_BY_ACTIVE_ARTIFACT",
                                model_influence=False,
                                policy="live_only_diagnostic_until_backfilled",
                            ),
                    ]
                ),
                _ablation_payload(
                    [{"variant": "all_forecasts", "delta": 0.01}],
                    [],
                ),
            )

            payload = build_ratchet(
                source_family_inventory=inventory,
                source_family_ablation=ablation,
                generated_at_utc="2026-06-24T00:00:00+00:00",
            )
            family = next(row for row in payload["families"] if row["family_id"] == "nws_grid")

        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(family["status"], "LIVE_ONLY")
        self.assertEqual(family["rollup_bucket"], "diagnostic_only")
        self.assertIn("nws_grid", payload["rollup"]["diagnostic_only"])
        self.assertEqual(family["model_influence"], False)
        self.assertEqual(family["blockers"], ["active_model_usage_status=NOT_USED_BY_ACTIVE_ARTIFACT"])


if __name__ == "__main__":
    unittest.main()
