"""Invalid timestamps and old research cannot silently qualify paper quotes."""

import json

import pytest

from tests.market.test_mm_policy import NOW, fresh_row
from weather.market.clob_recon import policy_overrides_from_recon
from weather.market.mm_policy import config_with_clob_recon, decide_quote, load_observation_status
from weather.time import evidence_age_seconds, parse_datetime


@pytest.mark.parametrize("overrides,reason", [
    ({"captured_at_utc": "2027-06-14T15:59:30+00:00"}, "NO_QUOTE_STALE_MODEL"),
    ({"captured_at_utc": "2027-06-14T15:59:30+00:00", "model_age_seconds": 0}, "NO_QUOTE_STALE_MODEL"),
    ({"model_age_seconds": -1}, "NO_QUOTE_STALE_MODEL"),
    ({"model_age_seconds": 0}, "NO_QUOTE_STALE_MODEL"),
    ({"clob_book_age_seconds": -3600}, "NO_QUOTE_STALE_BOOK"),
    ({"book_age_seconds": 20, "clob_book_age_seconds": 9999}, "NO_QUOTE_STALE_BOOK"),
    ({"clob_book_age_seconds": True}, "NO_QUOTE_STALE_BOOK"),
    ({"clob_book_captured_at_utc": "2027-06-14T15:59:30+00:00"}, "NO_QUOTE_STALE_BOOK"),
    ({"watcher_age_seconds": -3600}, "NO_QUOTE_STALE_WATCHER"),
    ({"watcher_age_seconds": float("inf")}, "NO_QUOTE_STALE_WATCHER"),
    ({"watcher_last_heartbeat": "invalid"}, "NO_QUOTE_STALE_WATCHER"),
])
def test_invalid_evidence_produces_a_named_no_quote(overrides, reason):
    quote = decide_quote(fresh_row(**overrides), now=NOW)
    assert quote["quote_permission"] is False
    assert quote["live_trade_permission"] is False
    assert quote["reason_code"] == reason


def test_rounding_tolerance_does_not_understate_age():
    assert evidence_age_seconds(parse_datetime(NOW), timestamp="2026-06-14T15:59:30+00:00",
                                reported_age=29.5) == 30.0
    assert evidence_age_seconds(parse_datetime(NOW), timestamp="2026-06-14T16:00:01+00:00") is None
    assert evidence_age_seconds(parse_datetime(NOW), timestamp="2026-06-14T16:00:01+00:00",
                                clock_skew_seconds=1.0) == 0.0
    assert decide_quote(fresh_row(model_age_seconds=30.0), now=NOW)["quote_permission"] is True


def test_captured_book_age_advances_from_its_own_observation_time():
    row = fresh_row(clob_book_age_seconds=10.0,
                    clob_book_captured_at_utc="2026-06-14T15:59:20+00:00",
                    book_age_observed_at_utc="2026-06-14T15:59:30+00:00")
    quote = decide_quote(row, now=NOW)
    assert quote["quote_permission"] is True
    assert quote["book_age_seconds"] == 40.0
    # A once-fresh book ages out even if its captured numeric age stays at ten.
    assert decide_quote(row, now="2026-06-14T16:02:00+00:00")["reason_code"] == "NO_QUOTE_STALE_BOOK"


def test_future_watcher_is_not_fresh(tmp_path):
    path = tmp_path / "watcher.json"
    path.write_text(json.dumps({"last_heartbeat": "2027-06-14T16:00:00+00:00"}), encoding="utf-8")
    assert load_observation_status(path, now=NOW)["heartbeat_ok"] is False


def test_book_refresh_does_not_renew_model_evidence(monkeypatch, tmp_path):
    from weather.market import mm_policy
    model = fresh_row(captured_at_utc="2026-06-14T12:00:00+00:00", snapshot_id="older-model")
    model["model_probability"] = model["fair_probability"]
    book = {**model, "captured_at_utc": "2026-06-14T15:59:30+00:00", "snapshot_id": "newer-book"}
    monkeypatch.setattr(mm_policy, "latest_folders_by_market", lambda *a, **kw: {"atlanta": tmp_path})
    monkeypatch.setattr(mm_policy, "load_latest_snapshot_rows", lambda *a: [model])
    monkeypatch.setattr(mm_policy, "load_source_status_rows", lambda *a: [])
    monkeypatch.setattr(mm_policy, "load_clob_feature_index", lambda *a: ({mm_policy._band_key(model): book}, {}))
    rows = mm_policy.assemble_policy_inputs({"atlanta": {"promotion_state": "SHADOW"}},
                                          {"watcher_age_seconds": 10, "heartbeat_ok": True, "fresh": True}, now=NOW)
    assert rows[0]["captured_at_utc"] == model["captured_at_utc"]
    assert rows[0]["snapshot_id"] == "older-model"
    assert rows[0]["book_age_observed_at_utc"] == book["captured_at_utc"]
    assert decide_quote(rows[0], now=NOW)["reason_code"] == "NO_QUOTE_STALE_MODEL"


def test_historical_research_never_overrides_policy_by_default(tmp_path):
    path = tmp_path / "recon.json"
    path.write_text(json.dumps({"schema_version": "clob_book_recon_v0.1",
                                "generated_at_utc": "2020-01-01T00:00:00+00:00",
                                "policy_parameter_suggestions": {"quote_size": 25}}), encoding="utf-8")
    config, diag = config_with_clob_recon({"clob_recon_path": str(path), "quote_size": 5.0})
    assert config["quote_size"] == 5.0
    assert diag["enabled"] is False
    assert policy_overrides_from_recon(path)[0] == {}


@pytest.mark.parametrize("payload", [
    {"schema_version": "unknown", "policy_parameter_suggestions": {"quote_size": 25}},
    {"schema_version": "clob_book_recon_v0.1", "policy_parameter_suggestions": {"quote_size": -1}},
    {"schema_version": "clob_book_recon_v0.1", "policy_parameter_suggestions": {"harvest_half_spread": 0.5}},
    {"schema_version": "clob_book_recon_v0.1", "policy_parameter_suggestions": [25]},
    ["not a report"],
])
def test_explicit_research_opt_in_still_rejects_bad_schema_or_parameters(tmp_path, payload):
    path = tmp_path / "recon.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    overrides, diag = policy_overrides_from_recon(path, enabled=True)
    assert overrides == {}
    assert diag["research_only"] is True
    assert diag["current_scope_verified"] is False
