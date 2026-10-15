"""The §9-§11 rehearsal subcommands end to end through the admitted entry, on fictional bundles (U5).

The bundles are ``fixtures.panel_v02`` fictional v0.2 days on the real calibration dates and the calibration
document is invented; no captured data is read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import warnings

import pytest

from maker_core.replay import bundle_v02
from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.pack_io import read_json
from maker_core.replay.v2 import rehearsal
from tools.research.maker_replay_v2 import rehearse_cli, run

from .fixtures.panel_v02 import Panel

REPLICATES = "100"  # the bootstrap floor; the subcommand defaults to 2000
ROOT = Path(__file__).resolve().parents[2]
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


def call_process(root, name, label, seed, *args):
    """``call`` in a fresh interpreter under ``PYTHONHASHSEED=seed`` (row 17: E7's two processes)."""
    out = root / label
    env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT))))
    done = subprocess.run([sys.executable, "-B", "-m", "tools.research.maker_replay_v2.run", name, "--out", str(out),
                           *map(str, args)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    value, _ = read_json(out / f"{name}.json", rehearse_cli.DOCUMENT_BYTES)
    return out / f"{name}.json", value


def refused(capsys, argv):
    """(code, stdout) of a refused subcommand: rc 2 and one ``refused: <code>`` line on stderr (row 16)."""
    capsys.readouterr()
    assert run.main([str(a) for a in argv]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("refused: ") and captured.err.count("\n") == 1 and captured.out == ""
    return captured.err.strip()[len("refused: "):], captured.out


@pytest.fixture(scope="module")
def documents(workspace):
    root, bundles, calibration = workspace
    docs = {}
    for label, days in [(d, [d]) for d in DAYS] + [("carried", DAYS)]:
        inventory, value = call(root, "rehearsal-inventory", "inv-" + label, *bundle_args(bundles, days))
        assert value["format"] == rehearse_cli.INVENTORY_FORMAT and value["dates"] == days and value["rows"]
        mode = "carried" if label == "carried" else "per_date"
        common = ("--inventory", inventory, "--calibration", calibration, "--mode", mode, "--replicates", REPLICATES)
        if label == DAYS[1]:  # E7's pair: two fresh processes under different hash seeds (row 17)
            docs[label] = call_process(root, "rehearse", "reh-" + label, 0, *bundle_args(bundles, days), *common)
            docs["repeat"] = call_process(root, "rehearse", "reh-repeat", 1, *bundle_args(bundles, days), *common)
            docs["same-process"] = call(root, "rehearse", "reh-same", *bundle_args(bundles, days), *common)
        else:
            docs[label] = call(root, "rehearse", "reh-" + label, *bundle_args(bundles, days), *common)
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
    assert gates["E7"]["separate_hash_seeds"] is True and all(gates["E7"]["identical"].values())
    assert gate["executability"]["not_supplied"] == ["E1", "E3"]
    assert gates["E6"]["status"] == "PASS" and gate["executability"]["not_evaluated"] == []  # E6 = A (10-15)
    assert derived["derived"]["ceilings"]["pull_candidates"] == gates["E6"]["max_pull_candidates"]
    # real in-process memory readings (E5) may fail here; E1/E3 are not supplied, so it never reads PASS
    failed = any(g["status"] == "FAIL" for g in gates.values())
    assert gate["executability"]["status"] == ("FAIL" if failed else "INCOMPLETE")
    assert set(gate["reachability"]["variants"]) == {"max_m", "r1_per_city"}


def test_a_panel_date_is_refused_before_any_bundle_is_opened(workspace, monkeypatch, capsys):
    root, _, calibration = workspace
    monkeypatch.setattr(bundle_v02, "open_stream_bundle", lambda *a, **k: pytest.fail("a bundle was opened"))
    panel_path = root / "bundles" / "2026-10-02" / "bundle"
    for name, extra in (("rehearsal-inventory", ()), ("rehearse", ("--mode", "per_date", "--calibration", calibration,
                                                                    "--inventory", calibration))):
        code, _ = refused(capsys, [name, "--out", root / ("refused-" + name), "--bundle", panel_path, *extra])
        assert code == "rehearsal_restricted_to_calibration_dates"


def test_rehearse_refuses_an_inventory_for_other_dates(workspace, documents, capsys):
    root, bundles, calibration = workspace
    inventory = root / "inv-carried" / "rehearsal-inventory.json"
    code, _ = refused(capsys, ["rehearse", "--out", root / "mismatch", "--bundle", bundles[DAYS[0]], "--inventory",
                               inventory, "--calibration", calibration, "--mode", "per_date"])
    assert code == "rehearsal_inventory_dates_mismatch"


def test_an_inventory_takes_one_date_or_all_three(workspace, monkeypatch, capsys):
    # Defender D7.2 / v03: two dates are neither a per-date nor a carried rehearsal; refused before anything is read
    from weather.market import maker_replay_universe_v02
    root, bundles, _ = workspace
    monkeypatch.setattr(maker_replay_universe_v02, "universe", lambda *a, **k: pytest.fail("bundles were read"))
    code, _ = refused(capsys, ["rehearsal-inventory", "--out", root / "two-dates", *bundle_args(bundles, DAYS[:2])])
    assert code == "rehearsal_bundle_paths_invalid"


def test_derive_refuses_mislabelled_rehearsals(workspace, documents, capsys):
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
        code, _ = refused(capsys, ["derive", "--out", root / f"derive-refused-{i}", "--per-date", *dates,
                                   "--carried", carried_path])
        assert code.startswith(refusal)


def test_e7_fails_for_a_repeat_from_the_same_process(workspace, documents):
    # row 17: the in-process repeat has the same hash seed in force, so identical hashes do not pass E7
    root, _, _ = workspace
    per_date = ["--per-date", *(documents[d][0] for d in DAYS)]
    _, gate = call(root, "gate-report", "gate-same", *per_date, "--carried", documents["carried"][0],
                   "--repeat-rehearsal", documents["same-process"][0])
    e7 = gate["executability"]["gates"]["E7"]
    assert e7["status"] == "FAIL" and e7["separate_hash_seeds"] is False and all(e7["identical"].values())
    assert documents["repeat"][1]["environment"]["hash_seed"] == "1"
    assert documents[DAYS[1]][1]["environment"]["hash_seed"] == "0"


SECRET, KEY_SECRET = "0.918273645", "77123"


def _smuggled(source, target, mutate):
    doc = json.loads(source.read_text(encoding="utf-8"))
    mutate(doc)
    target.write_text(json.dumps(doc), encoding="utf-8")
    return target


@pytest.mark.parametrize("mutate, expected", [
    (lambda d: d["reachability"].update(f_cal=SECRET + " fills"), "rehearsal_whitelist:reachability.f_cal"),
    (lambda d: d["measured"]["records_by_kind"].update({KEY_SECRET: 1}),
     "rehearsal_whitelist:measured.records_by_kind.<key>"),
    (lambda d: d["reachability"]["decision_reasons"].update({"pnl": SECRET}),
     "rehearsal_whitelist:reachability.decision_reasons.pnl"),
    (lambda d: d.update({"x" + KEY_SECRET: SECRET}), "rehearsal_whitelist:<key>"),
    (lambda d: d.update(interpretation=SECRET), "rehearsal_whitelist:interpretation"),
])
@pytest.mark.parametrize("name", ["derive", "gate-report"])
def test_an_edited_document_is_refused_on_read_and_nothing_of_it_is_printed_or_written(
        workspace, documents, capsys, tmp_path, mutate, expected, name):
    # row 16: the typed schema is re-checked on read, and a refusal is a code only on stderr: the smuggled value
    # (and a smuggled key) is in no output stream and no written file
    carried = _smuggled(documents["carried"][0], tmp_path / "carried.json", mutate)
    out = tmp_path / "out"
    extra = ["--repeat-rehearsal", documents["repeat"][0]] if name == "gate-report" else []
    code, stdout = refused(capsys, [name, "--out", out, "--per-date", *(documents[d][0] for d in DAYS),
                                    "--carried", carried, *extra])
    assert code == expected
    written = b"".join(p.read_bytes() for p in out.rglob("*") if p.is_file())
    for secret in (SECRET, KEY_SECRET):
        assert secret not in code and secret not in stdout and secret.encode() not in written


def test_an_exception_or_a_warning_prints_no_text(documents, capsys, monkeypatch, tmp_path):
    def leaky(args):
        warnings.warn("pnl " + SECRET)
        raise KeyError("fills " + SECRET)
    monkeypatch.setattr(rehearse_cli, "derive", leaky)
    code, _ = refused(capsys, ["derive", "--out", tmp_path / "leak", "--per-date", *(documents[d][0] for d in DAYS),
                               "--carried", documents["carried"][0]])
    assert code == "error:KeyError"
    monkeypatch.setattr(rehearse_cli, "derive", lambda args: dict(nested=[dict(pnl=SECRET)]))
    code, _ = refused(capsys, ["derive", "--out", tmp_path / "out-key"])
    assert code == "rehearsal_output_forbidden_key"
    assert not list((tmp_path / "out-key").iterdir())


@pytest.mark.parametrize("text, code", [
    ("rehearsal_whitelist:measured.records_by_kind.<key>", "rehearsal_whitelist:measured.records_by_kind.<key>"),
    ("rehearsal_whitelist:dates[2]", "rehearsal_whitelist:dates[2]"),
    ("e7_not_comparable:environment.source_sha256", "e7_not_comparable:environment.source_sha256"),
    ("gate_per_date_rehearsal_required:2026-09-27", "gate_per_date_rehearsal_required:2026-09-27"),
    ("gate_evidence_invalid:E1", "gate_evidence_invalid:E1"),
    ("rehearsal_whitelist:" + SECRET, "rehearsal_whitelist:<key>.<key>"),
    ("rehearsal_whitelist:x" + KEY_SECRET, "rehearsal_whitelist:<key>"),
    ("Pnl " + SECRET, "error:BundleError"),
])
def test_a_refusal_code_echoes_only_known_names(text, code):
    assert rehearse_cli.refusal_code(BundleError(text)) == code
