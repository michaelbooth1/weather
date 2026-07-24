import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.market.mm_policy import (
    QUOTE_COLUMNS,
    apply_known_edge_permission,
    config_with_clob_recon,
    decide_quote,
    hourly_trust_state,
    known_edge_record_key,
    load_known_edge_map,
    load_promotion_states,
    resolve_known_edge_record,
    run_policy_snapshot,
)


NOW = "2026-06-14T16:00:00+00:00"


def fresh_row(**overrides):
    row = {
        "market_id": "atlanta",
        "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
        "snapshot_id": "s1",
        "captured_at_utc": "2026-06-14T15:59:30+00:00",
        "model_version": "candidate",
        "promotion_state": "SHADOW",
        "range_label": "80-81 F",
        "bin_kind": "eq",
        "bin_value": "80",
        "bin_value_hi": "81",
        "clob_token_id": "token-1",
        "condition_id": "condition-1",
        "fair_probability": 0.51,
        "market_mid": 0.50,
        "market_yes": 0.50,
        "clob_spread": 0.02,
        "clob_best_bid": 0.49,
        "clob_best_ask": 0.51,
        "clob_depth_1pct_total": 100.0,
        "clob_book_age_seconds": 20.0,
        "watcher_age_seconds": 10.0,
        "source_fresh": True,
        "heartbeat_ok": True,
        "market_status": "active",
    }
    row.update(overrides)
    return row


def write_known_edge_map(path, records):
    path.write_text(json.dumps({
        "schema_version": "mm_known_edge_map_v0.2",
        "serving_or_release_authorization": False,
        "records": records,
        "summary": {"record_count": len(records)},
    }), encoding="utf-8")
    return path


def manual_event_calendar(action="suppress"):
    return {
        "manual_events": [
            {
                "event_id": "platform-maintenance-1",
                "market_id": "atlanta",
                "event_class": "platform_maintenance",
                "label": "platform maintenance",
                "starts_at_utc": "2026-06-14T15:59:00+00:00",
                "ends_at_utc": "2026-06-14T16:01:00+00:00",
                "action": action,
                "reason_code": "INFO_EVENT_PLATFORM_MAINTENANCE",
            }
        ],
    }


