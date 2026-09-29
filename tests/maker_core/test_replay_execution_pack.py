from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import authorization, ceilings, pack_cli
from maker_core.replay.__main__ import main
from maker_core.replay.bundle import BundleError, sha256
from maker_core.replay.engine import replay, ReplayConfig
from maker_core.replay.execution_manifest import apply_manifest, verify_manifest
from maker_core.replay.execution_receipt import reserve_attempt, evaluate_hurdles
from .fixtures.execution_pack import MEASURED, measurement, pack, per_date

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
FLAGS = dict(calibration_path="calibration", inventory_path="universe", quote_inventory_path="quote-markets",
             measurement_path="ceiling-measurement")


@pytest.fixture(autouse=True)
def small_process(monkeypatch):
    # The pytest process itself exceeds the fixture's memory ceiling; the guard is tested separately.
    monkeypatch.setattr(ceilings, "process_memory", lambda: (1, 1))


def binding_args(tmp_path, bundles, cb, paths):
    args = []
    for b in bundles:
        args += ["--bundle", str(tmp_path/"panel"/b.day.isoformat())]
    for b in cb:
        args += ["--calibration-bundle", str(tmp_path/"calibration-bundles"/b.day.isoformat())]
    for k, p in paths.items():
        args += ["--"+FLAGS.get(k, k.replace("_", "-")), str(p)]
    return args


def scored(tmp_path, monkeypatch, *, now=NOW, commit=10.0):
    doc, bundles, cb, paths, manifest, key = pack(tmp_path)
    monkeypatch.setattr(pack_cli, "_now", lambda: now)
    monkeypatch.setattr(authorization, "_utc_now", lambda: now)
    monkeypatch.setattr(ceilings, "commit_percent", lambda: commit)
    monkeypatch.setitem(authorization.APPROVED_REGISTRATIONS, key, "michaelbooth1")
    args = ["run", "--compare", "--pre-registration", str(manifest), "--pre-registration-sha256", key,
            "--out", str(tmp_path/"result")] + binding_args(tmp_path, bundles, cb, paths)
    return doc, args, tmp_path/"attempts"


def test_all_bindings_verify_before_scoring_day_without_enrollment(tmp_path, monkeypatch):
    doc, bundles, cb, paths, manifest, key = pack(tmp_path)
    monkeypatch.setattr(authorization, "APPROVED_REGISTRATIONS", {})
    before_look = datetime(2026, 10, 15, 1, tzinfo=timezone.utc)  # Oct 14 Toronto.
    assert verify_manifest(doc, bundles, cb, **paths, now=before_look) == doc
    assert doc["format"] == "maker_core.replay.execution.v2"
    assert doc["owner_decision"]["authorization_id"] == "maker-replay-2026-10-15-v2"
    with pytest.raises(BundleError, match="not_approved"):
        authorization.read_authorization(manifest, key)


@pytest.mark.parametrize("field", ["replay_config", "source_hashes", "active_intervals", "input_hashes",
                                   "universe", "calibration", "ceilings", "hurdles", "ceiling_measurement"])
def test_missing_binding_refuses(tmp_path, field):
    doc, bundles, cb, paths, _, _ = pack(tmp_path)
    del doc[field]
    with pytest.raises((BundleError, KeyError)):
        verify_manifest(doc, bundles, cb, **paths, now=NOW)


def test_modified_config_stream_source_and_calibration_refuse(tmp_path):
    doc, bundles, cb, paths, _, _ = pack(tmp_path)
    for field, value in (("order_cap", "61"), ("hazard_per_minute", 0), ("max_events", 499999), ("max_outputs", 7)):
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


def test_ceilings_follow_the_rule_and_bind_engine_and_cli(tmp_path):
    doc, _, _, _, _, _ = pack(tmp_path)
    # Largest date x 15 x 2, next power of two; memory adds the unmultiplied baseline.
    assert doc["ceilings"] == dict(max_input_bytes=2**29, max_records=2**20, max_seconds=32.0,
                                   max_output_bytes=4*1024**2, max_memory_bytes=2**30 + 100*1024**2)
    assert (doc["replay_config"]["max_events"], doc["replay_config"]["max_outputs"]) == (2**21, 2**21)
    assert doc["ceiling_measurement"]["per_date"]["2026-09-27"] == MEASURED
    assert doc["ceiling_measurement"]["derived"]["largest"] == MEASURED
    assert ceilings.next_power_of_two(1.0*30) == 32 and ceilings.next_power_of_two(64) == 64
    assert ceilings.next_power_of_two(65) == 128 and ceilings.next_power_of_two(0.2) == 1


