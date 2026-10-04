from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timezone
import json

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import authorization, ceilings, pack_cli
from maker_core.replay.__main__ import main
from maker_core.replay.bundle import BundleError, sha256
from maker_core.replay.engine import replay, ReplayConfig
from maker_core.replay.execution_manifest import apply_manifest, build_manifest, verify_manifest
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
    # Largest date x 15, next power of two; memory adds the unmultiplied baseline.
    assert doc["ceilings"] == dict(max_input_bytes=2**28, max_records=2**19, max_seconds=32.0,
                                   max_output_bytes=2*1024**2, max_memory_bytes=2**29 + 100*1024**2)
    assert (doc["replay_config"]["max_events"], doc["replay_config"]["max_outputs"]) == (2**20, 2**20)
    assert doc["ceiling_measurement"]["derived"]["multiplier"] == 15
    assert doc["ceiling_measurement"]["per_date"]["2026-09-27"] == MEASURED
    assert doc["ceiling_measurement"]["derived"]["largest"] == MEASURED
    assert ceilings.next_power_of_two(2.0*15) == 32 and ceilings.next_power_of_two(64) == 64
    assert ceilings.next_power_of_two(65) == 128 and ceilings.next_power_of_two(0.2) == 1


@pytest.mark.parametrize("field, value, binding", [
    ("runtime_seconds", 547.0, "runtime_seconds"),                      # 8,205 s -> 16,384 s > 4 h
    ("peak_memory_above_baseline_bytes", 547*1024**2, "memory_bytes"),  # 16 GiB + baseline > 70% of 16 GiB
    ("input_bytes", 547*1024**2, "input_bytes"),
    ("report_bytes", 547*1024**2, "report_bytes"),                     # Clarification 2 byte limits
    ("records", 150_000_000, "records"),                                 # 2.25e9 -> 2^32 > 2^31 count limit
    ("decisions_spans", 150_000_000, "decisions_spans")])
def test_binding_host_limit_is_not_executable_never_truncated(field, value, binding):
    derived = ceilings.derive(per_date(dict(MEASURED, **{field: value})))
    assert derived["executable"] is False and derived["host_limit_binding"] == [binding]
    assert derived["verdict"] == "not executable on this host"
    with pytest.raises(BundleError, match="not_executable_on_host:"+binding+r" \(not executable on this host\)"):
        ceilings.run_limits(derived)


@pytest.mark.parametrize("field", ["runtime_seconds", "peak_memory_above_baseline_bytes"])
def test_per_date_allowance_is_about_546_seconds_and_546_mib(field):
    # x15 then the next power of two: 546 -> 8,190 -> 8,192 fits; 547 -> 8,205 -> 16,384 does not.
    unit = 1.0 if field == "runtime_seconds" else 1024**2
    fits = ceilings.derive(per_date(dict(MEASURED, **{field: type(MEASURED[field])(546*unit)})))
    assert fits["executable"] and fits["verdict"] == "executable on this host"
    assert fits["ceilings"]["runtime_seconds" if field == "runtime_seconds" else "memory_bytes"] == (
        8192 if field == "runtime_seconds" else 8*1024**3 + MEASURED["baseline_memory_bytes"])
    assert not ceilings.derive(per_date(dict(MEASURED, **{field: type(MEASURED[field])(547*unit)})))["executable"]


def test_derive_ceilings_cli_reports_not_executable_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    from maker_core.replay.pack_io import write_json
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    args = []
    for day, measured in per_date(dict(MEASURED, runtime_seconds=600.0)).items():
        path = tmp_path/f"rehearsal-{day}.json"
        write_json(path, dict(format=ceilings.REHEARSAL_FORMAT, date=day, measured=measured,
                              detail=dict(calibration_sha256="0"*64), measured_at=NOW.isoformat()))
        args += ["--rehearsal", str(path)]
    assert main(["derive_ceilings", *args, "--out", str(tmp_path/"m.json")]) == 3
    assert "verdict=not executable on this host" in capsys.readouterr().out
    value = json.loads((tmp_path/"m.json").read_bytes())
    assert value["derived"]["host_limit_binding"] == ["runtime_seconds"]


def test_baseline_is_added_not_multiplied():
    derived = ceilings.derive(per_date(dict(MEASURED, baseline_memory_bytes=2*1024**3)))
    assert derived["ceilings"]["memory_bytes"] == 2**29 + 2*1024**3 and derived["executable"]
    with pytest.raises(BundleError, match="incomplete"):
        ceilings.derive({"2026-09-27": MEASURED})


