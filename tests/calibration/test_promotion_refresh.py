import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath("src"))

from promotion_refresh import (  # noqa: E402
    _candidate_gap_driver_rows,
    _candidate_source_freshness_rows,
    _candidate_summary,
    _serving_blocking_source_freshness_rows,
    build_family_decisions,
    promotion_readiness,
    write_report,
)


def _spec(market_id, city, unit="F"):
    return SimpleNamespace(id=market_id, city_label=city, display_unit=unit)


class TestPromotionRefresh(unittest.TestCase):
    def test_family_decisions_promote_only_passing_family_markets(self):
        specs = [
            _spec("nyc", "New York"),
            _spec("denver", "Denver"),
            _spec("toronto", "Toronto", unit="C"),
        ]
        manifest = {
            "entries": [
                {"market_id": "nyc"},
                {"market_id": "nyc"},
                {"market_id": "denver"},
                {"market_id": "toronto"},
            ],
        }
        trust_rows = [
            {"market": "nyc", "trust_score": 80, "grade": "Strong", "settled_days": 4},
            {"market": "denver", "trust_score": 15, "grade": "Unproven", "settled_days": 1},
        ]
        candidate_report = {
            "replay_gate": {"global_ok": True},
            "market_rows": [
                {
                    "market_id": "nyc",
                    "verdict": "PASS",
                    "reason": "beats current replay and clears market/trust gates",
                    "days": 4,
                    "snapshots": 20,
                    "rows": 60,
                    "comparison": {
                        "candidate_brier": 0.02,
                        "current_brier": 0.04,
                        "market_brier": 0.03,
                        "delta_vs_current": -0.02,
                        "delta_vs_market": -0.01,
                    },
                },
                {
                    "market_id": "denver",
                    "verdict": "SHADOW",
                    "reason": "trust 15 < 25",
                    "days": 1,
                    "snapshots": 5,
                    "rows": 15,
                    "comparison": {"candidate_brier": 0.05},
                },
            ],
        }

        decisions = build_family_decisions(
            manifest,
            trust_rows,
            candidate_report,
            specs=specs,
        )

        self.assertEqual(decisions["promote_markets"], ["nyc"])
        self.assertEqual(decisions["shadow_markets"], ["denver"])
        self.assertEqual(decisions["blocked_markets"], [])
        self.assertEqual(decisions["family_market_count"], 2)
        nyc = next(row for row in decisions["markets"] if row["market_id"] == "nyc")
        self.assertEqual(nyc["settled_days_in_corpus"], 2)
        self.assertEqual(nyc["action"], "PROMOTE_CANDIDATE")

    def test_global_replay_gate_blocks_otherwise_passing_candidate(self):
        specs = [_spec("nyc", "New York")]
        candidate_report = {
            "replay_gate": {
                "global_ok": False,
                "corpus_message": "FAIL: 1 corpus pin warning(s)",
            },
            "market_rows": [
                {
                    "market_id": "nyc",
                    "verdict": "PASS",
                    "reason": "passes local gates",
                    "days": 3,
                    "snapshots": 9,
                    "rows": 27,
                    "comparison": {},
                },
            ],
        }

        decisions = build_family_decisions(
            {"entries": [{"market_id": "nyc"}]},
            [{"market": "nyc", "trust_score": 80, "grade": "Strong", "settled_days": 3}],
            candidate_report,
            specs=specs,
        )

        self.assertEqual(decisions["promote_markets"], [])
        self.assertEqual(decisions["blocked_markets"], ["nyc"])
        self.assertIn("global replay gate failed", decisions["markets"][0]["reason"])

    def test_missing_candidate_rows_stay_shadow_not_promoted(self):
        decisions = build_family_decisions(
            {"entries": []},
            [],
            {"replay_gate": {"global_ok": True}, "market_rows": []},
            specs=[_spec("austin", "Austin")],
        )

        self.assertEqual(decisions["shadow_markets"], ["austin"])
        self.assertEqual(decisions["markets"][0]["action"], "KEEP_SHADOW")
        self.assertIn("no pinned candidate rows", decisions["markets"][0]["reason"])

    def test_promotion_readiness_surfaces_market_and_serving_blockers(self):
        readiness = promotion_readiness(
            {"aggregate": {"delta_vs_market": 0.0123}},
            {"verdict": "BLOCK"},
            {"shadow_markets": ["austin"], "blocked_markets": []},
        )

        categories = {row["category"] for row in readiness["blockers"]}
        self.assertEqual(readiness["status"], "OPEN")
        self.assertIn("candidate_market_skill", categories)
        self.assertIn("per_market_shadow", categories)
        self.assertIn("current_serving_gauntlet", categories)

    def test_candidate_summary_preserves_gap_driver_slices(self):
        summary = _candidate_summary(
            {
                "aggregate": {},
                "by_hour": [{"group": 7, "n": 10, "delta_vs_market": 0.02}],
                "by_bin_type": [{"group": "eq", "n": 20, "delta_vs_market": 0.01}],
                "by_settlement_distance": [{"group": "0", "n": 5, "delta_vs_market": 0.20}],
                "market_rows": [
                    {
                        "market_id": "miami",
                        "rows": 30,
                        "comparison": {
                            "candidate_brier": 0.07,
                            "market_brier": 0.04,
                            "delta_vs_current": -0.01,
                            "delta_vs_market": 0.03,
                        },
                    },
                ],
                "microstructure": {
                    "gated": {
                        "by_taxonomy": [{"group": "market_lead", "n": 3, "delta_vs_market": 0.30}],
                    },
                },
            },
            "candidate.json",
            "candidate.md",
        )

        slices = summary["slices"]
        self.assertEqual(slices["by_market"][0]["group"], "miami")
        self.assertEqual(slices["by_market"][0]["n"], 30)
        self.assertEqual(slices["by_cutoff_hour"][0]["group"], 7)
        self.assertEqual(slices["by_band_type"][0]["group"], "eq")
        self.assertEqual(slices["by_settlement_distance"][0]["group"], "0")
        self.assertEqual(slices["by_clob_taxonomy"][0]["group"], "market_lead")

    def test_candidate_gap_driver_rows_rank_by_excess_brier(self):
        rows = _candidate_gap_driver_rows({
            "slices": {
                "by_market": [
                    {
                        "group": "miami",
                        "n": 25,
                        "candidate_brier": 0.20,
                        "market_brier": 0.10,
                        "delta_vs_market": 0.10,
                    }
                ],
                "by_cutoff_hour": [
                    {
                        "group": 7,
                        "n": 100,
                        "candidate_brier": 0.10,
                        "market_brier": 0.05,
                        "delta_vs_current": -0.01,
                        "delta_vs_market": 0.05,
                    }
                ],
                "by_band_type": [
                    {
                        "group": "eq",
                        "n": 10,
                        "candidate_brier": 0.50,
                        "market_brier": 0.10,
                        "delta_vs_market": 0.40,
                    }
                ],
            }
        })

        self.assertEqual(rows[0]["slice"], "cutoff_hour")
        self.assertEqual(rows[0]["excess_brier_rows"], 5.0)
        self.assertEqual(rows[2]["slice"], "market")

    def test_candidate_source_freshness_rows_include_failed_and_stale_groups(self):
        rows = _candidate_source_freshness_rows({
            "slices": {
                "by_source_freshness": [
                    {"group": "all_fresh", "n": 100, "candidate_brier": 0.08, "market_brier": 0.04, "delta_vs_market": 0.04},
                    {"group": "failed:wu_history", "n": 20, "candidate_brier": 0.30, "market_brier": 0.10, "delta_vs_market": 0.20},
                    {"group": "stale:metar", "n": 10, "candidate_brier": 0.05, "market_brier": 0.07, "delta_vs_market": -0.02},
                ],
            }
        })

        self.assertEqual(rows[0]["group"], "all_fresh")
        self.assertEqual(rows[1]["group"], "failed:wu_history")
        self.assertEqual(rows[2]["group"], "stale:metar")

    def test_write_report_emits_source_freshness_slice_when_available(self):
        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "family_unit": "F",
            "corpus": {},
            "candidate": {
                "verdict": "PASS_WITH_SHADOWS",
                "candidate_market_verdict": "PASS_WITH_SHADOWS",
                "cutover_decision": "PER_MARKET_ONLY",
                "aggregate": {},
                "slices": {
                    "by_source_freshness": [
                        {
                            "group": "failed:wu_history",
                            "n": 20,
                            "candidate_brier": 0.30,
                            "market_brier": 0.10,
                            "delta_vs_current": -0.01,
                            "delta_vs_market": 0.20,
                        }
                    ],
                },
            },
            "readiness": {"status": "OPEN", "blockers": []},
            "decisions": {"promote_markets": [], "shadow_markets": [], "blocked_markets": [], "markets": []},
            "serving_gauntlet": None,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(Path(tmp) / "report.md", payload)
            text = path.read_text(encoding="utf-8")

        self.assertIn("### Source Freshness Slice", text)
        self.assertIn("failed:wu_history", text)
        self.assertNotIn("not available in the candidate replay rows yet", text)

    def test_write_report_emits_serving_blocking_source_freshness(self):
        serving = {
            "verdict": "PARTIAL_PASS",
            "market_rows": [
                {
                    "market_id": "miami",
                    "verdict": "BLOCK",
                    "rows": 11,
                    "comparison": {"code_effect": 0.01},
                    "reason": "code regression",
                }
            ],
            "decomposition": {
                "blocking_markets": {
                    "miami": {
                        "by_source_freshness": [
                            {
                                "group": "failed:wu_history",
                                "n": 11,
                                "replayed_brier": 0.30,
                                "recorded_brier": 0.10,
                                "market_brier": 0.20,
                                "code_effect": 0.20,
                            }
                        ]
                    }
                }
            },
        }
        rows = _serving_blocking_source_freshness_rows(serving)
        self.assertEqual(rows[0][0], "miami")
        self.assertEqual(rows[0][1], "failed:wu_history")

        payload = {
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "family_unit": "F",
            "corpus": {},
            "candidate": {"aggregate": {}, "slices": {}},
            "readiness": {"status": "OPEN", "blockers": []},
            "decisions": {"promote_markets": [], "shadow_markets": [], "blocked_markets": [], "markets": []},
            "serving_gauntlet": serving,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(Path(tmp) / "report.md", payload)
            text = path.read_text(encoding="utf-8")

        self.assertIn("### Serving Blocking Source Freshness", text)
        self.assertIn("failed:wu_history", text)


if __name__ == "__main__":
    unittest.main()
