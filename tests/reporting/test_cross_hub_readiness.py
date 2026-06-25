import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.source_gates.cross_hub_readiness import (
    build_cross_hub_readiness,
    quoteability_from_runs,
    write_markdown_report,
)


def _collection(market_id, *, state="CLEAN", snapshots=120, trading_allowed=True):
    return {
        "market_id": market_id,
        "city": market_id.title(),
        "state": state,
        "snapshots": snapshots,
        "reason": "ok" if state == "CLEAN" else "snapshot gap",
        "source_family_degradation": {
            "available": True,
            "affected_family_count": 0,
            "failed_source_count": 0,
            "fallback_source_count": 0,
            "rate_limited_source_count": 0,
            "trading_evidence_allowed": trading_allowed,
            "model_review_allowed": True,
            "families": {
                "local_history": {"status": "healthy", "source_count": 1, "fresh_source_count": 1},
                "metar": {"status": "healthy", "source_count": 1, "fresh_source_count": 1},
                "wu_history": {"status": "healthy", "source_count": 1, "fresh_source_count": 1},
            },
        },
    }


def _trust(market_id, *, ece=0.02, score=50):
    return {
        "market": market_id,
        "trust_score": score,
        "grade": "Moderate",
        "settled_days": 5,
        "model_ece": ece,
    }


def _decision(market_id, action, *, delta_current=-0.01, delta_market=-0.001, reason="passes"):
    return {
        "market_id": market_id,
        "city": market_id.title(),
        "action": action,
        "reason": reason,
        "metrics": {
            "candidate_brier": 0.03,
            "current_brier": 0.04,
            "market_brier": 0.031,
            "delta_vs_current": delta_current,
            "delta_vs_market": delta_market,
        },
    }


def _quote(market_id, rows, quote_rows):
    return {
        "rows": rows,
        "quote_rows": quote_rows,
        "no_quote_rows": rows - quote_rows,
        "quote_rate": quote_rows / rows if rows else None,
        "top_no_quote_reasons": [{"reason": "NO_QUOTE_STALE_INPUT", "rows": rows - quote_rows}],
    }


def _live_evidence(markets):
    return {
        "summary": {
            "per_market_live_forward_evidence": {
                "model_review_evidence": {
                    "countable_markets": markets,
                    "blocked_markets": [],
                },
                "paper_trading_evidence": {
                    "countable_markets": markets,
                    "blocked_markets": [],
                },
                "live_trade_permission_evidence": {
                    "countable_markets": markets,
                    "blocked_markets": [],
                },
            }
        },
        "per_market_evidence_credits": [],
    }