def test_manifest_refuses_unexecutable_or_rederived_measurement(tmp_path):
    (tmp_path/"a").mkdir()
    (tmp_path/"b").mkdir()
    with pytest.raises(BundleError, match="not_executable_on_host"):
        pack(tmp_path/"a", measured=dict(MEASURED, runtime_seconds=547.0))
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
    # A v2 row binding any other Clarification 2 hash, scoring date or a later expiry refuses even when
    # the row and the supplied bytes agree with each other: v2 pins the signed bindings.
    other = b"# not the signed Clarification 2\n"
    (tmp_path/"other-c2.md").write_bytes(other)
    for change, reason in ((dict(clarification_2_sha256=sha256(other)), "signed_binding_mismatch:clarification_2_sha256"),
                           (dict(scoring_date="2026-10-16"), "signed_binding_mismatch:scoring_date"),
                           (dict(expires_at="2026-11-01T04:00:01Z"), "expiry_after_signed_limit")):
        changed = dict(doc["owner_decision"], **change)
        pinned_log = tmp_path/"pinned-DECISION_LOG.md"
        pinned_log.write_text(authorization.LOG_HEADER + "\n| --- | --- | --- | --- | --- |\n| 2026-09-29 | "
                              "APPROVE_MAKER_REPLAY | offline replay only | `" + json.dumps(changed) + "` | — |\n",
                              encoding="utf8")
        with pytest.raises(BundleError, match=reason):
            authorization._verify_decision(dict(owner="michaelbooth1", signed_at=changed["signed_at"],
                                                owner_decision=changed), reader, pinned_log, paths["frozen_protocol"],
                                           paths["execution_addendum"], NOW, paths["clarification"],
                                           require_scoring_date=False, clarification_2=tmp_path/"other-c2.md")
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


@pytest.mark.parametrize("action", ["verify", "build"])
def test_manifest_cli_refuses_before_the_toronto_scoring_date(tmp_path, monkeypatch, capsys, action):
    doc, bundles, cb, paths, manifest, key = pack(tmp_path)
    monkeypatch.setattr(pack_cli, "_now", lambda: datetime(2026, 10, 15, 3, 59, tzinfo=timezone.utc))  # 10-14 23:59
    (tmp_path/"decision.json").write_bytes(canonical_bytes(doc["owner_decision"]))
    args = (["manifest", "verify", "--manifest", str(manifest), "--manifest-sha256", key] if action == "verify" else
            ["manifest", "build", "--owner-decision", str(tmp_path/"decision.json"), "--out", str(tmp_path/"m2.json")])
    with pytest.raises(SystemExit) as exc:
        main(args + binding_args(tmp_path, bundles, cb, paths))
    assert exc.value.code == 2 and "manifest_before_scoring_date_toronto" in capsys.readouterr().err
    assert not (tmp_path/"attempts").exists() and not (tmp_path/"m2.json").exists()
    monkeypatch.setattr(pack_cli, "_now", lambda: datetime(2026, 10, 15, 4, tzinfo=timezone.utc))  # 10-15 00:00
    assert main(args + binding_args(tmp_path, bundles, cb, paths)) == 0


def test_signed_documents_on_disk_match_the_pinned_v2_hashes():
    from .fixtures.execution_pack import RESEARCH, SIGNED_DOCUMENTS
    fields = dict(frozen_protocol="protocol_sha256", execution_addendum="addendum_sha256",
                  clarification="clarification_sha256", clarification_2="clarification_2_sha256")
    pinned = authorization.SIGNED_BINDINGS["maker-replay-2026-10-15-v2"]
    for name, filename in SIGNED_DOCUMENTS.items():
        assert sha256((RESEARCH/filename).read_bytes()) == pinned[fields[name]], filename
    assert pinned["clarification_2_sha256"] == "1719fd1ea679cd14501d5b6ddd392fbb9e8d2b086cf6b5a3c0348961824e60f0"
    assert authorization.EXPIRES_NO_LATER_THAN["maker-replay-2026-10-15-v2"] == datetime(
        2026, 11, 1, 4, tzinfo=timezone.utc)


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


def _hurdle_report(k03_lower=1, k05_lower=1):
    estimate = dict(status="OK", date_clusters=14, market_clusters=12, valid_replicates=2000, interval=[1, 3])
    lowers = dict(modeled_net_k1=1, modeled_net_k05=k05_lower, modeled_net_k03=k03_lower)
    value = dict(intervals={p+":"+m: dict(intervals={c: dict(estimate, interval=[lowers[m], 3])
                                                     for c in ("date", "date_x_market")})
        for p in ("blind_re1", "no_quote", "clock_only") for m in lowers},
        scores={"fixture": True}, traces={"fixture": True}, pull_efficiency=dict(status="HURDLE_MET"))
    return dict(bounds={b: deepcopy(value) for b in ("strictly_through", "at_price")})


