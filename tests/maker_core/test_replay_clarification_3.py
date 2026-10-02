"""Clarification 3: reported-only quote presence, economic MDE, screen label and the v3 binding."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal as D
import json
import time

import pytest

from maker_core.evidence.journal import canonical_bytes
from maker_core.replay import authorization, ceilings, pack_cli
from maker_core.replay.__main__ import main
from maker_core.replay.bundle import BundleError, Limits, _Reader, sha256
from maker_core.replay.clarification_3 import (SCREEN_SUPPRESSED, SCREEN_SUPPRESSION_THRESHOLD, quote_presence,
                                               registered_decision)
from maker_core.replay.engine import ReplayConfig
from maker_core.replay.execution_manifest import build_manifest, verify_manifest
from maker_core.replay.execution_receipt import evaluate_hurdles
from maker_core.replay.report import comparison_report, report_bytes
from .fixtures.execution_pack import CLARIFICATION_3_DOCUMENT, RESEARCH, measurement, pack
from .test_replay_report import panel

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
V2, V3 = "maker-replay-2026-10-15-v2", "maker-replay-2026-10-15-v3"
# Owner signed Clarification 3 at 2026-10-01T17:44Z; these are its raw bytes' SHA-256.
SIGNED_CLARIFICATION_3_SHA256 = "fcbcb7d0d2a38777814b6f9d5e8b96c879d069af873c0b32fb4b274506b03eaa"
CORE = ("status", "economic_hurdle_met", "pull_hurdle_met", "reasons", "measured_k_sensitivity", "label",
        "interpretation")


@pytest.fixture(autouse=True)
def small_process(monkeypatch):
    monkeypatch.setattr(ceilings, "process_memory", lambda: (1, 1))


def _report(lower=1, fraction=D("0.4"), pull="HURDLE_MET", se=0.5):
    estimate = dict(status="OK", date_clusters=14, market_clusters=12, valid_replicates=2000, interval=[lower, 3],
                    estimate=2, bootstrap_standard_error=se, mde_80_normal_approx=2.486*se)
    value = dict(intervals={p+":"+m: dict(intervals={c: deepcopy(estimate) for c in ("date", "date_x_market")})
        for p in ("blind_re1", "no_quote", "clock_only") for m in ("modeled_net_k1", "modeled_net_k05", "modeled_net_k03")},
        scores={"fixture": True}, traces={"fixture": True},
        pull_efficiency=dict(status=pull, counts=dict(opportunities=100, informed_pulled=60)),
        quote_presence={"informed-v0": dict(pooled=dict(eligible_seconds=D(1000), quoted_seconds=1000*fraction,
                                                        quoted_fraction=fraction), markets={})})
    return dict(bounds={b: deepcopy(value) for b in ("strictly_through", "at_price")})


def _strip(report):
    return dict(report, bounds={name: {k: v for k, v in bound.items() if k != "quote_presence"}
                                for name, bound in report["bounds"].items()})


def _core(decision):
    return canonical_bytes({k: decision[k] for k in CORE})


VARIANTS = dict(met=dict(), not_met=dict(lower=0), not_met_quoting=dict(lower=0, fraction=D("0.5")),
                pull_not_met=dict(pull="HURDLE_NOT_MET"), underpowered=dict(pull="UNDERPOWERED"),
                unidentified=dict(pull="UNIDENTIFIED"), negative=dict(lower=-1, fraction=D(0)))


@pytest.mark.parametrize("name", VARIANTS)
def test_status_flags_and_reasons_are_byte_identical_with_and_without_clarification_3(name):
    report = _report(**VARIANTS[name])
    with_c3 = registered_decision(report)
    assert set(with_c3) == set(CORE) | {"economic_hurdle_met", "pull_hurdle_met", "clarification_3"}
    # Same bytes as the unchanged registered decision, and as a report carrying no Clarification 3 field.
    assert _core(with_c3) == canonical_bytes(evaluate_hurdles(report)) == canonical_bytes(evaluate_hurdles(_strip(report)))
    assert _core(registered_decision(_strip(report))) == _core(with_c3)


def test_screen_label_applies_only_to_hurdle_not_met_below_one_half():
    assert SCREEN_SUPPRESSION_THRESHOLD == D("0.5")
    label = lambda **kw: registered_decision(_report(**kw))["clarification_3"]["screen"]["label"]
    assert label(lower=0, fraction=D("0.4999")) == SCREEN_SUPPRESSED
    assert label(lower=0, fraction=D(0)) == SCREEN_SUPPRESSED
    assert label(lower=0, fraction=D("0.5")) is None  # At 0.5 the expected ceiling is exactly 2: reachable.
    assert label(fraction=D("0.1")) is None  # MET is never relabelled.
    for pull in ("UNDERPOWERED", "UNIDENTIFIED", "UNMATCHED"):
        assert label(lower=0, fraction=D("0.1"), pull=pull) is None
    missing = _report(lower=0)
    del missing["bounds"]["strictly_through"]["quote_presence"]
    assert registered_decision(missing)["clarification_3"]["screen"]["label"] is None
    screen = registered_decision(_report(lower=0))["clarification_3"]["screen"]
    assert screen["pull_common_set_quoted_fraction"] == D("0.4")
    assert screen["expected_pull_ratio_ceiling"] == 1 / D("0.6")


def test_economic_mde_states_what_a_non_significant_cell_could_detect():
    mde = registered_decision(_report(lower=0, se=0.5))["clarification_3"]["economic_mde"]
    assert set(mde["cells"]) == {"blind_re1:date", "blind_re1:date_x_market", "no_quote:date", "no_quote:date_x_market"}
    for cell in mde["cells"].values():
        assert cell["distinguishable_from_zero"] is False and cell["mde_80"] == pytest.approx(1.243)
        assert cell["statement"].startswith("not distinguishable from zero; this panel had about 80% power only")
    assert mde["binding_mde_80"] == pytest.approx(1.243)
    report = _report(se=0.5)
    report["bounds"]["strictly_through"]["intervals"]["no_quote:modeled_net_k1"]["intervals"]["date"][
        "mde_80_normal_approx"] = 9.0
    mde = registered_decision(report)["clarification_3"]["economic_mde"]
    assert all(c["statement"] is None for c in mde["cells"].values()) and mde["binding_mde_80"] == 9.0
    del report["bounds"]["strictly_through"]["intervals"]["blind_re1:modeled_net_k1"]
    mde = registered_decision(report)["clarification_3"]["economic_mde"]
    assert mde["binding_mde_80"] is None and mde["cells"]["blind_re1:date"]["status"] == "MISSING"


def test_quote_presence_per_policy_and_city_from_scored_rows(tmp_path):
    report = comparison_report(panel(tmp_path), ReplayConfig(hazard_per_minute=0), replicates=100)
    for bound in report["bounds"].values():
        presence = bound["quote_presence"]
        assert presence == quote_presence(bound["scores"]) and set(presence) == set(authorization.POLICIES)
        for policy, rows in bound["scores"].items():
            assert set(presence[policy]["markets"]) == {r["market_id"] for r in rows}
            pooled = presence[policy]["pooled"]
            assert pooled["eligible_seconds"] == sum(r["covered_seconds"] for r in rows)
            assert pooled["quoted_seconds"] == sum(r["covered_seconds"] - r["pulled_seconds"] for r in rows)
        assert all(e["quoted_seconds"] == 0 for e in (presence["no_quote"]["pooled"], *presence["no_quote"]["markets"].values()))
    markdown = report_bytes(report)[1]
    assert b"### Quote presence (Clarification 3, reported only)" in markdown and b"MDE80" in markdown
    # The registered decision on this report is unchanged by the presence fields.
    assert _core(registered_decision(report)) == canonical_bytes(evaluate_hurdles(_strip(report)))


def _reader():
    return _Reader(Limits(8*1024**2, 1, 5), time.monotonic)


def _verify(doc, paths, **extra):
    return authorization._verify_decision(doc, _reader(), paths["decision_log"], paths["frozen_protocol"],
                                          paths["execution_addendum"], NOW, paths["clarification"],
                                          require_scoring_date=False, clarification_2=paths["clarification_2"], **extra)


def test_signed_v3_pin_verifies_all_five_documents_and_v1_still_verifies(tmp_path):
    # The production pin itself, not a monkeypatched one.
    assert authorization.CLARIFICATION_3_SHA256 == SIGNED_CLARIFICATION_3_SHA256
    (tmp_path/"v3").mkdir()
    doc, bundles, cb, paths, _, _ = pack(tmp_path/"v3", authorization_id=V3)
    decision = doc["owner_decision"]
    assert set(decision) == authorization.DECISION_FIELDS | set(authorization.CLARIFIED_IDS[V3])
    hashed = {k: v for k, v in decision.items() if k.endswith("_sha256")}
    assert len(hashed) == 5 and hashed == {k: v for k, v in authorization.SIGNED_BINDINGS[V3].items()
                                           if k.endswith("_sha256")}
    _verify(doc, paths, clarification_3=paths["clarification_3"])
    assert verify_manifest(doc, bundles, cb, **paths, now=NOW) == doc
    # Any other Clarification 3 bytes fail against the pin.
    forged = dict(decision, clarification_3_sha256="0"*64)
    with pytest.raises(BundleError, match="signed_binding_mismatch:clarification_3_sha256"):
        _verify(dict(doc, owner_decision=forged), paths, clarification_3=paths["clarification_3"])
    # A v1 attestation (one clarification) still verifies against its own row.
    v1 = {k: v for k, v in decision.items() if k not in ("clarification_2_sha256", "clarification_3_sha256")}
    v1.update(authorization_id="maker-replay-2026-10-15-v1", signed_at="2026-09-27T00:00:00Z",
              expires_at="2026-10-16T04:00:00Z")
    log = paths["decision_log"]
    log.write_text(log.read_text(encoding="utf8").rstrip("\n") + "\n| 2026-09-27 | APPROVE_MAKER_REPLAY | offline "
                   "replay only | `" + json.dumps(v1) + "` | — |\n", encoding="utf8")
    authorization._verify_decision(dict(owner="michaelbooth1", signed_at=v1["signed_at"], owner_decision=v1),
                                   _reader(), log, paths["frozen_protocol"], paths["execution_addendum"], NOW,
                                   paths["clarification"])


def test_v3_binds_five_documents_and_v2_still_verifies(tmp_path, monkeypatch):
    v3_root, v2_root = tmp_path/"v3", tmp_path/"v2"
    v3_root.mkdir()
    v2_root.mkdir()
    raw = (RESEARCH/CLARIFICATION_3_DOCUMENT).read_bytes()
    monkeypatch.setitem(authorization.SIGNED_BINDINGS, V3,
                        dict(authorization.SIGNED_BINDINGS[V3], clarification_3_sha256=sha256(raw)))
    doc, bundles, cb, paths, manifest, key = pack(v3_root, authorization_id=V3)
    assert doc["owner_decision"]["clarification_3_sha256"] == sha256(raw)
    _verify(doc, paths, clarification_3=paths["clarification_3"])
    assert verify_manifest(doc, bundles, cb, **paths, now=NOW) == doc
    with pytest.raises(BundleError, match="clarification_3_path_required"):
        _verify(doc, paths)
    paths["clarification_3"].write_bytes(raw + b"x")
    with pytest.raises(BundleError, match="frozen_document_hash_mismatch:clarification_3_sha256"):
        _verify(doc, paths, clarification_3=paths["clarification_3"])
    # A v3 row cannot drop Clarification 3, and a v2 row cannot attest it.
    short = {k: v for k, v in doc["owner_decision"].items() if k != "clarification_3_sha256"}
    with pytest.raises(BundleError, match="invalid_owner_decision"):
        _verify(dict(doc, owner_decision=short), paths)
    with pytest.raises(BundleError, match="clarified_owner_decision_required"):
        build_manifest(bundles, cb, doc["calibration"], doc["universe"], short, measurement(),
                       calibration_sha256="0"*64, inventory_sha256="0"*64,
                       quote_inventory_sha256=doc["calibration"]["quote_inventory_sha256"],
                       measurement_sha256="0"*64)
    doc2, bundles2, cb2, paths2, _, _ = pack(v2_root)
    assert verify_manifest(doc2, bundles2, cb2, **paths2, now=NOW) == doc2
    with pytest.raises(BundleError, match="clarification_3_not_attested"):
        _verify(doc2, paths2, clarification_3=paths["clarification_2"])
    # v3 keeps v2's scoring date, late-look limit and expiry.
    assert authorization.LATE_LOOK_UNTIL[V3] == authorization.LATE_LOOK_UNTIL[V2]
    assert authorization.EXPIRES_NO_LATER_THAN[V3] == authorization.EXPIRES_NO_LATER_THAN[V2]


def test_v3_pins_v2_documents_and_the_clarification_3_pin_matches_the_file():
    v2, v3 = authorization.SIGNED_BINDINGS[V2], authorization.SIGNED_BINDINGS[V3]
    assert {k: v for k, v in v3.items() if k != "clarification_3_sha256"} == v2
    pin = v3["clarification_3_sha256"]
    assert pin == SIGNED_CLARIFICATION_3_SHA256 == sha256((RESEARCH/CLARIFICATION_3_DOCUMENT).read_bytes())
    assert len((RESEARCH/CLARIFICATION_3_DOCUMENT).read_bytes()) < 65536  # The verifier's per-document cap.


def test_scored_v3_look_reports_clarification_3_beside_the_unchanged_decision(tmp_path, monkeypatch):
    raw = (RESEARCH/CLARIFICATION_3_DOCUMENT).read_bytes()
    monkeypatch.setitem(authorization.SIGNED_BINDINGS, V3,
                        dict(authorization.SIGNED_BINDINGS[V3], clarification_3_sha256=sha256(raw)))
    doc, bundles, cb, paths, manifest, key = pack(tmp_path, authorization_id=V3)
    monkeypatch.setattr(pack_cli, "_now", lambda: NOW)
    monkeypatch.setattr(authorization, "_utc_now", lambda: NOW)
    monkeypatch.setattr(ceilings, "commit_percent", lambda: 10.0)
    monkeypatch.setitem(authorization.APPROVED_REGISTRATIONS, key, "michaelbooth1")
    flags = dict(calibration_path="calibration", inventory_path="universe", quote_inventory_path="quote-markets",
                 measurement_path="ceiling-measurement")
    args = ["run", "--compare", "--pre-registration", str(manifest), "--pre-registration-sha256", key,
            "--out", str(tmp_path/"result")]
    args += [x for b in bundles for x in ("--bundle", str(tmp_path/"panel"/b.day.isoformat()))]
    args += [x for b in cb for x in ("--calibration-bundle", str(tmp_path/"calibration-bundles"/b.day.isoformat()))]
    args += [x for k, p in paths.items() for x in ("--"+flags.get(k, k.replace("_", "-")), str(p))]
    assert main(args) == 0
    report = json.loads((tmp_path/"result"/"report.json").read_bytes())
    decision = report["registered_decision"]
    assert set(decision["clarification_3"]) == {"quote_presence", "economic_mde", "screen", "interpretation"}
    stripped = json.loads(canonical_bytes({k: v for k, v in decision.items() if k != "clarification_3"}))
    without = dict(report, bounds={n: {k: v for k, v in b.items() if k != "quote_presence"} for n, b in report["bounds"].items()})
    assert stripped == json.loads(canonical_bytes(evaluate_hurdles(without)))
    completed = json.loads((tmp_path/"attempts"/(V3+".completed.json")).read_bytes())
    assert completed["registered_decision"] == decision
    markdown = next((tmp_path/"result").glob("*.md")).read_text(encoding="utf-8")
    assert "Clarification 3 (reported only" in markdown and "Economic MDE" in markdown