class TestMmPolicy(unittest.TestCase):
    def test_load_promotion_states_prefers_allowlist_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion.json"
            path.write_text(json.dumps({
                "decisions": {
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "action": "PROMOTE_CANDIDATE",
                            "verdict": "PASS",
                        }
                    ]
                },
                "promotion_allowlist": {
                    "schema_version": "promotion_allowlist_v0.1",
                    "path": "allowlist.json",
                    "candidate_id": "candidate_v1",
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "candidate_id": "candidate_v1",
                            "action": "BLOCK_CANDIDATE",
                            "verdict": "BLOCK",
                            "candidate_serving_allowed": False,
                            "candidate_permission_allowed": False,
                            "blocker_reason": "candidate trails market",
                        }
                    ],
                },
            }), encoding="utf-8")

            states, diag = load_promotion_states(path)

        self.assertEqual(states["atlanta"]["promotion_state"], "BLOCK")
        self.assertFalse(states["atlanta"]["candidate_permission_allowed"])
        self.assertTrue(states["atlanta"]["promotion_allowlist_enforced"])
        self.assertTrue(diag["promotion_allowlist_enforced"])
        self.assertEqual(diag["promotion_allowlist_schema_version"], "promotion_allowlist_v0.1")

    def test_load_promotion_states_shadows_denied_promote_allowlist_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion.json"
            path.write_text(json.dumps({
                "promotion_allowlist": {
                    "schema_version": "promotion_allowlist_v0.1",
                    "markets": [
                        {
                            "market_id": "austin",
                            "action": "PROMOTE_CANDIDATE",
                            "verdict": "PASS",
                            "candidate_serving_allowed": False,
                            "candidate_permission_allowed": False,
                            "blocker_reason": "candidate cutover is not allowed",
                        }
                    ],
                },
            }), encoding="utf-8")

            states, diag = load_promotion_states(path)

        self.assertEqual(states["austin"]["promotion_state"], "SHADOW")
        self.assertFalse(states["austin"]["candidate_permission_allowed"])
        self.assertTrue(diag["promotion_allowlist_enforced"])

    def test_runtime_denies_forged_permission_without_ready_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion.json"
            path.write_text(
                json.dumps(
                    {
                        "readiness": {"status": "OPEN"},
                        "promotion_allowlist": {
                            "schema_version": "promotion_allowlist_v0.1",
                            "readiness_status": "READY",
                            "readiness_permission_allowed": True,
                            "candidate_permission_allowed": True,
                            "markets": [
                                {
                                    "market_id": "austin",
                                    "action": "PROMOTE_CANDIDATE",
                                    "verdict": "PASS",
                                    "effective_promotion_state": "PASS",
                                    "readiness_status": "READY",
                                    "readiness_permission_allowed": True,
                                    "candidate_serving_allowed": True,
                                    "candidate_permission_allowed": True,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            states, diag = load_promotion_states(path)

        self.assertEqual(states["austin"]["promotion_state"], "SHADOW")
        self.assertFalse(states["austin"]["candidate_permission_allowed"])
        self.assertFalse(states["austin"]["candidate_serving_allowed"])
        self.assertFalse(states["austin"]["readiness_bound"])
        self.assertFalse(diag["readiness_bound"])

    def test_runtime_v01_allowlist_remains_non_authorizing_even_when_ready_claims_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion.json"
            path.write_text(
                json.dumps(
                    {
                        "readiness": {"status": "READY"},
                        "promotion_allowlist": {
                            "schema_version": "promotion_allowlist_v0.1",
                            "readiness_status": "READY",
                            "readiness_permission_allowed": True,
                            "candidate_permission_allowed": True,
                            "markets": [
                                {
                                    "market_id": "austin",
                                    "action": "PROMOTE_CANDIDATE",
                                    "verdict": "PASS",
                                    "effective_promotion_state": "PASS",
                                    "readiness_status": "READY",
                                    "readiness_permission_allowed": True,
                                    "candidate_serving_allowed": True,
                                    "candidate_permission_allowed": True,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            states, diag = load_promotion_states(path)

        self.assertEqual(states["austin"]["promotion_state"], "SHADOW")
        self.assertFalse(states["austin"]["candidate_permission_allowed"])
        self.assertFalse(states["austin"]["candidate_serving_allowed"])
        self.assertFalse(states["austin"]["readiness_bound"])
        self.assertFalse(diag["readiness_bound"])
        self.assertTrue(diag["readiness_claims_match"])
        self.assertFalse(diag["authorization_schema_supported"])
        self.assertEqual(diag["authorization_status"], "NON_AUTHORIZING_SCHEMA")

    def test_runtime_does_not_trust_case_variant_effective_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion.json"
            path.write_text(
                json.dumps(
                    {
                        "readiness": {"status": "OPEN"},
                        "promotion_allowlist": {
                            "schema_version": "promotion_allowlist_v0.1",
                            "markets": [
                                {
                                    "market_id": "austin",
                                    "action": "PROMOTE_CANDIDATE",
                                    "verdict": "PASS",
                                    "effective_promotion_state": "pass",
                                    "candidate_serving_allowed": True,
                                    "candidate_permission_allowed": True,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            states, _diag = load_promotion_states(path)

        self.assertEqual(states["austin"]["promotion_state"], "SHADOW")
        self.assertFalse(states["austin"]["candidate_permission_allowed"])

    def test_runtime_treats_contradictory_block_verdict_as_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion.json"
            path.write_text(
                json.dumps(
                    {
                        "decisions": {
                            "markets": [
                                {
                                    "market_id": "austin",
                                    "action": "PROMOTE_CANDIDATE",
                                    "verdict": "BLOCK",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            states, _diag = load_promotion_states(path)

        self.assertEqual(states["austin"]["promotion_state"], "BLOCK")
        self.assertFalse(states["austin"]["candidate_permission_allowed"])

    def test_runtime_blocks_duplicate_market_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion.json"
            path.write_text(
                json.dumps(
                    {
                        "decisions": {
                            "markets": [
                                {
                                    "market_id": "austin",
                                    "action": "BLOCK_CANDIDATE",
                                    "verdict": "BLOCK",
                                },
                                {
                                    "market_id": "austin",
                                    "action": "PROMOTE_CANDIDATE",
                                    "verdict": "PASS",
                                },
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            states, diag = load_promotion_states(path)

        self.assertEqual(states["austin"]["promotion_state"], "BLOCK")
        self.assertEqual(diag["duplicate_market_ids"], ["austin"])

    def test_runtime_rejects_duplicate_json_object_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "promotion.json"
            path.write_text(
                '{"readiness":{"status":"OPEN"},'
                '"readiness":{"status":"READY"}}',
                encoding="utf-8",
            )

            states, diag = load_promotion_states(path)

        self.assertEqual(states, {})
        self.assertEqual(diag["authorization_status"], "BLOCK_MALFORMED")
        self.assertIn("duplicate JSON object key", diag["blockers"][0])

    def test_strict_policy_loaders_reject_all_nested_non_finite_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for token in ("NaN", "Infinity", "1e999"):
                with self.subTest(loader="promotion", token=token):
                    path = root / "promotion.json"
                    path.write_text(
                        (
                            '{"decisions":{"markets":[{"market_id":"austin",'
                            '"nested":{"value":TOKEN}}]}}'
                        ).replace("TOKEN", token),
                        encoding="utf-8",
                    )
                    states, diag = load_promotion_states(path)
                    self.assertEqual(states, {})
                    self.assertEqual(
                        diag["authorization_status"], "BLOCK_MALFORMED"
                    )
                    self.assertIn("non-finite JSON", diag["blockers"][0])

                with self.subTest(loader="known_edge", token=token):
                    path = root / "known-edge.json"
                    path.write_text(
                        (
                            '{"schema_version":"mm_known_edge_map_v0.2",'
                            '"records":[{"nested":[{"value":TOKEN}]}]}'
                        ).replace("TOKEN", token),
                        encoding="utf-8",
                    )
                    records, diag = load_known_edge_map(path)
                    self.assertEqual(records, [])
                    self.assertEqual(diag["status"], "BLOCK")
                    self.assertIn("non-finite JSON", diag["blockers"][0])

    def test_known_edge_loader_suppresses_detached_edge_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "known_edge.json"
            write_known_edge_map(
                path,
                [
                    {
                        "market_id": "austin",
                        "cutoff": "*",
                        "hour_utc": "*",
                        "band_distance_bucket": "*",
                        "band_type": "*",
                        "casebook_taxonomy": "*",
                        "regime": "*",
                        "source_fresh": "*",
                        "source_freshness_state": "*",
                        "book_imbalance_bucket": "*",
                        "permission": "edge_allowed",
                    }
                ],
            )

            records, diag = load_known_edge_map(path)

        self.assertEqual(records[0]["permission"], "edge_research")
        self.assertEqual(diag["sanitized_edge_allowed_count"], 1)
        self.assertFalse(diag["edge_allowed_authorization_supported"])

    def test_blocked_promotion_fails_closed(self):
        quote = decide_quote(fresh_row(promotion_state="BLOCK"), now=NOW)

        self.assertFalse(quote["quote_permission"])
        self.assertFalse(quote["live_trade_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_BLOCKED_PROMOTION")

    def test_shadow_harvest_quotes_when_fresh_and_small_edge(self):
        quote = decide_quote(fresh_row(), now=NOW)

        self.assertTrue(quote["quote_permission"])
        self.assertFalse(quote["live_trade_permission"])
        self.assertEqual(quote["regime"], "harvest")
        self.assertEqual(quote["reason_code"], "QUOTE_HARVEST_MID")
        self.assertLess(quote["bid_price"], quote["ask_price"])
        self.assertIn(quote["event_gate_status"], {"CLEAR", "WIDEN"})

    def test_high_spread_wide_book_requires_depth_and_spread_bounds(self):
        wide_but_allowed = decide_quote(
            fresh_row(
                fair_probability=0.505,
                market_mid=0.50,
                clob_best_bid=0.4605,
                clob_best_ask=0.5395,
                clob_spread=0.079,
                clob_depth_1pct_total=100.0,
            ),
            now=NOW,
        )
        too_wide = decide_quote(
            fresh_row(
                fair_probability=0.505,
                market_mid=0.50,
                clob_best_bid=0.4595,
                clob_best_ask=0.5405,
                clob_spread=0.081,
                clob_depth_1pct_total=100.0,
            ),
            now=NOW,
        )
        too_thin = decide_quote(
            fresh_row(
                fair_probability=0.505,
                market_mid=0.50,
                clob_best_bid=0.4605,
                clob_best_ask=0.5395,
                clob_spread=0.079,
                clob_depth_1pct_total=0.5,
            ),
            now=NOW,
        )

        self.assertTrue(wide_but_allowed["quote_permission"])
        self.assertEqual(wide_but_allowed["reason_code"], "QUOTE_HARVEST_MID")
        self.assertEqual(wide_but_allowed["regime"], "harvest")
        self.assertEqual(wide_but_allowed["book_spread"], 0.079)
        self.assertFalse(too_wide["quote_permission"])
        self.assertEqual(too_wide["reason_code"], "NO_QUOTE_WIDE_SPREAD")
        self.assertFalse(too_thin["quote_permission"])
        self.assertEqual(too_thin["reason_code"], "NO_QUOTE_THIN_DEPTH")

    def test_default_model_freshness_covers_snapshot_loop_sla(self):
        quote = decide_quote(fresh_row(captured_at_utc="2026-06-14T15:46:00+00:00"), now=NOW)
        stale = decide_quote(fresh_row(captured_at_utc="2026-06-14T15:44:30+00:00"), now=NOW)

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "QUOTE_HARVEST_MID")
        self.assertFalse(stale["quote_permission"])
        self.assertEqual(stale["reason_code"], "NO_QUOTE_STALE_MODEL")

    def test_information_event_gate_suppresses_quote(self):
        quote = decide_quote(
            fresh_row(),
            config={"_information_event_calendar_config": manual_event_calendar()},
            now=NOW,
        )

        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_INFORMATION_EVENT")
        self.assertEqual(quote["event_gate_status"], "PULL")
        self.assertEqual(quote["event_gate_action"], "suppress")
        self.assertEqual(quote["event_gate_event_class"], "platform_maintenance")
        self.assertEqual(quote["event_gate_reason_code"], "INFO_EVENT_PLATFORM_MAINTENANCE")

    def test_information_event_exception_requires_evidence_and_caps_size(self):
        quote = decide_quote(
            fresh_row(),
            config={
                "_information_event_calendar_config": manual_event_calendar(),
                "event_gate_exception_enabled": True,
                "event_gate_exception_event_classes": "platform_maintenance",
                "event_gate_exception_evidence_status": "PAPER_PASS",
                "event_gate_exception_evidence_id": "paper-slice-1",
                "event_gate_exception_risk_cap_usdc": 1.0,
            },
            now=NOW,
        )

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["event_gate_status"], "EXCEPTION")
        self.assertEqual(quote["event_gate_action"], "allow_exception")
        self.assertEqual(quote["event_gate_exception_id"], "paper-slice-1")
        self.assertEqual(quote["final_size_limiter"], "event_gate_exception_risk_cap")
        self.assertLess(float(quote["bid_size"]), 2.0)

    def test_correlated_regime_cap_limits_quote_size(self):
        quote = decide_quote(
            fresh_row(
                range_label="84-85 F",
                bin_value="84",
                bin_value_hi="85",
                settlement_current_high="80",
                correlated_regime_notional_before_usdc="4.5",
                correlated_regime_joint_stress_loss_before_usdc="4.5",
            ),
            config={"max_correlated_regime_joint_loss_usdc": 5.0},
            now=NOW,
        )

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["correlated_regime_group_key"], "2026-06-14|southeast|warm")
        self.assertEqual(quote["final_size_limiter"], "correlated_regime_joint_loss_cap")
        self.assertLess(float(quote["bid_size"]), 1.0)

    def test_clob_recon_policy_overrides_apply_when_artifact_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clob_recon.json"
            path.write_text(json.dumps({
                "schema_version": "clob_book_recon_v0.1",
                "policy_parameter_suggestions": {
                    "quote_size": 2.0,
                    "harvest_half_spread": 0.02,
                    "min_depth_1pct_total": 4.0,
                    "reward_competitor_q": 50.0,
                },
                "summary": {"slice_rows": 3},
            }), encoding="utf-8")

            config, diag = config_with_clob_recon({
                "clob_recon_policy_enabled": True,
                "clob_recon_path": str(path),
                "quote_size": 5.0,
            })

        self.assertTrue(diag["exists"])
        self.assertEqual(config["quote_size"], 2.0)
        self.assertEqual(config["harvest_half_spread"], 0.02)
        self.assertNotIn("reward_competitor_q", config)

    def test_shadow_large_disagreement_stands_down(self):
        quote = decide_quote(fresh_row(fair_probability=0.70, market_mid=0.50), now=NOW)

        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_DISAGREEMENT_SHADOW")

    def test_snapshot_cadence_gap_blocks_high_confidence_edge_quote(self):
        quote = decide_quote(
            fresh_row(
                promotion_state="PASS",
                known_edge_allowed=True,
                known_edge_permission="edge_allowed",
                known_edge_reason="live_forward_paper_gate_clear",
                fair_probability=0.78,
                market_mid=0.50,
                clob_best_bid=0.49,
                clob_best_ask=0.51,
                snapshot_cadence="scheduled",
                snapshot_cadence_gap_count=1,
                snapshot_cadence_max_gap_seconds=1328.4,
            ),
            now=NOW,
        )

        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_SNAPSHOT_CADENCE_DEGRADED")
        self.assertEqual(quote["snapshot_cadence_quality_state"], "gappy")
        self.assertEqual(quote["snapshot_cadence_permission"], "deny")
        self.assertLess(float(quote["snapshot_cadence_confidence_multiplier"]), 1.0)
        self.assertLess(float(quote["cadence_adjusted_fair_probability"]), float(quote["fair_probability"]))

    def test_late_untrusted_current_high_blocks_aggressive_mm_edge_for_june_21_markets(self):
        cases = {
            "toronto": (84.0, 86.0),
            "atlanta": (84.02, 86.0),
            "denver": (83.84, 87.0),
            "houston": (86.0, 89.0),
            "san-francisco": (64.94, 70.0),
        }
        for market_id, (raw_high, settlement_high) in cases.items():
            with self.subTest(market_id=market_id):
                quote = decide_quote(
                    fresh_row(
                        market_id=market_id,
                        event_slug=f"highest-temperature-in-{market_id}-on-june-21-2026",
                        captured_at_utc="2026-06-21T20:00:00+00:00",
                        capture_hour_local="16",
                        promotion_state="PASS",
                        known_edge_allowed=True,
                        known_edge_permission="edge_allowed",
                        known_edge_reason="live_forward_paper_gate_clear",
                        fair_probability=0.78,
                        market_mid=0.50,
                        clob_best_bid=0.49,
                        clob_best_ask=0.56,
                        raw_current_high=raw_high,
                        raw_current_high_bucket=round(raw_high),
                        settlement_current_high=settlement_high,
                        current_high_trusted=False,
                        current_high_guard_reason="settlement_adjusted_high_diverged_from_raw_current_high",
                        current_max_state="current_max_history_gap",
                    ),
                    config={"information_event_calendar_enabled": False},
                    now="2026-06-21T20:01:00+00:00",
                )

                self.assertFalse(quote["quote_permission"])
                self.assertEqual(quote["reason_code"], "NO_QUOTE_CURRENT_HIGH_TRUST_GATE")
                self.assertEqual(quote["current_high_trust_gate_status"], "blocked")
                self.assertEqual(quote["current_high_trust_gate_action"], "deny_aggressive_edge")
                self.assertTrue(quote["current_high_trust_gate_aggressive"])
                self.assertIn("untrusted_current_high", quote["reason_detail"])

    def test_late_untrusted_current_high_caps_and_widens_mm_harvest(self):
        quote = decide_quote(
            fresh_row(
                captured_at_utc="2026-06-21T20:00:00+00:00",
                capture_hour_local="16",
                current_high_trusted=False,
                current_high_guard_reason="missing_wu_history_validation",
                current_max_state="missing_wu_history_high",
            ),
            config={"information_event_calendar_enabled": False},
            now="2026-06-21T20:01:00+00:00",
        )

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["regime"], "harvest")
        self.assertEqual(quote["current_high_trust_gate_status"], "capped")
        self.assertEqual(quote["current_high_trust_gate_action"], "cap_and_widen")
        self.assertAlmostEqual(float(quote["bid_size"]), 2.5)
        self.assertAlmostEqual(float(quote["ask_size"]), 2.5)
        self.assertAlmostEqual(float(quote["bid_price"]), 0.48)
        self.assertAlmostEqual(float(quote["ask_price"]), 0.52)

    def test_hourly_trust_bands_are_market_local(self):
        self.assertEqual(
            hourly_trust_state(fresh_row(captured_at_utc="2026-06-14T12:30:00+00:00"))["hourly_trust_band"],
            "early_00_08",
        )
        self.assertEqual(
            hourly_trust_state(fresh_row(captured_at_utc="2026-06-14T13:00:00+00:00"))["hourly_trust_band"],
            "midday_09_14",
        )
        self.assertEqual(
            hourly_trust_state(fresh_row(captured_at_utc="2026-06-14T19:00:00+00:00"))["hourly_trust_band"],
            "late_15_19",
        )
        self.assertEqual(
            hourly_trust_state(fresh_row(captured_at_utc="2026-06-15T01:00:00+00:00"))["hourly_trust_band"],
            "closing_20_23",
        )

    def test_early_hour_guardrail_caps_size_widens_quotes_and_preserves_fair(self):
        quote = decide_quote(
            fresh_row(
                generated_at_utc="2026-06-14T09:01:00+00:00",
                captured_at_utc="2026-06-14T09:00:30+00:00",
            ),
            config={"information_event_calendar_enabled": False},
            now="2026-06-14T09:01:00+00:00",
        )

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["hourly_trust_band"], "early_00_08")
        self.assertEqual(quote["early_hour_guardrail_status"], "active")
        self.assertAlmostEqual(float(quote["bid_size"]), 1.75)
        self.assertAlmostEqual(float(quote["ask_size"]), 1.75)
        self.assertAlmostEqual(float(quote["bid_price"]), 0.48)
        self.assertAlmostEqual(float(quote["ask_price"]), 0.52)
        self.assertAlmostEqual(float(quote["fair_probability"]), 0.51)
        self.assertAlmostEqual(float(quote["market_aware_overlay_probability"]), 0.5065)
        self.assertTrue(quote["market_aware_overlay_used_for_risk_only"])
        self.assertEqual(quote["final_size_limiter"], "early_hour_market_guardrail")

    def test_early_hour_guardrail_requires_stronger_no_market_edge_for_edge_quotes(self):
        quote = decide_quote(
            fresh_row(
                generated_at_utc="2026-06-14T09:01:00+00:00",
                captured_at_utc="2026-06-14T09:00:30+00:00",
                promotion_state="PASS",
                known_edge_allowed=True,
                known_edge_permission="edge_allowed",
                known_edge_reason="live_forward_paper_gate_clear",
                fair_probability=0.55,
                market_mid=0.50,
                clob_best_bid=0.49,
                clob_best_ask=0.60,
            ),
            config={"information_event_calendar_enabled": False},
            now="2026-06-14T09:01:00+00:00",
        )

        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_EARLY_HOUR_GUARDRAIL_MIN_EDGE")
        self.assertEqual(quote["early_hour_guardrail_status"], "active")
        self.assertGreater(float(quote["early_hour_guardrail_min_edge"]), abs(float(quote["edge"])))

    def test_early_hour_guardrail_override_requires_edge_freshness_and_source_agreement(self):
        quote = decide_quote(
            fresh_row(
                generated_at_utc="2026-06-14T09:01:00+00:00",
                captured_at_utc="2026-06-14T09:00:30+00:00",
                promotion_state="PASS",
                known_edge_allowed=True,
                known_edge_permission="edge_allowed",
                known_edge_reason="live_forward_paper_gate_clear",
                source_freshness_state="all_fresh",
                forecast_source_count_bucket="normal_count",
                forecast_disagreement_bucket="low_disagreement",
                forecast_disagreement=0.5,
                fair_probability=0.62,
                market_mid=0.50,
                clob_best_bid=0.49,
                clob_best_ask=0.70,
            ),
            now="2026-06-14T09:01:00+00:00",
        )

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["regime"], "edge")
        self.assertEqual(quote["early_hour_guardrail_status"], "override_allowed")
        self.assertTrue(quote["early_hour_guardrail_override_allowed"])
        self.assertAlmostEqual(float(quote["bid_size"]), 5.0)

    def test_pass_known_edge_can_emit_model_skewed_quote(self):
        quote = decide_quote(
            fresh_row(
                promotion_state="PASS",
                known_edge_allowed=True,
                known_edge_permission="edge_allowed",
                known_edge_reason="live_forward_paper_gate_clear",
                known_edge_record_key="atlanta|*|*|*|*|*|*|*|*",
                known_edge_taxonomy="book_liquidity_artifact",
                fair_probability=0.60,
                market_mid=0.50,
                clob_best_bid=0.49,
                clob_best_ask=0.56,
            ),
            now=NOW,
        )

        self.assertTrue(quote["quote_permission"])
        self.assertEqual(quote["regime"], "edge")
        self.assertEqual(quote["side"], "YES_BID")
        self.assertEqual(quote["reason_code"], "QUOTE_EDGE_MODEL")

    def test_clob_overlay_market_informed_record_does_not_enable_edge_quote(self):
        row = fresh_row(
            promotion_state="PASS",
            casebook_taxonomy="market_lead",
            fair_probability=0.60,
            market_mid=0.50,
            clob_best_bid=0.49,
            clob_best_ask=0.56,
        )
        records = [
            {
                "market_id": "*",
                "cutoff": "*",
                "hour_utc": "*",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "market_lead",
                "regime": "*",
                "source_fresh": "*",
                "source_freshness_state": "*",
                "book_imbalance_bucket": "*",
                "base_permission": "CLOB_OVERLAY_MARKET_INFORMED",
                "permission": "edge_research",
                "reason": "clob_overlay_market_informed_replay_gate_clear",
            }
        ]

        record = resolve_known_edge_record(row, records)
        merged = apply_known_edge_permission(row, record=record, map_loaded=True)
        quote = decide_quote(merged, now=NOW)

        self.assertFalse(quote["known_edge_allowed"])
        self.assertEqual(quote["known_edge_taxonomy"], "market_lead")
        self.assertEqual(quote["known_edge_reason"], "clob_overlay_market_informed_replay_gate_clear")
        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["regime"], "none")
        self.assertEqual(quote["reason_code"], "NO_QUOTE_DISAGREEMENT_SHADOW")

    def test_known_edge_resolution_ignores_diagnostic_match_fields(self):
        row = fresh_row(
            known_edge_match_hour_utc="02",
        )
        records = [
            {
                "market_id": "atlanta",
                "cutoff": "*",
                "hour_utc": "02",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "*",
                "regime": "*",
                "source_fresh": "*",
                "source_freshness_state": "*",
                "book_imbalance_bucket": "*",
                "permission": "harvest_only",
                "reason": "diagnostic_field_should_not_match",
            },
            {
                "market_id": "atlanta",
                "cutoff": "*",
                "hour_utc": "15",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "*",
                "regime": "*",
                "source_fresh": "*",
                "source_freshness_state": "*",
                "book_imbalance_bucket": "*",
                "permission": "harvest_only",
                "reason": "actual_input_dimension",
            },
        ]

        record = resolve_known_edge_record(row, records)

        self.assertEqual(record["reason"], "actual_input_dimension")

    def test_known_edge_resolution_canonicalizes_record_hour_utc(self):
        row = fresh_row()
        records = [
            {
                "market_id": "atlanta",
                "cutoff": "*",
                "hour_utc": "16:00Z",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "*",
                "regime": "*",
                "source_fresh": "*",
                "source_freshness_state": "*",
                "book_imbalance_bucket": "*",
                "permission": "harvest_only",
                "reason": "wrong_hour",
            },
            {
                "market_id": "atlanta",
                "cutoff": "*",
                "hour_utc": "15:00Z",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "*",
                "regime": "*",
                "source_fresh": "*",
                "source_freshness_state": "*",
                "book_imbalance_bucket": "*",
                "permission": "harvest_only",
                "reason": "canonical_same_hour",
            },
        ]

        record = resolve_known_edge_record(row, records)

        self.assertEqual(record["reason"], "canonical_same_hour")
        self.assertIn("|15|", known_edge_record_key(record))

    def test_no_quote_known_edge_permission_fails_closed(self):
        quote = decide_quote(
            fresh_row(
                promotion_state="PASS",
                known_edge_allowed=True,
                known_edge_permission="no_quote",
                known_edge_reason="promotion_block",
                fair_probability=0.70,
                market_mid=0.50,
            ),
            now=NOW,
        )

        self.assertFalse(quote["quote_permission"])
        self.assertFalse(quote["known_edge_allowed"])
        self.assertEqual(quote["known_edge_permission"], "no_quote")
        self.assertEqual(quote["reason_code"], "NO_QUOTE_KNOWN_EDGE_PERMISSION")

    def test_known_edge_match_dimensions_are_written_for_diagnostics(self):
        quote = decide_quote(
            fresh_row(
                promotion_state="PASS",
                known_edge_allowed=True,
                known_edge_permission="no_quote",
                known_edge_reason="promotion_block",
                band_distance_bucket="edge_lt_1c",
                casebook_taxonomy="unmatched",
                source_freshness_state="all_fresh",
                book_imbalance_bucket="bid_heavy",
                fair_probability=0.70,
                market_mid=0.50,
            ),
            now=NOW,
        )

        expected_columns = {
            "known_edge_match_cutoff",
            "known_edge_match_hour_utc",
            "known_edge_match_band_distance_bucket",
            "known_edge_match_band_type",
            "known_edge_match_casebook_taxonomy",
            "known_edge_match_regime",
            "known_edge_match_source_fresh",
            "known_edge_match_source_freshness_state",
            "known_edge_match_book_imbalance_bucket",
        }
        self.assertTrue(expected_columns.issubset(set(QUOTE_COLUMNS)))
        self.assertEqual(quote["schema_version"], "mm_quote_intent_v0.3")
        self.assertEqual(quote["known_edge_match_cutoff"], "")
        self.assertEqual(quote["known_edge_match_hour_utc"], "15")
        self.assertEqual(quote["known_edge_match_band_distance_bucket"], "edge_lt_1c")
        self.assertEqual(quote["known_edge_match_band_type"], "eq")
        self.assertEqual(quote["known_edge_match_casebook_taxonomy"], "unmatched")
        self.assertEqual(quote["known_edge_match_regime"], "")
        self.assertEqual(quote["known_edge_match_source_fresh"], "true")
        self.assertEqual(quote["known_edge_match_source_freshness_state"], "all_fresh")
        self.assertEqual(quote["known_edge_match_book_imbalance_bucket"], "bid_heavy")

    def test_stale_watcher_fails_closed_before_quote_logic(self):
        quote = decide_quote(fresh_row(heartbeat_ok=False, watcher_age_seconds=999), now=NOW)

        self.assertFalse(quote["quote_permission"])
        self.assertEqual(quote["reason_code"], "NO_QUOTE_STALE_WATCHER")

    def test_zero_probability_is_valid_fair_value(self):
        quote = decide_quote(
            fresh_row(
                fair_probability=0.0,
                market_mid=0.0005,
                market_yes=0.0005,
                clob_best_bid=0.0,
                clob_best_ask=0.001,
            ),
            now=NOW,
        )

        self.assertNotEqual(quote["reason_code"], "NO_QUOTE_MISSING_FAIR")
        self.assertEqual(quote["fair_probability"], 0.0)

    def test_policy_snapshot_writes_reason_for_each_latest_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "model_version",
                    "range_label",
                    "condition_id",
                    "clob_yes_token_id",
                    "bin_kind",
                    "bin_value_c",
                    "model_probability",
                    "market_yes",
                    "best_bid",
                    "best_ask",
                    "market_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "range_label": "80-81 F",
                    "condition_id": "c1",
                    "clob_yes_token_id": "t1",
                    "bin_kind": "eq",
                    "bin_value_c": "80",
                    "model_probability": "0.51",
                    "market_yes": "0.50",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "market_status": "active",
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "range_label": "82-83 F",
                    "condition_id": "c2",
                    "clob_yes_token_id": "t2",
                    "bin_kind": "eq",
                    "bin_value_c": "82",
                    "model_probability": "0.70",
                    "market_yes": "0.50",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "market_status": "active",
                })
            with (folder / "clob_features_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "market_id",
                    "range_label",
                    "bin_kind",
                    "bin_value",
                    "bin_value_hi",
                    "clob_token_id",
                    "clob_book_captured_at_utc",
                    "clob_feature_available",
                    "clob_book_age_seconds",
                    "clob_midpoint",
                    "clob_spread",
                    "clob_best_bid",
                    "clob_best_ask",
                    "clob_depth_1pct_total",
                ])
                writer.writeheader()
                for token, label, value, model_mid in [
                    ("t1", "80-81 F", "80", "0.50"),
                    ("t2", "82-83 F", "82", "0.50"),
                ]:
                    writer.writerow({
                        "snapshot_id": "s1",
                        "captured_at_utc": "2026-06-14T15:59:30+00:00",
                        "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                        "market_id": "atlanta",
                        "range_label": label,
                        "bin_kind": "eq",
                        "bin_value": value,
                        "bin_value_hi": str(int(value) + 1),
                        "clob_token_id": token,
                        "clob_book_captured_at_utc": "2026-06-14T15:59:20+00:00",
                        "clob_feature_available": "1.0",
                        "clob_book_age_seconds": "10.0",
                        "clob_midpoint": model_mid,
                        "clob_spread": "0.02",
                        "clob_best_bid": "0.49",
                        "clob_best_ask": "0.51",
                        "clob_depth_1pct_total": "100.0",
                    })
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({
                "decisions": {
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "action": "KEEP_SHADOW",
                            "verdict": "SHADOW",
                        }
                    ]
                }
            }), encoding="utf-8")
            known_edge = write_known_edge_map(root / "known_edge.json", [{
                "market_id": "atlanta",
                "cutoff": "*",
                "hour_utc": "*",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "*",
                "regime": "*",
                "source_fresh": "*",
                "book_imbalance_bucket": "*",
                "permission": "harvest_only",
                "reason": "promotion_shadow",
            }])
            status = root / "observation_status.json"
            status.write_text(json.dumps({
                "last_heartbeat": "2026-06-14T15:59:50+00:00",
                "consecutive_errors": 0,
            }), encoding="utf-8")

            payload = run_policy_snapshot(
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                snapshots_root=snapshots_root,
                observation_status_path=status,
                out=root / "quotes_long.csv",
                json_out=root / "quotes.json",
                markets=["atlanta"],
                now=NOW,
            )
            self.assertEqual(payload["row_count"], 2)
            self.assertEqual(payload["live_trade_permission_rows"], 0)
            self.assertTrue(Path(payload["csv_out"]).exists())
            self.assertEqual(payload["reason_counts"]["QUOTE_HARVEST_MID"], 1)
            self.assertEqual(payload["reason_counts"]["NO_QUOTE_DISAGREEMENT_SHADOW"], 1)
            self.assertTrue(payload["known_edge_map"]["exists"])
            self.assertEqual({row["known_edge_permission"] for row in payload["rows"]}, {"harvest_only"})

    def test_policy_snapshot_does_not_let_edge_map_override_non_authorizing_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "model_version",
                    "range_label",
                    "condition_id",
                    "clob_yes_token_id",
                    "bin_kind",
                    "bin_value_c",
                    "model_probability",
                    "market_yes",
                    "best_bid",
                    "best_ask",
                    "market_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "range_label": "80-81 F",
                    "condition_id": "c1",
                    "clob_yes_token_id": "t1",
                    "bin_kind": "eq",
                    "bin_value_c": "80",
                    "model_probability": "0.70",
                    "market_yes": "0.50",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "market_status": "active",
                })
            with (folder / "clob_features_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "market_id",
                    "range_label",
                    "bin_kind",
                    "bin_value",
                    "bin_value_hi",
                    "clob_token_id",
                    "clob_book_captured_at_utc",
                    "clob_book_age_seconds",
                    "clob_midpoint",
                    "clob_spread",
                    "clob_best_bid",
                    "clob_best_ask",
                    "clob_depth_1pct_total",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "market_id": "atlanta",
                    "range_label": "80-81 F",
                    "bin_kind": "eq",
                    "bin_value": "80",
                    "bin_value_hi": "81",
                    "clob_token_id": "t1",
                    "clob_book_captured_at_utc": "2026-06-14T15:59:20+00:00",
                    "clob_book_age_seconds": "10.0",
                    "clob_midpoint": "0.50",
                    "clob_spread": "0.02",
                    "clob_best_bid": "0.49",
                    "clob_best_ask": "0.51",
                    "clob_depth_1pct_total": "100.0",
                })
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({
                "decisions": {
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "action": "PROMOTE_CANDIDATE",
                            "verdict": "PASS",
                        }
                    ]
                }
            }), encoding="utf-8")
            known_edge = write_known_edge_map(root / "known_edge.json", [{
                "market_id": "atlanta",
                "cutoff": "*",
                "hour_utc": "*",
                "band_distance_bucket": "*",
                "band_type": "*",
                "casebook_taxonomy": "*",
                "regime": "*",
                "source_fresh": "*",
                "book_imbalance_bucket": "*",
                "permission": "edge_allowed",
                "reason": "live_forward_paper_gate_clear",
            }])
            status = root / "observation_status.json"
            status.write_text(json.dumps({
                "last_heartbeat": "2026-06-14T15:59:50+00:00",
                "consecutive_errors": 0,
            }), encoding="utf-8")

            payload = run_policy_snapshot(
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                snapshots_root=snapshots_root,
                observation_status_path=status,
                out=root / "quotes_long.csv",
                json_out=root / "quotes.json",
                markets=["atlanta"],
                now=NOW,
            )

            self.assertEqual(payload["quote_permission_rows"], 0)
            self.assertEqual(payload["reason_counts"]["NO_QUOTE_DISAGREEMENT_SHADOW"], 1)
            row = payload["rows"][0]
            self.assertFalse(row["known_edge_allowed"])
            self.assertEqual(row["known_edge_permission"], "edge_research")
            self.assertTrue(row["known_edge_record_key"])
            self.assertEqual(row["promotion_state"], "SHADOW")
            self.assertFalse(payload["promotion"]["authorization_schema_supported"])
            self.assertEqual(
                payload["known_edge_map"]["sanitized_edge_allowed_count"],
                1,
            )

    def test_policy_snapshot_prefers_source_freshness_gap_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots_root = root / "snapshots"
            folder = snapshots_root / "highest-temperature-in-atlanta-on-june-14-2026"
            folder.mkdir(parents=True)
            with (folder / "snapshots_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "model_version",
                    "range_label",
                    "condition_id",
                    "clob_yes_token_id",
                    "bin_kind",
                    "bin_value_c",
                    "model_probability",
                    "market_yes",
                    "best_bid",
                    "best_ask",
                    "market_status",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "model_version": "candidate",
                    "range_label": "80-81 F",
                    "condition_id": "c1",
                    "clob_yes_token_id": "t1",
                    "bin_kind": "eq",
                    "bin_value_c": "80",
                    "model_probability": "0.70",
                    "market_yes": "0.50",
                    "best_bid": "0.49",
                    "best_ask": "0.51",
                    "market_status": "active",
                })
            with (folder / "clob_features_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "captured_at_utc",
                    "event_slug",
                    "market_id",
                    "range_label",
                    "bin_kind",
                    "bin_value",
                    "bin_value_hi",
                    "clob_token_id",
                    "clob_book_captured_at_utc",
                    "clob_book_age_seconds",
                    "clob_midpoint",
                    "clob_spread",
                    "clob_best_bid",
                    "clob_best_ask",
                    "clob_depth_1pct_total",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "captured_at_utc": "2026-06-14T15:59:30+00:00",
                    "event_slug": "highest-temperature-in-atlanta-on-june-14-2026",
                    "market_id": "atlanta",
                    "range_label": "80-81 F",
                    "bin_kind": "eq",
                    "bin_value": "80",
                    "bin_value_hi": "81",
                    "clob_token_id": "t1",
                    "clob_book_captured_at_utc": "2026-06-14T15:59:20+00:00",
                    "clob_book_age_seconds": "10.0",
                    "clob_midpoint": "0.50",
                    "clob_spread": "0.02",
                    "clob_best_bid": "0.49",
                    "clob_best_ask": "0.51",
                    "clob_depth_1pct_total": "100.0",
                })
            with (folder / "source_status_long.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "snapshot_id",
                    "source",
                    "ok",
                    "status",
                    "stale",
                ])
                writer.writeheader()
                writer.writerow({
                    "snapshot_id": "s1",
                    "source": "wu_history",
                    "ok": "False",
                    "status": "failed",
                    "stale": "False",
                })
                writer.writerow({
                    "snapshot_id": "s1",
                    "source": "metar",
                    "ok": "True",
                    "status": "fresh",
                    "stale": "False",
                })
            promotion = root / "promotion.json"
            promotion.write_text(json.dumps({
                "decisions": {
                    "markets": [
                        {
                            "market_id": "atlanta",
                            "action": "PROMOTE_CANDIDATE",
                            "verdict": "PASS",
                        }
                    ]
                }
            }), encoding="utf-8")
            known_edge = write_known_edge_map(root / "known_edge.json", [
                {
                    "market_id": "atlanta",
                    "cutoff": "*",
                    "hour_utc": "*",
                    "band_distance_bucket": "*",
                    "band_type": "*",
                    "casebook_taxonomy": "*",
                    "regime": "*",
                    "source_fresh": "*",
                    "source_freshness_state": "*",
                    "book_imbalance_bucket": "*",
                    "permission": "edge_allowed",
                    "reason": "live_forward_paper_gate_clear",
                },
                {
                    "market_id": "*",
                    "cutoff": "*",
                    "hour_utc": "*",
                    "band_distance_bucket": "*",
                    "band_type": "*",
                    "casebook_taxonomy": "*",
                    "regime": "*",
                    "source_fresh": "*",
                    "source_freshness_state": "failed:wu_history",
                    "book_imbalance_bucket": "*",
                    "permission": "harvest_only",
                    "reason": "source_freshness_model_gap",
                },
            ])
            status = root / "observation_status.json"
            status.write_text(json.dumps({
                "last_heartbeat": "2026-06-14T15:59:50+00:00",
                "consecutive_errors": 0,
            }), encoding="utf-8")

            payload = run_policy_snapshot(
                promotion_refresh=promotion,
                known_edge_map=known_edge,
                snapshots_root=snapshots_root,
                observation_status_path=status,
                out=root / "quotes_long.csv",
                json_out=root / "quotes.json",
                markets=["atlanta"],
                now=NOW,
            )

            row = payload["rows"][0]
            self.assertEqual(row["source_freshness_state"], "failed:wu_history")
            self.assertEqual(row["known_edge_permission"], "harvest_only")
            self.assertEqual(row["known_edge_reason"], "source_freshness_model_gap")
            self.assertFalse(row["known_edge_allowed"])
            self.assertNotEqual(row["reason_code"], "QUOTE_EDGE_MODEL")


if __name__ == "__main__":
    unittest.main()