def test_measured_k_label_is_reported_beside_an_unchanged_status():
    keys = ("status", "economic_hurdle_met", "pull_hurdle_met", "reasons")
    met = evaluate_hurdles(_hurdle_report())
    assert met["status"] == "REPLAY_HURDLES_MET" and met["label"] is None
    assert met["measured_k_sensitivity"]["k03_lower_bounds_positive"] is True
    assert met["measured_k_sensitivity"]["k05_lower_bounds_positive"] is True
    for k03, k05 in ((0, 1), (-1, -1)):
        decision = evaluate_hurdles(_hurdle_report(k03, k05))
        # Status, hurdle flags and reasons are exactly those of the positive case.
        assert {k: decision[k] for k in keys} == {k: met[k] for k in keys}
        assert decision["label"] == "hurdles_met_not_positive_at_measured_k"
        assert decision["measured_k_sensitivity"]["k03_lower_bounds_positive"] is False
        assert decision["measured_k_sensitivity"]["k05_lower_bounds_positive"] is (k05 > 0)
    # Only the strictly_through bound and the two economic baselines count; clock_only and at_price do not.
    report = _hurdle_report()
    report["bounds"]["at_price"]["intervals"]["no_quote:modeled_net_k03"]["intervals"]["date"]["interval"][0] = -1
    report["bounds"]["strictly_through"]["intervals"]["clock_only:modeled_net_k03"]["intervals"]["date"]["interval"][0] = -1
    assert evaluate_hurdles(report)["label"] is None
    # A missing k = 0.3 estimate is not positive; the label never applies to a status other than MET.
    report = _hurdle_report()
    del report["bounds"]["strictly_through"]["intervals"]["blind_re1:modeled_net_k03"]
    missing = evaluate_hurdles(report)
    assert missing["status"] == "REPLAY_HURDLES_MET" and missing["label"] == "hurdles_met_not_positive_at_measured_k"
    assert missing["measured_k_sensitivity"]["cells"]["k03:blind_re1:date"]["status"] == "MISSING"
    report = _hurdle_report(-1)
    report["bounds"]["strictly_through"]["intervals"]["no_quote:modeled_net_k1"]["intervals"]["date"]["interval"][0] = 0
    failed = evaluate_hurdles(report)
    assert failed["status"] == "HURDLE_NOT_MET" and failed["label"] is None
    assert failed["measured_k_sensitivity"]["k03_lower_bounds_positive"] is False


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
                                          ("calibration", "manifest_verification"), ("source", "action_boundary"),
                                          ("pull_cap", "engine_preflight")])
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
    elif fault == "pull_cap":
        from maker_core.replay import pull_efficiency
        candidates = pull_efficiency.opportunity_candidates
        monkeypatch.setattr(pull_efficiency, "opportunity_candidates", lambda windows: 2**40)
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
    if fault == "pull_cap":
        monkeypatch.setattr(pull_efficiency, "opportunity_candidates", candidates)
    def stop(*a, **k):
        scoring.append(True)
        raise BundleError("fixture_stop_after_reservation")
    monkeypatch.setattr(cli, "comparison_report", stop)
    with pytest.raises(SystemExit):
        main(good)
    assert scoring == [True] and (attempts/"maker-replay-2026-10-15-v2.json").exists()


@pytest.mark.parametrize("writes", [False, True])
def test_failed_reservation_consumes_only_when_it_wrote_the_receipt(tmp_path, monkeypatch, writes):
    import maker_core.replay.__main__ as cli
    from maker_core.replay import execution_receipt
    doc, args, attempts = scored(tmp_path, monkeypatch)
    manifest = tmp_path/"manifest.json"
    original = execution_receipt.reserve_attempt
    def failing(*a, **k):
        if writes:
            original(*a, **k)
        raise OSError("fixture_reservation_failure")
    monkeypatch.setattr(execution_receipt, "reserve_attempt", failing)
    monkeypatch.setattr(cli, "comparison_report", lambda *a, **k: pytest.fail("scored"))
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2
    refusals = list(attempts.glob("maker-replay-2026-10-15-v2.refusal-*.json"))
    stopped = attempts/"maker-replay-2026-10-15-v2.stopped.json"
    if writes:
        assert not refusals
        assert json.loads(stopped.read_bytes())["stage"] == "reservation"
        assert execution_receipt.late_look_permitted(manifest, doc) is False
    else:
        record, = refusals
        assert not stopped.exists() and not (attempts/"maker-replay-2026-10-15-v2.json").exists()
        body = json.loads(record.read_bytes())
        assert (body["status"], body["stage"]) == ("NOT_CONSUMED_OPERATIONAL_REFUSAL", "reservation")
        assert execution_receipt.late_look_permitted(manifest, doc) is True