@pytest.mark.parametrize("field, value, binding", [
    ("runtime_seconds", 481.0, "runtime_seconds"),                      # 14,430 s -> 16,384 s > 4 h
    ("peak_memory_above_baseline_bytes", 400*1024**2, "memory_bytes"),  # 16 GiB + baseline > 70% of 16 GiB
    ("input_bytes", 400*1024**2, "input_bytes")])
def test_binding_host_limit_is_not_executable_never_truncated(field, value, binding):
    derived = ceilings.derive(per_date(dict(MEASURED, **{field: value})))
    assert derived["executable"] is False and derived["host_limit_binding"] == [binding]
    with pytest.raises(BundleError, match="not_executable_on_host:"+binding):
        ceilings.run_limits(derived)


def test_baseline_is_added_not_multiplied():
    derived = ceilings.derive(per_date(dict(MEASURED, baseline_memory_bytes=2*1024**3)))
    assert derived["ceilings"]["memory_bytes"] == 2**30 + 2*1024**3 and derived["executable"]
    with pytest.raises(BundleError, match="incomplete"):
        ceilings.derive({"2026-09-27": MEASURED})


def test_manifest_refuses_unexecutable_or_rederived_measurement(tmp_path):
    (tmp_path/"a").mkdir()
    (tmp_path/"b").mkdir()
    with pytest.raises(BundleError, match="not_executable_on_host"):
        pack(tmp_path/"a", measured=dict(MEASURED, runtime_seconds=481.0))
    doc, bundles, cb, paths, _, _ = pack(tmp_path/"b")
    value = measurement()
    value["derived"]["ceilings"]["runtime_seconds"] = 2048
    paths["measurement_path"].write_bytes(canonical_bytes(value))
    with pytest.raises(BundleError, match="ceiling_derivation_mismatch"):
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


def test_quote_markets_are_the_rule_not_a_hand_list(tmp_path):
    doc, bundles, cb, paths, _, _ = pack(tmp_path)
    value = json.loads(paths["calibration_path"].read_bytes())
    value["quote_markets"] = ["a", "b"]
    paths["calibration_path"].write_bytes(canonical_bytes(value))
    paths["quote_inventory_path"].write_bytes(canonical_bytes(["a", "b"]))
    with pytest.raises(BundleError, match="quote_markets_rule_mismatch"):
        verify_manifest(doc, bundles, cb, **paths, now=NOW)


def test_quote_market_and_calibration_cli_use_the_rule(tmp_path, monkeypatch, capsys):
    _, _, cb, _, _, _ = pack(tmp_path)
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    cal = ["--calibration-bundle" if i % 2 == 0 else str(tmp_path/"calibration-bundles"/b.day.isoformat())
           for b in cb for i in range(2)]
    assert main(["quote_markets", *cal, "--out", str(tmp_path/"rule.json")]) == 0
    assert json.loads((tmp_path/"rule.json").read_bytes()) == ["a"]
    hand = tmp_path/"hand.json"
    hand.write_bytes(canonical_bytes(["a", "zz"]))
    bundle_args = [a.replace("--calibration-bundle", "--bundle") for a in cal]
    with pytest.raises(SystemExit):
        main(["calibrate_hazard", *bundle_args, "--quote-markets", str(hand), "--out", str(tmp_path/"c.json")])
    assert "quote_markets_rule_mismatch" in capsys.readouterr().err
    assert not (tmp_path/"c.json").exists()


