import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from weather.reporting.shadow_ab_monitor import build_monitor, write_json, write_report  # noqa: E402


def _write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestShadowABMonitor(unittest.TestCase):
    def test_monitor_classifies_promote_shadow_and_alert_markets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            promotion = _write(root / "promotion.json", {
                "readiness": {"status": "OPEN", "blockers": []},
                "serving_gauntlet": {"verdict": "PARTIAL_PASS", "blocking_markets": {"miami": {}}},
                "decisions": {
                    "promote_markets": ["nyc"],
                    "shadow_markets": ["denver"],
                    "blocked_markets": ["miami"],
                    "markets": [
                        {"market_id": "nyc", "action": "PROMOTE_CANDIDATE", "reason": "clear"},
                        {"market_id": "denver", "action": "KEEP_SHADOW", "reason": "trust low"},
                        {"market_id": "miami", "action": "BLOCK_CANDIDATE", "reason": "serving block"},
                    ],
                },
                "promotion_allowlist": {
                    "schema_version": "promotion_allowlist_v0.1",
                    "path": "allowlist.json",
                    "candidate_id": "candidate_v1",
                    "markets": [
                        {"market_id": "nyc", "action": "PROMOTE_CANDIDATE", "reason": "clear"},
                        {"market_id": "denver", "action": "KEEP_SHADOW", "reason": "trust low"},
                        {"market_id": "miami", "action": "BLOCK_CANDIDATE", "blocker_reason": "serving block"},
                    ],
                },
            })
            candidate = _write(root / "candidate.json", {
                "replay_gate": {"global_ok": True},
                "market_rows": [
                    {
                        "market_id": "nyc",
                        "verdict": "PASS",
                        "days": 3,
                        "rows": 30,
                        "comparison": {
                            "candidate_brier": 0.02,
                            "current_brier": 0.03,
                            "market_brier": 0.025,
                            "delta_vs_current": -0.01,
                            "delta_vs_market": -0.005,
                        },
                    },
                    {
                        "market_id": "denver",
                        "verdict": "SHADOW",
                        "days": 1,
                        "rows": 10,
                        "comparison": {
                            "delta_vs_current": 0.0,
                            "delta_vs_market": 0.0,
                        },
                    },
                    {
                        "market_id": "miami",
                        "verdict": "BLOCK",
                        "days": 2,
                        "rows": 20,
                        "comparison": {
                            "delta_vs_current": 0.010,
                            "delta_vs_market": 0.020,
                        },
                    },
                ],
            })

            payload = build_monitor(promotion, candidate, current_tol=0.003, market_tol=0.003)

        by_market = {row["market_id"]: row for row in payload["markets"]}
        self.assertEqual(payload["status"], "ALERT")
        self.assertEqual(by_market["nyc"]["status"], "PROMOTE_READY")
        self.assertEqual(by_market["denver"]["status"], "SHADOW")
        self.assertEqual(by_market["miami"]["status"], "ALERT")
        self.assertIn("candidate regresses current", "; ".join(by_market["miami"]["alerts"]))
        self.assertEqual(payload["summary"]["alert_markets"], 1)
        self.assertEqual(payload["summary"]["unique_observation_count"], 60)
        self.assertEqual(payload["evidence_accounting"]["source"], "candidate_replay_market_rows")
        self.assertTrue(payload["promotion_allowlist"]["present"])
        self.assertEqual(payload["promotion_allowlist"]["candidate_id"], "candidate_v1")

    def test_monitor_alerts_on_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_monitor(Path(tmp) / "missing_promotion.json", Path(tmp) / "missing_candidate.json")

        self.assertEqual(payload["status"], "ALERT")
        self.assertIn("missing promotion refresh artifact", payload["global_alerts"])
        self.assertIn("missing pooled candidate replay artifact", payload["global_alerts"])

    def test_outputs_write_json_and_markdown_report(self):
        payload = {
            "schema_version": "shadow_ab_monitor_v0.1",
            "generated_at_utc": "2026-06-15T00:00:00+00:00",
            "status": "WARN",
            "summary": {
                "market_count": 1,
                "promote_ready_markets": 0,
                "shadow_markets": 1,
                "alert_markets": 0,
                "alert_count": 0,
            },
            "global_alerts": [],
            "markets": [
                {
                    "market_id": "denver",
                    "status": "SHADOW",
                    "promotion_action": "KEEP_SHADOW",
                    "candidate_verdict": "SHADOW",
                    "days": 1,
                    "rows": 10,
                    "unique_observations": 10,
                    "delta_vs_current": 0.0,
                    "delta_vs_market": 0.0,
                    "alerts": [],
                    "warnings": ["trust low"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            json_path = write_json(Path(tmp) / "monitor.json", payload)
            report_path = write_report(Path(tmp) / "monitor.md", payload)
            saved = json.loads(json_path.read_text(encoding="utf-8"))
            report = report_path.read_text(encoding="utf-8")

        self.assertEqual(saved["status"], "WARN")
        self.assertIn("Shadow/A-B Monitor", report)
        self.assertIn("denver", report)


if __name__ == "__main__":
    unittest.main()
