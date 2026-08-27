from __future__ import annotations

import json

import pytest

from weather.market import portable_live_candidate_preflight as preflight
from weather.operations.live_path_security import LivePathSecurityError


TARGET_DATE = "2026-08-27"
MARKET = "toronto"
CONDITION = "0x" + "1" * 64


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fixture(tmp_path, monkeypatch):
    config = preflight.config_for_date(TARGET_DATE, MARKET)
    snapshots_root = tmp_path / "snapshots"
    folder = snapshots_root / config.event_slug
    folder.mkdir(parents=True)
    event_metadata = _write_json(tmp_path / "events.json", {"locations": []})
    validation = _write_json(tmp_path / "validation.json", {
        "schema_version": preflight.event_metadata_validation.SCHEMA_VERSION,
        "generated_at_utc": "2026-08-27T12:00:00+00:00",
        "target_date": TARGET_DATE,
        "markets": [MARKET],
        "event_metadata_path": str(event_metadata),
        "validation_hash": "a" * 64,
    })
    observation = _write_json(tmp_path / "observation.json", {
        "markets": {
            MARKET: {
                "last_observation": {
                    "market_id": MARKET,
                    "target_date": TARGET_DATE,
                    "event_slug": config.event_slug,
                }
            }
        }
    })
    economics = _write_json(tmp_path / "economics.json", {
        "markets": [{
            "location_id": MARKET,
            "event_date": TARGET_DATE,
            "condition_id": CONDITION,
            "token_ids": ["101", "102"],
        }]
    })
    accepted = _write_json(tmp_path / "accepted.json", {})
    drift = _write_json(tmp_path / "drift.json", {})
    paper_config = _write_json(tmp_path / "run-config.json", {
        "snapshots_root": str(snapshots_root),
        "observation_status_path": str(observation),
        "markets": [MARKET],
        "target_date": TARGET_DATE,
        "permission_profile": "market_harvest",
        "mode": "paper-live-forward",
    })
    paper_gate = _write_json(tmp_path / "paper-preflight.json", {
        "status": "PASS",
        "markets": [{
            "market_id": MARKET,
            "target_date": TARGET_DATE,
            "event_slug": config.event_slug,
            "folder": str(folder),
            "gates": [{"name": "example", "ok": True}],
        }],
    })
    quotes = tmp_path / "quotes.csv"
    quotes.write_text("header\n", encoding="utf-8")
    for name in (
        "clob_tokens.csv",
        "order_books_summary.csv",
        "source_status_long.csv",
    ):
        (folder / name).write_text("header\n", encoding="utf-8")

    monkeypatch.setattr(preflight, "_validation_content_is_intact", lambda *_args: True)
    monkeypatch.setattr(preflight, "_metadata_matches_validation", lambda *_args, **_kwargs: True)

    monkeypatch.setattr(
        preflight.event_metadata_validation,
        "gate_for_market",
        lambda *_args: {"ok": True, "event_slug": config.event_slug},
    )
    monkeypatch.setattr(preflight, "_latest_token_rows", lambda _folder: [
        {
            "captured_at_utc": "2026-08-27T12:00:00+00:00",
            "condition_id": CONDITION,
            "clob_token_id": "101",
            "outcome": "yes",
            "active": True,
            "closed": False,
        },
        {
            "captured_at_utc": "2026-08-27T12:00:00+00:00",
            "condition_id": CONDITION,
            "clob_token_id": "102",
            "outcome": "yes",
            "active": True,
            "closed": False,
        },
    ])
    monkeypatch.setattr(preflight, "source_status_for_snapshot", lambda *_args: [
        {
            "ok": True,
            "status": "fresh",
            "snapshot_id": "snapshot-1",
            "captured_at_utc": "2026-08-27T12:00:00+00:00",
        }
    ])
    monkeypatch.setattr(
        preflight,
        "source_status_degradation_preflight",
        lambda *_args: {
            "ok": True,
            "snapshot_matches": True,
            "trading_evidence_allowed": True,
        },
    )
    monkeypatch.setattr(preflight, "latest_book_rows", lambda *_args: [{"book": True}])
    monkeypatch.setattr(preflight, "preflight_book_audit", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(
        preflight,
        "market_harvest_clob_feature_rows",
        lambda *_args, **_kwargs: [{"feature": True}],
    )
    monkeypatch.setattr(
        preflight,
        "load_observation_status",
        lambda *_args, **_kwargs: {"fresh": True},
    )
    monkeypatch.setattr(
        preflight,
        "load_exchange_economics_gate",
        lambda *_args, **_kwargs: {
            "ok": True,
            "snapshot_id": "economics-1",
            "exchange_economics_hash": "economics-hash",
        },
    )
    monkeypatch.setattr(
        preflight,
        "load_economics_acceptance_evidence",
        lambda *_args, **_kwargs: {
            "drift_status": "PASS",
            "accepted_snapshot_file_sha256": "accepted-hash",
            "drift_report_file_sha256": "drift-hash",
        },
    )
    monkeypatch.setattr(
        preflight,
        "_load_paper_quote_evidence",
        lambda *_args, **_kwargs: {
            "market_id": MARKET,
            "qualifying": {(CONDITION, "101"): {}},
            "quote_intents_sha256": "quotes-hash",
            "quote_intents_row_count": 1,
        },
    )
    return {
        "market_id": MARKET,
        "target_date": TARGET_DATE,
        "event_metadata_path": event_metadata,
        "event_metadata_validation_path": validation,
        "snapshots_root": snapshots_root,
        "observation_status_path": observation,
        "economics_snapshot_path": economics,
        "accepted_economics_snapshot_path": accepted,
        "economics_drift_report_path": drift,
        "paper_run_config_path": paper_config,
        "paper_preflight_path": paper_gate,
        "paper_quote_intents_path": quotes,
        "now": "2026-08-27T12:01:00+00:00",
    }


def test_preflight_passes_exact_isolated_public_substrate(tmp_path, monkeypatch):
    payload = preflight.build_preflight(**_fixture(tmp_path, monkeypatch))

    assert payload["status"] == "PASS"
    assert payload["blockers"] == []
    assert payload["credential_access"] is False
    assert payload["exchange_contact"] is False
    assert payload["network_access"] is False


def test_preflight_blocks_paper_run_bound_to_another_snapshot_root(
    tmp_path,
    monkeypatch,
):
    inputs = _fixture(tmp_path, monkeypatch)
    config_path = inputs["paper_run_config_path"]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["snapshots_root"] = str(tmp_path / "other-snapshots")
    config_path.write_text(json.dumps(config), encoding="utf-8")

    payload = preflight.build_preflight(**inputs)

    assert payload["status"] == "BLOCK"
    assert "paper_config_snapshot_root" in payload["blockers"]


def test_preflight_rejects_redirected_snapshot_root(tmp_path, monkeypatch):
    inputs = _fixture(tmp_path, monkeypatch)
    redirected = tmp_path / "redirected-snapshots"
    try:
        redirected.symlink_to(inputs["snapshots_root"], target_is_directory=True)
    except OSError:
        pytest.skip("this Windows account cannot create a directory symlink")
    inputs["snapshots_root"] = redirected

    with pytest.raises(LivePathSecurityError, match="redirected"):
        preflight.build_preflight(**inputs)