def test_v1_rows_still_verify_and_v2_requires_clarification_2(tmp_path, monkeypatch):
    doc, _, _, paths, manifest, key = pack(tmp_path)
    ap = {k: paths[k] for k in ("decision_log", "frozen_protocol", "execution_addendum", "clarification",
                                "clarification_2")}
    monkeypatch.setattr(authorization, "_utc_now", lambda: NOW)
    monkeypatch.setitem(authorization.APPROVED_REGISTRATIONS, key, "michaelbooth1")
    assert authorization.read_authorization(manifest, key, **ap) == doc
    with pytest.raises(BundleError, match="clarification_2_path_required"):
        authorization.read_authorization(manifest, key, **{k: v for k, v in ap.items() if k != "clarification_2"})
    # A v1 attestation (one clarification) still verifies against its own row.
    v1 = {k: v for k, v in doc["owner_decision"].items() if k != "clarification_2_sha256"}
    v1.update(authorization_id="maker-replay-2026-10-15-v1", signed_at="2026-09-27T00:00:00Z",
              expires_at="2026-10-16T04:00:00Z")
    log = paths["decision_log"]
    log.write_text(log.read_text(encoding="utf8").rstrip("\n") + "\n| 2026-09-27 | APPROVE_MAKER_REPLAY | offline replay only | `"
                   + json.dumps(v1) + "` | — |\n", encoding="utf8")
    v1_doc = dict(owner="michaelbooth1", signed_at=v1["signed_at"], owner_decision=v1)
    from maker_core.replay.bundle import Limits, _Reader
    import time
    reader = _Reader(Limits(8*1024**2, 1, 5), time.monotonic)
    authorization._verify_decision(v1_doc, reader, log, paths["frozen_protocol"], paths["execution_addendum"],
                                   NOW, paths["clarification"])
    with pytest.raises(BundleError, match="clarification_2_not_attested"):
        authorization._verify_decision(v1_doc, reader, log, paths["frozen_protocol"], paths["execution_addendum"],
                                       NOW, paths["clarification"], clarification_2=paths["clarification_2"])
    # A v2 attestation missing the Clarification 2 hash refuses before any document read.
    bad = {k: v for k, v in doc["owner_decision"].items() if k != "clarification_2_sha256"}
    with pytest.raises(BundleError, match="invalid_owner_decision"):
        authorization._verify_decision(dict(owner="michaelbooth1", signed_at=bad["signed_at"], owner_decision=bad),
                                       reader, log, paths["frozen_protocol"], paths["execution_addendum"], NOW,
                                       paths["clarification"])
    # Tampered Clarification 2 bytes refuse; revoking v1 leaves v2 intact; revoking v2 refuses.
    paths["clarification_2"].write_bytes(paths["clarification_2"].read_bytes() + b"x")
    with pytest.raises(BundleError, match="clarification_2_sha256"):
        authorization.read_authorization(manifest, key, **ap)
    paths["clarification_2"].write_bytes(paths["clarification_2"].read_bytes()[:-1])
    log.write_text(log.read_text(encoding="utf8") + '| 2026-09-29 | REVOKE_MAKER_REPLAY | offline replay only | `{"authorization_id":"maker-replay-2026-10-15-v1"}` | — |\n', encoding="utf8")
    assert authorization.read_authorization(manifest, key, **ap) == doc
    log.write_text(log.read_text(encoding="utf8") + '| 2026-09-29 | REVOKE_MAKER_REPLAY | offline replay only | `{"authorization_id":"maker-replay-2026-10-15-v2"}` | — |\n', encoding="utf8")
    with pytest.raises(BundleError, match="revoked"):
        authorization.read_authorization(manifest, key, **ap)