class TestCrossHubReadiness(unittest.TestCase):
    def test_model_labels_do_not_confuse_quoteability_or_collection_for_edge(self):
        markets = ["atlanta", "dallas", "miami", "seattle"]
        fleet = {
            "collection": {"markets": [_collection(market) for market in markets]},
            "trust_readiness": {
                "atlanta": _trust("atlanta"),
                "dallas": _trust("dallas", ece=0.07),
                "miami": _trust("miami"),
                "seattle": _trust("seattle"),
            },
            "live_forward_slo": {"counts_toward_live_forward_gate": True, "status": "PASS"},
            "loop_integrity": {"summary": {"ok": True, "malformed_lines": 0}},
        }
        promotion = {
            "decisions": {
                "markets": [
                    _decision("atlanta", "PROMOTE_CANDIDATE", reason="beats current and market"),
                    _decision("dallas", "PROMOTE_CANDIDATE", reason="clean collection is not enough"),
                    _decision(
                        "miami",
                        "KEEP_SHADOW",
                        delta_current=0.0,
                        delta_market=0.001,
                        reason="not proven better than current replay",
                    ),
                    _decision(
                        "seattle",
                        "KEEP_SHADOW",
                        delta_market=0.02,
                        reason="not proven better than market on pinned rows",
                    ),
                ]
            }
        }
        quoteability = {
            "markets": {
                "atlanta": _quote("atlanta", 100, 10),
                "dallas": _quote("dallas", 100, 5),
                "miami": _quote("miami", 1000, 900),
                "seattle": _quote("seattle", 1000, 950),
            },
            "diagnostics": {},
        }
        latest = {
            "exists": True,
            "preflight_status": "PASS",
            "markets": {market: {"market_id": market, "status": "PASS"} for market in markets},
        }

        payload = build_cross_hub_readiness(
            fleet,
            promotion,
            _live_evidence(markets),
            quoteability,
            latest,
            max_ece=0.05,
        )
        rows = {row["market_id"]: row for row in payload["markets"]}

        self.assertEqual(rows["atlanta"]["readiness_label"], "promote")
        self.assertEqual(rows["dallas"]["model_label"], "model-blocked")
        self.assertIn("ECE 0.0700 > 0.0500", rows["dallas"]["model_reasons"])
        self.assertIn("dallas_trust_guardrail", rows["dallas"]["hub_lessons"])
        self.assertEqual(rows["miami"]["model_label"], "shadow")
        self.assertEqual(rows["seattle"]["model_label"], "shadow")
        self.assertIn("quoteability_not_edge", rows["miami"]["hub_lessons"])
        self.assertIn("quoteability_not_edge", rows["seattle"]["hub_lessons"])

    def test_broad_live_claim_and_final_labels_block_on_shared_plumbing(self):
        fleet = {
            "collection": {"markets": [_collection("atlanta", state="PARTIAL")]},
            "trust_readiness": {"atlanta": _trust("atlanta")},
            "live_forward_slo": {
                "counts_toward_live_forward_gate": False,
                "status": "BLOCK",
                "reason": "snapshot coverage gap",
            },
            "loop_integrity": {"summary": {"ok": False, "malformed_lines": 12}},
        }
        promotion = {"decisions": {"markets": [_decision("atlanta", "PROMOTE_CANDIDATE")]}}
        latest = {
            "exists": True,
            "preflight_status": "BLOCK",
            "markets": {
                "atlanta": {
                    "market_id": "atlanta",
                    "status": "BLOCK",
                    "reason_kind": "missing_preflight",
                }
            },
        }

        payload = build_cross_hub_readiness(
            fleet,
            promotion,
            _live_evidence(["atlanta"]),
            {"markets": {"atlanta": _quote("atlanta", 10, 2)}, "diagnostics": {}},
            latest,
        )
        row = payload["markets"][0]
        blocker_gates = {item["gate"] for item in payload["broad_live_claim"]["blockers"]}

        self.assertFalse(payload["broad_live_claim"]["allowed"])
        self.assertEqual(row["model_label"], "promote")
        self.assertEqual(row["readiness_label"], "ops-blocked")
        self.assertIn("live_forward_slo", blocker_gates)
        self.assertIn("serialization_integrity", blocker_gates)
        self.assertIn("latest_preflight", blocker_gates)
        self.assertIn("shared_plumbing_blocker", row["hub_lessons"])

    def test_quoteability_reader_handles_legacy_degree_symbol_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data" / "mm_runs"
            folder = root / "2026-06-18" / "run1"
            folder.mkdir(parents=True)
            csv_text = "\n".join([
                "market_id,run_id,action,quote_permission,reason_code,reason_detail",
                "miami,run1,QUOTE,true,,edge on 90\xb0F",
                "miami,run1,,false,NO_QUOTE_STALE_INPUT,stale 90\xb0F",
            ])
            (folder / "quote_intents_long.csv").write_bytes(csv_text.encode("cp1252"))

            payload = quoteability_from_runs(root)

        self.assertEqual(payload["diagnostics"]["legacy_encoding_files"], 1)
        self.assertEqual(payload["markets"]["miami"]["rows"], 2)
        self.assertEqual(payload["markets"]["miami"]["quote_rows"], 1)
        self.assertEqual(
            payload["markets"]["miami"]["top_no_quote_reasons"][0]["reason"],
            "NO_QUOTE_STALE_INPUT",
        )

    def test_report_emits_required_table_columns_and_lessons(self):
        payload = {
            "schema_version": "cross_hub_readiness_v0.1",
            "generated_at_utc": "2026-06-18T00:00:00+00:00",
            "broad_live_claim": {"allowed": False, "blockers": [{"gate": "live_forward_slo", "detail": "gap"}]},
            "quoteability_diagnostics": {"files": 1},
            "markets": [
                {
                    "market_id": "seattle",
                    "readiness_label": "ops-blocked",
                    "model_label": "shadow",
                    "collection": {"state": "PARTIAL", "snapshots": 10},
                    "source_redundancy": {
                        "status": "healthy",
                        "family_count": 3,
                        "fallback_source_count": 0,
                        "failed_source_count": 0,
                        "fresh_source_count": 2,
                        "source_count": 3,
                        "official_or_local_families": ["metar"],
                    },
                    "trust": {"trust_score": 43, "grade": "Low", "model_ece": 0.02},
                    "candidate_vs_current": {"delta_vs_current": -0.01},
                    "candidate_vs_market": {"delta_vs_market": 0.02},
                    "quoteability": _quote("seattle", 1000, 950),
                    "live_forward_evidence": {
                        "model_review": "countable",
                        "paper_trading": "countable",
                        "live_trade_permission": "blocked",
                    },
                    "hub_lessons": ["quoteability_not_edge", "shared_plumbing_blocker"],
                    "ops_blockers": ["snapshot gap"],
                    "model_reasons": ["not proven better than market"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_markdown_report(Path(tmp) / "report.md", payload)
            text = path.read_text(encoding="utf-8")

        self.assertIn("Source Redundancy", text)
        self.assertIn("fresh 2/3", text)
        self.assertIn("Trust/ECE", text)
        self.assertIn("Candidate vs Current", text)
        self.assertIn("Candidate vs Market", text)
        self.assertIn("Quoteability", text)
        self.assertIn("Live-Forward Evidence", text)
        self.assertIn("quoteability_not_edge", text)


if __name__ == "__main__":
    unittest.main()
