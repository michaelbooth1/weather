import json
import tempfile
import unittest
from pathlib import Path

from weather.reporting.research.cross_hub_research_audit import (
    build_research_audit,
    summarize_run_logs,
    write_markdown_report,
)


def _readiness_row(
    market_id,
    *,
    model_label="shadow",
    readiness_label="ops-blocked",
    delta_current=-0.001,
    delta_market=0.004,
    quote_rows=100,
    quote_total=1000,
    ece=0.02,
    trust_score=43,
):
    return {
        "market_id": market_id,
        "city": market_id.title(),
        "readiness_label": readiness_label,
        "model_label": model_label,
        "promotion_action": "PROMOTE_CANDIDATE" if model_label == "promote" else "KEEP_SHADOW",
        "candidate_vs_current": {
            "candidate_brier": 0.03,
            "current_brier": 0.04,
            "delta_vs_current": delta_current,
        },
        "candidate_vs_market": {
            "candidate_brier": 0.03,
            "market_brier": 0.031,
            "delta_vs_market": delta_market,
        },
        "trust": {"trust_score": trust_score, "grade": "Low", "model_ece": ece},
        "collection": {"state": "PARTIAL", "snapshots": 12},
        "source_redundancy": {
            "status": "healthy",
            "source_count": 3,
            "fresh_source_count": 3,
            "official_or_local_families": ["metar", "local_history"],
        },
        "quoteability": {
            "rows": quote_total,
            "quote_rows": quote_rows,
            "quote_rate": quote_rows / quote_total if quote_total else None,
            "top_no_quote_reasons": [{"reason": "NO_QUOTE_STALE_INPUT", "rows": quote_total - quote_rows}],
        },
        "live_forward_evidence": {"model_review": "countable", "paper_trading": "countable", "live_trade_permission": "blocked"},
    }


def _promotion_decision(market_id, *, action="KEEP_SHADOW", delta_current=-0.001, delta_market=0.004):
    return {
        "market_id": market_id,
        "action": action,
        "metrics": {
            "candidate_brier": 0.03,
            "current_brier": 0.04,
            "market_brier": 0.031,
            "delta_vs_current": delta_current,
            "delta_vs_market": delta_market,
            "candidate_ece": 0.02,
            "rows": 100,
        },
    }