def test_cli_preflight_create_only_and_hash_refusal(tmp_path, monkeypatch):
    doc, bundles, cb, paths, manifest, key = pack(tmp_path)
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    args = ["manifest", "verify", "--manifest", str(manifest), "--manifest-sha256", key]
    args += binding_args(tmp_path, bundles, cb, paths)
    assert main(args) == 0
    args[args.index(key)] = "0"*64
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_manifest_operational_refusal_is_recorded_not_consumed(tmp_path, monkeypatch):
    doc, bundles, cb, paths, manifest, key = pack(tmp_path)
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    args = ["manifest", "verify", "--manifest", str(manifest), "--manifest-sha256", key]
    args += binding_args(tmp_path, bundles, cb, paths)
    args[args.index(str(tmp_path/"panel"/bundles[0].day.isoformat()))] = str(tmp_path/"panel"/"missing")
    with pytest.raises(SystemExit):
        main(args)
    record, = (tmp_path/"attempts").glob("maker-replay-2026-10-15-v2.refusal-*.json")
    value = json.loads(record.read_bytes())
    assert (value["status"], value["stage"], value["toronto_date"]) == (
        "NOT_CONSUMED_OPERATIONAL_REFUSAL", "manifest_verify", "2026-10-15")
    assert not (tmp_path/"attempts"/"maker-replay-2026-10-15-v2.json").exists()


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
    doc, args, attempts = scored(tmp_path, monkeypatch)
    called = []
    def fail(*a, **k):
        called.append(True)
        assert (attempts/(doc["owner_decision"]["authorization_id"]+".json")).exists()
        raise BundleError("fixture_failure_after_consumption")
    monkeypatch.setattr(cli, "comparison_report", fail)
    for _ in range(2):
        with pytest.raises(SystemExit) as exc:
            main(args)
        assert exc.value.code == 2
    assert called == [True]
    assert not (tmp_path/"result").exists()
    stopped = json.loads((attempts/"maker-replay-2026-10-15-v2.stopped.json").read_bytes())
    assert (stopped["status"], stopped["stage"]) == ("CONSUMED_STOPPED", "scoring")


@pytest.mark.parametrize("fault, stage", [("output_exists", "output_preflight"), ("commit", "host_preflight"),
                                          ("window", "host_preflight"),
                                          ("missing_bundle", "input"), ("ceiling_flag", "ceiling_binding"),
                                          ("calibration", "manifest_verification"), ("source", "action_boundary")])
def test_operational_refusal_before_scoring_does_not_consume_the_look(tmp_path, monkeypatch, fault, stage):
    import maker_core.replay.__main__ as cli
    from maker_core.replay import execution_manifest
    late = datetime(2026, 10, 15, 12, 59, 50, tzinfo=timezone.utc)  # 08:59:50 Toronto: 32 s would pass 09:00.
    doc, args, attempts = scored(tmp_path, monkeypatch, commit=85.0 if fault == "commit" else 10.0,
                                 now=late if fault == "window" else NOW)
    good = list(args)
    if fault == "output_exists":
        (tmp_path/"result").mkdir()
    elif fault == "missing_bundle":
        args[args.index("--bundle")+1] = str(tmp_path/"panel"/"missing")
    elif fault == "ceiling_flag":
        args += ["--max-seconds", "300"]
    elif fault == "calibration":
        args[args.index("--calibration")+1] = str(tmp_path/"quote-markets.json")
    elif fault == "source":
        original = execution_manifest.source_hashes
        calls = []
        def changed(**kwargs):
            calls.append(True)
            value = original(**kwargs)
            return value if len(calls) == 1 else dict(value, extra="0"*64)
        monkeypatch.setattr(execution_manifest, "source_hashes", changed)
    scoring = []
    monkeypatch.setattr(cli, "comparison_report", lambda *a, **k: scoring.append(True) or pytest.fail("scored"))
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2 and not scoring
    assert not (attempts/"maker-replay-2026-10-15-v2.json").exists()
    record, = attempts.glob("maker-replay-2026-10-15-v2.refusal-*.json")
    assert json.loads(record.read_bytes())["stage"] == stage
    # The look remains available: the repaired run reserves it before its first policy replay.
    if fault == "output_exists":
        (tmp_path/"result").rmdir()
    monkeypatch.setattr(ceilings, "commit_percent", lambda: 10.0)
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    if fault == "source":
        monkeypatch.setattr(execution_manifest, "source_hashes", original)
    def stop(*a, **k):
        scoring.append(True)
        raise BundleError("fixture_stop_after_reservation")
    monkeypatch.setattr(cli, "comparison_report", stop)
    with pytest.raises(SystemExit):
        main(good)
    assert scoring == [True] and (attempts/"maker-replay-2026-10-15-v2.json").exists()


