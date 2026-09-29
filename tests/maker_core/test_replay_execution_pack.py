from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import authorization, pack_cli
from maker_core.replay.__main__ import main
from maker_core.replay.bundle import BundleError, sha256
from maker_core.replay.engine import replay, ReplayConfig
from maker_core.replay.execution_manifest import apply_manifest, verify_manifest
from maker_core.replay.execution_receipt import reserve_attempt, evaluate_hurdles
from .fixtures.execution_pack import pack

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def test_all_bindings_verify_before_scoring_day_without_enrollment(tmp_path, monkeypatch):
    doc, bundles, cb, paths, manifest, key = pack(tmp_path)
    monkeypatch.setattr(authorization, "APPROVED_REGISTRATIONS", {})
    before_look = datetime(2026, 10, 15, 1, tzinfo=timezone.utc)  # Oct 14 Toronto.
    assert verify_manifest(doc, bundles, cb, **paths, now=before_look) == doc
    with pytest.raises(BundleError, match="not_approved"):
        authorization.read_authorization(manifest, key)


@pytest.mark.parametrize("field", ["replay_config", "source_hashes", "active_intervals", "input_hashes",
                                   "universe", "calibration", "ceilings", "hurdles"])
def test_missing_binding_refuses(tmp_path, field):
    doc, bundles, cb, paths, _, _ = pack(tmp_path)
    del doc[field]
    with pytest.raises((BundleError, KeyError)):
        verify_manifest(doc, bundles, cb, **paths, now=NOW)


def test_modified_config_stream_source_and_calibration_refuse(tmp_path):
    doc, bundles, cb, paths, _, _ = pack(tmp_path)
    for field, value in (("order_cap", "61"), ("hazard_per_minute", 0), ("max_events", 499999)):
        changed = deepcopy(doc)
        changed["replay_config"][field] = value
        with pytest.raises(BundleError, match="binding_mismatch"):
            verify_manifest(changed, bundles, cb, **paths, now=NOW)
    changed = deepcopy(doc)
    changed["source_hashes"][next(iter(changed["source_hashes"]))] = "0"*64
    with pytest.raises(BundleError, match="binding_mismatch"):
        verify_manifest(changed, bundles, cb, **paths, now=NOW)
    changed_bundle = replace(bundles[0], input_hashes={"bundle.json": "0"*64})
    with pytest.raises(BundleError, match="binding_mismatch"):
        verify_manifest(doc, (changed_bundle, *bundles[1:]), cb, **paths, now=NOW)
    value = json.loads(paths["calibration_path"].read_bytes())
    value["hazard_per_minute"] = "0.000000000000"
    paths["calibration_path"].write_bytes(canonical_bytes(value))
    with pytest.raises(BundleError, match="calibration_recomputation"):
        verify_manifest(doc, bundles, cb, **paths, now=NOW)


def test_maintenance_is_inactive_and_settlement_date_never_quotes(tmp_path):
    doc, bundles, _, _, _, _ = pack(tmp_path)
    projected = apply_manifest(doc, bundles)
    assert projected[-1].active_intervals == ()
    windows = projected[0].active_intervals
    assert len(windows) == 2 and windows[0][2].hour == 5 and windows[1][1].hour == 8
    result = replay(projected, ReplayConfig(policy="no_quote"))
    assert all(not (5 <= s.start.hour < 8) for s in result.spans if s.evaluation_active)
    assert all(s.start.date() != bundles[-1].day for s in result.spans if s.evaluation_active)


def test_optional_clarification_enrollment_tamper_and_revoked_old_id(tmp_path, monkeypatch):
    doc, _, _, paths, manifest, key = pack(tmp_path)
    ap = {k: paths[k] for k in ("decision_log", "frozen_protocol", "execution_addendum", "clarification")}
    monkeypatch.setattr(authorization, "_utc_now", lambda: NOW)
    monkeypatch.setitem(authorization.APPROVED_REGISTRATIONS, key, "michaelbooth1")
    assert authorization.read_authorization(manifest, key, **ap) == doc
    with pytest.raises(BundleError, match="clarification_path_required"):
        authorization.read_authorization(manifest, key, **{k: v for k, v in ap.items() if k != "clarification"})
    manifest.write_bytes(manifest.read_bytes()+b"\n")
    with pytest.raises(BundleError, match="hash_mismatch"):
        authorization.read_authorization(manifest, key, **ap)
    manifest.write_bytes(canonical_bytes(doc))
    log = paths["decision_log"]
    log.write_text(log.read_text(encoding="utf8")+ '| 2026-09-27 | REVOKE_MAKER_REPLAY | offline replay only | `{"authorization_id":"maker-replay-2026-10-12-v1"}` | — |\n', encoding="utf8")
    assert authorization.read_authorization(manifest, key, **ap) == doc
    log.write_text(log.read_text(encoding="utf8")+ '| 2026-09-27 | REVOKE_MAKER_REPLAY | offline replay only | `{"authorization_id":"maker-replay-2026-10-15-v1"}` | — |\n', encoding="utf8")
    with pytest.raises(BundleError, match="revoked"):
        authorization.read_authorization(manifest, key, **ap)