class TestCrossHubResearchAudit(unittest.TestCase):
    def test_build_research_audit_separates_performance_quoteability_and_trust(self):
        readiness = {
            "schema_version": "cross_hub_readiness_v0.1",
            "broad_live_claim": {"allowed": False, "blockers": [{"gate": "live_forward_slo", "detail": "gap"}]},
            "markets": [
                _readiness_row("atlanta", model_label="promote", delta_market=-0.002, quote_rows=50),
                _readiness_row("dallas", model_label="model-blocked", delta_market=-0.001, quote_rows=20, ece=0.07),
                _readiness_row("seattle", model_label="shadow", delta_market=0.02, quote_rows=900),
                _readiness_row("miami", model_label="shadow", delta_market=0.001, quote_rows=1),
            ],
        }
        promotion = {
            "schema_version": "promotion_refresh_v0.1",
            "decisions": {
                "markets": [
                    _promotion_decision("atlanta", action="PROMOTE_CANDIDATE", delta_market=-0.002),
                    _promotion_decision("dallas", action="PROMOTE_CANDIDATE", delta_market=-0.001),
                    _promotion_decision("seattle", action="KEEP_SHADOW", delta_market=0.02),
                    _promotion_decision("miami", action="KEEP_SHADOW", delta_market=0.001),
                ]
            },
            "market_skill_diagnostics": [
                {"market_id": "seattle", "delta_vs_market": 0.02, "owner": "Seattle residual repair"},
            ],
        }
        trust = [
            {"market": "dallas", "trust_score": 35, "grade": "Low", "model_ece": 0.07},
            {"market": "seattle", "trust_score": 43, "grade": "Low", "model_ece": 0.02},
        ]
        run_logs = {
            "run_summary_count": 2,
            "markets": {
                "atlanta": {"run_count": 2, "pass_rate": 1.0, "latest": {"target_date": "2026-06-19", "status": "PASS", "preflight_status": "PASS"}},
                "dallas": {"run_count": 2, "pass_rate": 1.0, "latest": {"target_date": "2026-06-19", "status": "PASS", "preflight_status": "PASS"}},
                "seattle": {"run_count": 2, "pass_rate": 0.5, "latest": {"target_date": "2026-06-19", "status": "BLOCK", "preflight_status": "PASS"}},
                "miami": {"run_count": 2, "pass_rate": 1.0, "latest": {"target_date": "2026-06-19", "status": "PASS", "preflight_status": "PASS"}},
            },
        }

        payload = build_research_audit(readiness, promotion, trust, {"hourly_performance_gate": {"blockers": []}}, run_logs)
        rows = {row["market_id"]: row for row in payload["markets"]}
        lessons = {row["lesson_id"]: row for row in payload["transfer_lessons"]}

        self.assertEqual(rows["atlanta"]["performance_class"], "beats current and market")
        self.assertIn("denver_atlanta_promotion_pattern", rows["atlanta"]["transfer_lesson_ids"])
        self.assertIn("trust/ECE blocks treating ops health as model readiness", rows["dallas"]["findings"])
        self.assertIn("dallas_trust_guardrail", rows["dallas"]["transfer_lesson_ids"])
        self.assertIn("quote rows are not promotion evidence", rows["seattle"]["findings"])
        self.assertIn("quoteability_not_edge", rows["miami"]["transfer_lesson_ids"])
        self.assertIn("seattle", lessons["quoteability_not_edge"]["source_hubs"])
        self.assertFalse(payload["summary"]["broad_live_claim_allowed"])
        self.assertEqual(payload["summary"]["best_market_gap_hubs"][0]["market_id"], "atlanta")

    def test_summarize_run_logs_counts_market_status_and_failing_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mm_runs"
            first = root / "2026-06-18" / "run1"
            latest = root / "2026-06-19" / "run2"
            first.mkdir(parents=True)
            latest.mkdir(parents=True)
            (first / "run_summary.json").write_text(json.dumps({
                "run_id": "run1",
                "target_date": "2026-06-18",
                "preflight_status": "BLOCK",
                "live_forward_gate_status": "BLOCK",
                "markets": [
                    {
                        "market_id": "seattle",
                        "status": "BLOCK",
                        "reason_kind": "missing_preflight",
                        "blocking_reasons": ["missing current CLOB book rows"],
                        "book_audit": {"captures": 0},
                        "csv_encoding": {"issue_count": 1, "status": "WARN"},
                        "gates": [{"name": "clob_books", "ok": False}],
                    }
                ],
            }), encoding="utf-8")
            (latest / "run_summary.json").write_text(json.dumps({
                "run_id": "run2",
                "target_date": "2026-06-19",
                "preflight_status": "PASS",
                "live_forward_gate_status": "BLOCK",
                "markets": [
                    {
                        "market_id": "seattle",
                        "status": "PASS",
                        "book_audit": {"captures": 12, "ok": True},
                        "csv_encoding": {"issue_count": 0, "status": "OK"},
                        "gates": [{"name": "clob_books", "ok": True}],
                    }
                ],
            }), encoding="utf-8")

            payload = summarize_run_logs(root)

        row = payload["markets"]["seattle"]
        self.assertEqual(row["run_count"], 2)
        self.assertEqual(row["status_counts"], {"BLOCK": 1, "PASS": 1})
        self.assertEqual(row["csv_issue_count"], 1)
        self.assertEqual(row["top_failing_gates"][0], {"name": "clob_books", "count": 1})
        self.assertEqual(row["latest"]["target_date"], "2026-06-19")

    def test_markdown_report_includes_audit_comparison_and_transfer_sections(self):
        payload = build_research_audit(
            {
                "schema_version": "cross_hub_readiness_v0.1",
                "broad_live_claim": {"allowed": False, "blockers": []},
                "markets": [_readiness_row("atlanta", model_label="promote", delta_market=-0.001)],
            },
            {"schema_version": "promotion_refresh_v0.1", "decisions": {"markets": [_promotion_decision("atlanta", action="PROMOTE_CANDIDATE", delta_market=-0.001)]}},
            [{"market": "atlanta", "trust_score": 43, "grade": "Low", "model_ece": 0.02}],
            {"hourly_performance_gate": {"blockers": [{"gate": "early_hour_brier_regression", "detail": "early hour gap"}]}},
            {"run_summary_count": 1, "markets": {"atlanta": {"run_count": 1, "pass_rate": 1.0, "latest": {"target_date": "2026-06-19", "status": "PASS", "preflight_status": "PASS"}}}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_markdown_report(Path(tmp) / "audit.md", payload)
            text = path.read_text(encoding="utf-8")

        self.assertIn("Per-Location Audit", text)
        self.assertIn("Cross-Hub Comparison", text)
        self.assertIn("Transfer Lessons", text)
        self.assertIn("Run/Log Evidence", text)
        self.assertIn("early_hour_brier_regression", text)


if __name__ == "__main__":
    unittest.main()