def test_late_look_needs_a_recorded_refusal_on_the_scoring_date(tmp_path, monkeypatch):
    import maker_core.replay.__main__ as cli
    later = datetime(2026, 10, 17, 10, tzinfo=timezone.utc)  # 06:00 Toronto, inside the window.
    doc, args, attempts = scored(tmp_path, monkeypatch, now=later)
    monkeypatch.setattr(cli, "comparison_report", lambda *a, **k: pytest.fail("scored"))
    with pytest.raises(SystemExit):
        main(args)
    assert not attempts.exists()  # Authorization refused: no record, no consumption.
    from maker_core.replay.execution_receipt import record_refusal
    record_refusal(attempts, "maker-replay-2026-10-15-v2", "input", "fixture", datetime(2026, 10, 16, 1, tzinfo=timezone.utc))
    with pytest.raises(SystemExit):  # A 10-16 UTC / 10-15 Toronto refusal permits a later look.
        monkeypatch.setattr(cli, "comparison_report", lambda *a, **k: (_ for _ in ()).throw(BundleError("stop")))
        main(args)
    assert (attempts/"maker-replay-2026-10-15-v2.json").exists()
    assert authorization.scoring_date_allowed(doc["owner_decision"], datetime(2026, 11, 1).date(), True) is False
    assert authorization.scoring_date_allowed(doc["owner_decision"], datetime(2026, 10, 31).date(), True) is True
    v1 = dict(doc["owner_decision"], authorization_id="maker-replay-2026-10-15-v1")
    assert authorization.scoring_date_allowed(v1, datetime(2026, 10, 16).date(), True) is False


def test_rehearsals_are_per_calibration_date_score_free_and_derive_the_rule(tmp_path, monkeypatch, capsys):
    from maker_core.replay.calibration import CALIBRATION_DATES
    from .fixtures.replay_scenario import Scenario
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    _, _, _, paths, _, _ = pack(tmp_path)
    for day in CALIBRATION_DATES:
        (tmp_path/"cal-panel"/day.isoformat()).mkdir(parents=True)
        Scenario(day, markets=("a",), minutes=60).bundle(tmp_path/"cal-panel"/day.isoformat()/"bundle")
    for day in ("2026-09-30", "2026-10-13"):
        with pytest.raises(SystemExit):
            main(["rehearse", "--bundle", str(tmp_path/"never-read"/day/"bundle"),
                  "--calibration", str(paths["calibration_path"]), "--out", str(tmp_path/"x.json")])
        assert "rehearsal_restricted_to_calibration_dates" in capsys.readouterr().err
    outs = []
    for day in CALIBRATION_DATES:
        out = tmp_path/f"rehearsal-{day.isoformat()}.json"
        assert main(["rehearse", "--bundle", str(tmp_path/"cal-panel"/day.isoformat()/"bundle"),
                     "--calibration", str(paths["calibration_path"]), "--out", str(out)]) == 0
        value = json.loads(out.read_bytes())
        assert set(value) == {"format", "date", "measured", "detail", "measured_at", "interpretation"}
        assert set(value["measured"]) == set(ceilings.MEASURED) and value["date"] == day.isoformat()
        assert set(value["detail"]) == {"dates", "conditions", "engine_passes", "input_hashes", "calibration_sha256"}
        assert len(value["detail"]["engine_passes"]) >= 8 and value["measured"]["report_bytes"] > 0
        assert all(set(p) == {"policy", "fill_bound", "events", "decisions", "spans"}
                   for p in value["detail"]["engine_passes"])
        outs += ["--rehearsal", str(out)]
    with pytest.raises(SystemExit):  # Two rehearsals cannot derive the rule.
        main(["derive_ceilings", *outs[:4], "--out", str(tmp_path/"partial.json")])
    assert main(["derive_ceilings", *outs, "--out", str(tmp_path/"m.json")]) == 0
    value = json.loads((tmp_path/"m.json").read_bytes())
    assert value["derived"] == ceilings.derive(value["per_date"]) and set(value["rehearsal_sha256"]) == set(
        value["per_date"])


def test_memory_guard_and_host_commit_refuse():
    ticks = iter([0.0, 1.0])
    check = ceilings.guarded(lambda: None, 100, memory=lambda: (101, 101), clock=lambda: next(ticks))
    with pytest.raises(BundleError, match="memory_ceiling"):
        check()
    for value in (None, 70.0, float("nan")):
        with pytest.raises(BundleError, match="commit"):
            ceilings.host_preflight(commit=lambda: value)
    assert ceilings.host_preflight(commit=lambda: 69.9) == 69.9