def test_cli_preflight_create_only_and_hash_refusal(tmp_path, monkeypatch):
    doc, bundles, cb, paths, manifest, key = pack(tmp_path)
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    args = ["manifest", "verify", "--manifest", str(manifest), "--manifest-sha256", key]
    for b in bundles:
        args += ["--bundle", str(tmp_path/"panel"/b.day.isoformat())]
    for b in cb:
        args += ["--calibration-bundle", str(tmp_path/"calibration-bundles"/b.day.isoformat())]
    flags = dict(calibration_path="calibration", inventory_path="universe", quote_inventory_path="quote-markets")
    for k, p in paths.items():
        args += ["--"+flags.get(k, k.replace("_", "-")), str(p)]
    assert main(args) == 0
    args[args.index(key)] = "0"*64
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_partial_scored_attempt_is_consumed_across_output_directories(tmp_path):
    doc, _, _, _, manifest, key = pack(tmp_path)
    attempt = reserve_attempt(manifest, doc, key, NOW)
    assert json.loads(attempt.read_bytes())["status"] == "CONSUMED_BEFORE_POLICY"
    # No result has to exist for the authorization to be spent.
    assert not attempt.with_suffix(".completed.json").exists()
    with pytest.raises(BundleError, match="already_consumed"):
        reserve_attempt(manifest, doc, key, NOW)


def test_hurdle_conjunction_and_equality_fail_closed():
    estimate = dict(status="OK", date_clusters=14, market_clusters=12, valid_replicates=2000, interval=[1, 3])
    value = dict(intervals={p+":"+m: dict(intervals={c: deepcopy(estimate) for c in ("date", "date_x_market")})
        for p in ("blind_re1", "no_quote", "clock_only") for m in ("modeled_net_k1", "modeled_net_k05")},
        scores={"fixture": True}, traces={"fixture": True}, pull_efficiency=dict(status="HURDLE_MET"))
    report = dict(bounds={b: deepcopy(value) for b in ("strictly_through", "at_price")})
    assert evaluate_hurdles(report)["status"] == "REPLAY_HURDLES_MET"
    e = report["bounds"]["strictly_through"]["intervals"]["no_quote:modeled_net_k1"]["intervals"]["date_x_market"]
    e["interval"][0] = 0
    assert evaluate_hurdles(report)["status"] == "HURDLE_NOT_MET"
    e["market_clusters"] = 9
    assert evaluate_hurdles(report)["status"] == "UNDERPOWERED"
    del report["bounds"]["at_price"]
    assert evaluate_hurdles(report)["status"] == "BLOCKED"


def test_target_after_settlement_date_is_excluded_without_dropping_inventory(tmp_path):
    from maker_core.replay.execution_manifest import active_intervals
    doc, bundles, _, _, _, _ = pack(tmp_path)
    bundle = bundles[-2]
    descriptor = next(r for r in bundle.records if r.kind == "descriptor")
    # Use plain JSON conversion because the loaded nested mappings are immutable.
    payload = json.loads(canonical_bytes(descriptor.payload))
    payload["horizon_days"] = 2
    payload["market"]["close_at_utc"] = "2026-10-16T00:00:00+00:00"
    payload["market"]["settle_at_utc"] = "2026-10-16T00:01:00+00:00"
    revised = replace(descriptor, payload=payload)
    changed = replace(bundle, records=tuple(revised if r is descriptor else r for r in bundle.records))
    universe = deepcopy(doc["universe"])
    next(r for r in universe if r["condition_id"] == descriptor.condition_id)["target_date"] = "2026-10-15"
    windows, exclusions = active_intervals((*bundles[:-2], changed, bundles[-1]), universe)
    assert not any(w["condition_id"] == descriptor.condition_id for w in windows)
    assert any(e["condition_id"] == descriptor.condition_id and e["reason"] == "target_after_settlement_only" for e in exclusions)
    assert len(universe) == len(doc["universe"])


def test_scoring_cli_verifies_then_consumes_before_failed_policy_call(tmp_path, monkeypatch):
    import maker_core.replay.__main__ as cli
    doc, bundles, cb, paths, manifest, key = pack(tmp_path)
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    monkeypatch.setattr(authorization, "_utc_now", lambda: NOW)
    monkeypatch.setitem(authorization.APPROVED_REGISTRATIONS, key, "michaelbooth1")
    args = ["run", "--compare", "--pre-registration", str(manifest), "--pre-registration-sha256", key,
            "--out", str(tmp_path/"result")]
    for b in bundles:
        args += ["--bundle", str(tmp_path/"panel"/b.day.isoformat())]
    for b in cb:
        args += ["--calibration-bundle", str(tmp_path/"calibration-bundles"/b.day.isoformat())]
    flags = dict(calibration_path="calibration", inventory_path="universe", quote_inventory_path="quote-markets")
    for k, p in paths.items():
        args += ["--"+flags.get(k, k.replace("_", "-")), str(p)]
    called = []
    def fail(*a, **k):
        called.append(True)
        assert (tmp_path/"attempts"/(doc["owner_decision"]["authorization_id"]+".json")).exists()
        raise BundleError("fixture_failure_after_consumption")
    monkeypatch.setattr(cli, "comparison_report", fail)
    for _ in range(2):
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 2
    assert called == [True]
    assert not (tmp_path/"result").exists()