def test_late_look_runs_on_any_permitted_date_while_unreserved(tmp_path, monkeypatch):
    import maker_core.replay.__main__ as cli
    later = datetime(2026, 10, 17, 10, tzinfo=timezone.utc)  # 06:00 Toronto, inside the window.
    doc, args, attempts = scored(tmp_path, monkeypatch, now=later)
    # No refusal record is needed: an unreserved look runs on 10-17 and is consumed by its reservation.
    def stop(*a, **k):
        assert (attempts/"maker-replay-2026-10-15-v2.json").exists()
        raise BundleError("fixture_stop_after_reservation")
    monkeypatch.setattr(cli, "comparison_report", stop)
    with pytest.raises(SystemExit):
        main(args)
    assert not list(attempts.glob("*.refusal-*.json"))
    stopped = json.loads((attempts/"maker-replay-2026-10-15-v2.stopped.json").read_bytes())
    assert (stopped["status"], stopped["stage"]) == ("CONSUMED_STOPPED", "scoring")
    # The reservation consumed the look: later dates refuse at authorization and write nothing new.
    before = sorted(p.name for p in attempts.iterdir())
    monkeypatch.setattr(cli, "comparison_report", lambda *a, **k: pytest.fail("scored"))
    for day in (datetime(2026, 10, 15, 12, tzinfo=timezone.utc), datetime(2026, 10, 20, 10, tzinfo=timezone.utc)):
        monkeypatch.setattr(authorization, "_utc_now", lambda: day)
        monkeypatch.setattr(pack_cli, "_now", lambda: day)
        with pytest.raises(SystemExit):
            main(args)
    assert sorted(p.name for p in attempts.iterdir()) == before
    from maker_core.replay.execution_receipt import late_look_permitted
    assert late_look_permitted(tmp_path/"manifest.json", doc) is False


def test_late_look_window_is_toronto_10_15_to_10_31_and_v2_only(tmp_path):
    doc, _, _, _, manifest, _ = pack(tmp_path)
    from maker_core.replay.execution_receipt import late_look_permitted
    assert late_look_permitted(manifest, doc) is True  # No attempts directory yet.
    allowed = authorization.scoring_date_allowed
    decision = doc["owner_decision"]
    assert allowed(decision, date(2026, 10, 15), False) is True
    assert allowed(decision, date(2026, 10, 31), True) is True
    assert allowed(decision, date(2026, 10, 20), False) is False  # Reserved: consumed whatever the date.
    assert allowed(decision, date(2026, 11, 1), True) is False
    assert allowed(decision, date(2026, 10, 14), True) is False
    v1 = dict(decision, authorization_id="maker-replay-2026-10-15-v1")
    assert allowed(v1, date(2026, 10, 16), True) is False
    reserve_attempt(manifest, doc, "0"*64, NOW)
    assert late_look_permitted(manifest, doc) is False


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


def test_completed_look_carries_the_measured_k_flag_in_report_and_receipt(tmp_path, monkeypatch):
    doc, args, attempts = scored(tmp_path, monkeypatch)
    assert main(args) == 0
    report = json.loads((tmp_path/"result"/"report.json").read_bytes())
    decision = report["registered_decision"]
    assert set(decision["measured_k_sensitivity"]) >= {"k03_lower_bounds_positive", "k05_lower_bounds_positive", "cells"}
    assert decision["label"] in (None, "hurdles_met_not_positive_at_measured_k")
    assert (decision["label"] is not None) == (decision["status"] == "REPLAY_HURDLES_MET"
                                               and not decision["measured_k_sensitivity"]["k03_lower_bounds_positive"])
    completed = json.loads((attempts/"maker-replay-2026-10-15-v2.completed.json").read_bytes())
    assert completed["registered_decision"] == decision
    markdown = next((tmp_path/"result").glob("*.md")).read_text(encoding="utf-8")
    assert "Measured-reaction sensitivity" in markdown and "Label: " in markdown


def test_manifest_refuses_a_ceiling_measurement_rehearsed_on_another_calibration(tmp_path):
    doc, bundles, cb, paths, _, _ = pack(tmp_path)
    calibration = json.loads(paths["calibration_path"].read_bytes())
    sealed = sha256(paths["calibration_path"].read_bytes())
    kwargs = dict(calibration_sha256=sealed, inventory_sha256=doc["universe_sha256"],
                  quote_inventory_sha256=doc["calibration"]["quote_inventory_sha256"], measurement_sha256="0"*64)
    inventory = json.loads(paths["inventory_path"].read_bytes())
    with pytest.raises(BundleError, match="ceiling_measurement_calibration_mismatch"):
        build_manifest(bundles, cb, calibration, inventory, doc["owner_decision"], measurement(), **kwargs)
    built = build_manifest(bundles, cb, calibration, inventory, doc["owner_decision"],
                           measurement(calibration_sha256=sealed), **kwargs)
    assert built["calibration_sha256"] == sealed
