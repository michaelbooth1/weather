"""The §9-§11 rehearsal subcommands end to end through the admitted entry, on fictional bundles (U5).

The bundles are ``fixtures.panel_v02`` fictional v0.2 days on the real calibration dates and the calibration
document is invented; no captured data is read.
"""
from __future__ import annotations

import json

import pytest

from maker_core.replay import bundle_v02
from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.pack_io import read_json
from maker_core.replay.v2 import rehearsal
from tools.research.maker_replay_v2 import rehearse_cli, run

from .fixtures.panel_v02 import Panel

REPLICATES = "100"  # the bootstrap floor; the subcommand defaults to 2000
DAYS = [d.isoformat() for d in CALIBRATION_DATES]


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("cli")
    panel = Panel(bands=1, step=5, full=True, capture_minutes=range(0, 600))
    bundles = {d.isoformat(): panel.write(root / "bundles" / d.isoformat(), d, provenance="captured")
               for d in CALIBRATION_DATES}
    calibration = root / "calibration.json"
    calibration.write_text(json.dumps(dict(
        format="maker_core.replay.calibration.v1", hazard_per_minute="0.001000000000", markets=["austin", "toronto"],
        global_fallback=None, cities={"austin": {"upper": "0.001000000000"}, "toronto": {"upper": "0.000500000000"}})),
        encoding="utf-8")
    return root, bundles, calibration


def call(root, name, label, *args):
    out = root / label
    assert run.main([name, "--out", str(out), *map(str, args)]) == 0
    value, _ = read_json(out / f"{name}.json", rehearse_cli.DOCUMENT_BYTES)
    return out / f"{name}.json", value


def bundle_args(bundles, days):
    return [a for day in days for a in ("--bundle", bundles[day])]


@pytest.fixture(scope="module")
def documents(workspace):
    root, bundles, calibration = workspace
    docs = {}
    for label, days in [(d, [d]) for d in DAYS] + [("carried", DAYS)]:
        inventory, value = call(root, "rehearsal-inventory", "inv-" + label, *bundle_args(bundles, days))
        assert value["format"] == rehearse_cli.INVENTORY_FORMAT and value["dates"] == days and value["rows"]
        mode = "carried" if label == "carried" else "per_date"
        common = ("--inventory", inventory, "--calibration", calibration, "--mode", mode, "--replicates", REPLICATES)
        docs[label] = call(root, "rehearse", "reh-" + label, *bundle_args(bundles, days), *common)
        if label == DAYS[1]:
            docs["repeat"] = call(root, "rehearse", "reh-repeat", *bundle_args(bundles, days), *common)
        if label == "carried":
            docs["r1"] = call(root, "rehearse", "reh-r1", *bundle_args(bundles, days), *common,
                              "--hazard-variant", "r1_per_city")
    return docs


def test_rehearse_writes_a_whitelisted_document_bound_to_its_inputs(workspace, documents):
    _, _, calibration = workspace
    _, doc = documents["carried"]
    assert rehearsal.whitelisted(doc) is doc and doc["mode"] == "carried" and doc["dates"] == DAYS
    assert doc["calibration_sha256"] == read_json(calibration)[1]
    assert doc["hazard_per_minute"] == .001 and doc["hazard_map_sha256"] is None
    assert doc["inventory_sha256"] and "reachability" in doc
    _, r1 = documents["r1"]
    assert r1["hazard_variant"] == "r1_per_city" and r1["hazard_map_sha256"]
    assert r1["hashes"]["decision_sha256"] != doc["hashes"]["decision_sha256"]  # toronto reads its own U_m


