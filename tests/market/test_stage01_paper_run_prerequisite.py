"""The International live-pilot Stage 0/1 paper-run prerequisite still runs.

Owner decision 2026-09-29 (110o part 3): the paper-run tool is retained until the
informed maker's own live procedure exists. This test runs the runbook's strict
paper market-harvest tick (docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md,
prerequisite 7 and the attempt-local public-substrate sequence) through the real
CLI on fixtures, then feeds its run folder to the exact loader that
``mm_live_candidate_cli`` and ``portable_live_candidate_preflight`` use.

Guards: DECISION_LOG 2026-09-29 (110o part 3 keeps the Stage 0/1 paper-run tool) - the only documented
attended path to a live start (INTERNATIONAL_MM_LIVE_PILOT.md prerequisite 7) must still produce a
PASS paper run whose folder the live-candidate loader accepts.
"""

import json
from pathlib import Path

from tests.market.test_market_making_run import (
    NOW,
    TARGET_DATE,
    write_market_fixture,
    write_observation_status,
)
from weather.market import exchange_economics, market_making_run
from weather.market.execution_contract import SCHEMA_VERSION as RUN_SCHEMA_VERSION
from weather.market.mm_live_candidate_cli import load_paper_quote_evidence

EVENT_SLUG = "highest-temperature-in-atlanta-on-june-14-2026"
TOKENS = {"token-80": "80000000000000000001", "token-82": "82000000000000000001"}
CONDITIONS = {"condition-80": "0x" + "a" * 64, "condition-82": "0x" + "b" * 64}


def _public_substrate(root: Path):
    snapshots_root, _promotion = write_market_fixture(root)
    folder = snapshots_root / EVENT_SLUG
    # Live CLOB identities are numeric token ids and 32-byte condition ids.
    for path in folder.iterdir():
        text = path.read_text(encoding="utf-8")
        for old, new in {**TOKENS, **CONDITIONS}.items():
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
    # market_harvest never uses model snapshot rows or prebuilt features.
    (folder / "snapshots_long.csv").unlink()
    (folder / "clob_features_long.csv").unlink()
    observation = root / "observation_status.json"
    write_observation_status(observation)
    validation = root / "event_metadata_validation.json"
    validation.write_text(json.dumps({
        "target_date": TARGET_DATE,
        "status": "PASS",
        "validation_hash": "fixture-validation-hash",
        "market_rows": [{"market_id": "atlanta", "ok": True, "status": "PASS"}],
    }), encoding="utf-8")
    economics = root / "exchange_economics_snapshot.json"
    exchange_economics.write_json(economics, exchange_economics.build_snapshot_payload(
        target_date=TARGET_DATE,
        verified_at_utc="2026-06-14T15:55:00+00:00",
        token_ids=list(TOKENS.values()),
    ))
    return snapshots_root, observation, validation, economics


def test_strict_market_harvest_paper_tick_feeds_the_live_candidate_loader(tmp_path, capsys):
    snapshots_root, observation, validation, economics = _public_substrate(tmp_path)
    runs_root = tmp_path / "paper-runs"
    run_id = "stage01-paper-proof"

    # Runbook: --date --budget-usdc 25 --mode paper-live-forward
    # --permission-profile market_harvest --markets --snapshots-root
    # --observation-status --event-metadata-validation
    # --exchange-economics-snapshot --runs-root --run-id --config --once
    # --require-preflight-pass. The remaining paths are pinned under tmp_path so
    # no default data/ artifact is read.
    payload = market_making_run.main([
        "--date", TARGET_DATE,
        "--budget-usdc", "25",
        "--mode", "paper-live-forward",
        "--permission-profile", "market_harvest",
        "--markets", "atlanta",
        "--snapshots-root", str(snapshots_root),
        "--observation-status", str(observation),
        "--event-metadata-validation", str(validation),
        "--exchange-economics-snapshot", str(economics),
        "--runs-root", str(runs_root),
        "--run-id", run_id,
        "--config", "quote_ttl_seconds=600",
        "--once",
        "--require-preflight-pass",
        "--now", NOW,
        "--promotion-refresh", str(tmp_path / "absent-promotion.json"),
        "--known-edge-map", str(tmp_path / "absent-known-edge.json"),
        "--data-layer-audit", str(tmp_path / "absent-data-layer-audit.json"),
        "--platform-verification", str(tmp_path / "absent-platform-verification.json"),
    ])
    capsys.readouterr()

    run_folder = runs_root / TARGET_DATE / run_id
    assert Path(payload["run_folder"]) == run_folder
    assert payload["preflight_status"] == "PASS"
    assert payload["quote_permission_rows"] >= 1
    assert payload["live_trade_permission_rows"] == 0
    # The three files the runbook hands to portable_live_candidate_preflight.
    for name in ("run_config.json", "preflight.json", "quote_intents_long.csv"):
        assert (run_folder / name).is_file(), name
    config = json.loads((run_folder / "run_config.json").read_text(encoding="utf-8"))
    preflight = json.loads((run_folder / "preflight.json").read_text(encoding="utf-8"))
    assert config["schema_version"] == RUN_SCHEMA_VERSION
    assert config["permission_profile"] == "market_harvest"
    assert config["mode"] == "paper-live-forward"
    assert config["policy_config"]["quote_ttl_seconds"] == 600.0
    assert preflight["status"] == "PASS"

    evidence = load_paper_quote_evidence(
        run_folder / "run_config.json",
        run_folder / "quote_intents_long.csv",
        target_date=TARGET_DATE,
        economics_snapshot_id=config["exchange_economics_snapshot_id"],
        economics_hash=config["exchange_economics_hash"],
        now=NOW,
    )
    assert evidence["market_id"] == "atlanta"
    assert evidence["run_id"] == run_id
    assert evidence["qualifying"]
    for binding in evidence["qualifying"].values():
        assert binding["token_id"] in TOKENS.values()
        assert binding["condition_id"] in CONDITIONS.values()
        assert binding["live_trade_permission"] is False
        assert binding["quote_ttl_seconds"] == 600.0