def test_derive_and_the_gate_report_read_the_written_documents(workspace, documents):
    root, _, _ = workspace
    per_date = ["--per-date", *(documents[d][0] for d in DAYS)]
    _, derived = call(root, "derive", "derived", *per_date, "--carried", documents["carried"][0])
    assert derived["format"] == rehearse_cli.DERIVED_FORMAT and derived["derived"]["executable"] is True
    assert derived["e5"]["days_do_not_accumulate"] in (True, False) and derived["run_limits"]
    evidence = root / "e8.json"
    evidence.write_text(json.dumps(dict(status="PASS", evidence="fixture suite")), encoding="utf-8")
    _, gate = call(root, "gate-report", "gate", *per_date, "--carried", documents["carried"][0],
                   "--repeat-rehearsal", documents["repeat"][0], "--r1", documents["r1"][0], "--e8", evidence)
    gates = gate["executability"]["gates"]
    assert gates["E7"]["status"] == "PASS" and gates["E8"] == dict(status="PASS", evidence="fixture suite")
    assert gate["executability"]["not_supplied"] == ["E1", "E3"]
    assert gates["E6"]["status"] == "PASS" and gate["executability"]["not_evaluated"] == []  # E6 = A (10-15)
    assert derived["derived"]["ceilings"]["pull_candidates"] == gates["E6"]["max_pull_candidates"]
    # real in-process memory readings (E5) may fail here; E1/E3 are not supplied, so it never reads PASS
    failed = any(g["status"] == "FAIL" for g in gates.values())
    assert gate["executability"]["status"] == ("FAIL" if failed else "INCOMPLETE")
    assert set(gate["reachability"]["variants"]) == {"max_m", "r1_per_city"}


def test_a_panel_date_is_refused_before_any_bundle_is_opened(workspace, monkeypatch):
    root, _, calibration = workspace
    monkeypatch.setattr(bundle_v02, "open_stream_bundle", lambda *a, **k: pytest.fail("a bundle was opened"))
    panel_path = root / "bundles" / "2026-10-02" / "bundle"
    for name, extra in (("rehearsal-inventory", ()), ("rehearse", ("--mode", "per_date", "--calibration", calibration,
                                                                    "--inventory", calibration))):
        with pytest.raises(BundleError, match="rehearsal_restricted_to_calibration_dates"):
            run.main([name, "--out", str(root / ("refused-" + name)), "--bundle", str(panel_path), *map(str, extra)])


def test_rehearse_refuses_an_inventory_for_other_dates(workspace, documents):
    root, bundles, calibration = workspace
    inventory = root / "inv-carried" / "rehearsal-inventory.json"
    with pytest.raises(BundleError, match="rehearsal_inventory_dates_mismatch"):
        run.main(["rehearse", "--out", str(root / "mismatch"), "--bundle", str(bundles[DAYS[0]]), "--inventory",
                  str(inventory), "--calibration", str(calibration), "--mode", "per_date"])


def test_an_inventory_takes_one_date_or_all_three(workspace, monkeypatch):
    # Defender D7.2 / v03: two dates are neither a per-date nor a carried rehearsal; refused before anything is read
    from weather.market import maker_replay_universe_v02
    root, bundles, _ = workspace
    monkeypatch.setattr(maker_replay_universe_v02, "universe", lambda *a, **k: pytest.fail("bundles were read"))
    with pytest.raises(BundleError, match="rehearsal_bundle_paths_invalid"):
        run.main(["rehearsal-inventory", "--out", str(root / "two-dates"), *map(str, bundle_args(bundles, DAYS[:2]))])


def test_derive_refuses_mislabelled_rehearsals(workspace, documents):
    # Defender D7.2 / v04: derive holds the documents to the labels gate-report requires
    root, _, _ = workspace
    per_date = [documents[d][0] for d in DAYS]
    carried = documents["carried"][0]
    cases = [
        # carried passed as a per-date one; its first date (DAYS[0]) is not a duplicate, so the label check refuses
        ([*per_date[1:], carried], carried, "gate_per_date_rehearsal_required"),
        (per_date, per_date[0], "gate_carried_rehearsal_required:max_m"),  # a per-date one passed as carried
        (per_date, documents["r1"][0], "gate_carried_rehearsal_required:max_m"),  # R1 is not the ceiling run
    ]
    for i, (dates, carried_path, refusal) in enumerate(cases):
        with pytest.raises(BundleError, match=refusal):
            run.main(["derive", "--out", str(root / f"derive-refused-{i}"), "--per-date", *map(str, dates),
                      "--carried", str(carried_path)])
