"""Rehearsal output contract (registration §9; U2): calibration-date guard, pass projection, whitelist.

Guards: maker replay v2 rehearsal output contract and calibration-date guard (docs/research/maker-replay-v2-registration-DRAFT.md, section 9).
"""
from __future__ import annotations

import copy
import inspect
from datetime import date
from pathlib import Path

import pytest

from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.v2 import reachability, rehearsal
from maker_core.replay.v2.engine import EngineV2


def document():
    """A carried document with every field the pipeline writes, in its real shape and type (row 16)."""
    return dict(format=rehearsal.FORMAT, mode="carried", dates=[d.isoformat() for d in CALIBRATION_DATES],
                hazard_variant="max_m", calibration_sha256="c" * 64, measured_at="2026-09-29T12:00:00+00:00",
                interpretation=rehearsal.INTERPRETATION, report_status="FIXTURE_ONLY", replicates=100,
                hazard_per_minute=.001, hazard_map_sha256=None, inventory_sha256="b" * 64, pull_candidates=40,
                measured=dict(input_bytes=1, records=2, records_by_kind={"book": 1, "descriptor": 1}, wakes=3,
                              decisions=4, span_runs=5, report_bytes=6, sidecar_bytes=7,
                              runtime_seconds=9.5, peak_memory_above_baseline_bytes=10, baseline_memory_bytes=11),
                hashes=dict(input_hashes={"2026-09-27": {"bundle.json": "d" * 64, "book.jsonl": "a" * 64}},
                            report_sha256="e" * 64, sidecar_sha256="f" * 64, decision_sha256="a" * 64),
                reachability=dict(status="PASS", f_cal="0.61",
                                  screen_pass_rate=dict(reached=5, passed=2, rate="0.4",
                                                        reading=reachability.SCREEN_READING),
                                  decision_reasons={"QUOTE:INFORMED_QUOTE": 3, "NO_QUOTE:NONPOSITIVE_NET": 2},
                                  quoted_fraction={p: dict(eligible_seconds="10.000000", quoted_seconds="6.1",
                                                           quoted_fraction="0.61")
                                                   for p in reachability.QUOTED_FRACTION_POLICIES},
                                  n_cal=100, l_cal=12,
                                  expected_clock_removed=dict(calibration="4.68", panel="21.84",
                                                              panel_scale=reachability.PANEL_SCALE_TEXT)),
                environment=dict(source_sha256="9" * 64, python="3.11.9", numpy="2.4.6", scipy="1.17.1",
                                 thread_pins={k: "1" for k in rehearsal.THREAD_PINS}, hash_seed="0",
                                 hash_probe=-123))


def test_a_complete_document_is_whitelisted():
    doc = document()
    assert rehearsal.whitelisted(doc) is doc


@pytest.mark.parametrize("where", [
    lambda d: d,
    lambda d: d["measured"],
    lambda d: d["hashes"]["input_hashes"],  # a free-form leaf still refuses a forbidden key
    lambda d: d["reachability"]["decision_reasons"],
])
@pytest.mark.parametrize("key", ["fills", "final_cash", "scores", "markout", "contrast", "exclusions"])
def test_a_smuggled_score_key_anywhere_refuses(where, key):
    doc = document()
    where(doc)[key] = 0
    with pytest.raises(BundleError, match="rehearsal_whitelist:"):
        rehearsal.whitelisted(doc)


@pytest.mark.parametrize("mutate, path", [
    (lambda d: d.update(extra=1), "extra"),
    (lambda d: d["measured"].update(engine_events=1), "measured.engine_events"),
    (lambda d: d["hashes"].update(passes=[]), "hashes.passes"),
    (lambda d: d.update(measured=[1]), "measured"),
])
def test_unknown_keys_and_wrong_shapes_refuse_at_their_path(mutate, path):
    doc = document()
    mutate(doc)
    with pytest.raises(BundleError, match="rehearsal_whitelist:" + path.replace("[", r"\[").replace("]", r"\]")):
        rehearsal.whitelisted(doc)


@pytest.mark.parametrize("mutate, path", [
    (lambda d: d.update(passes=[dict(policy="informed-v0", fill_bound="touch", decisions=5)]), "passes"),
    (lambda d: d.update(clock=dict(rounds=3)), "clock"),
    (lambda d: d["measured"].update(sidecar_records=8), "measured.sidecar_records"),
])
def test_outputs_outside_the_s9_list_refuse(mutate, path):
    # Defender D3.1: §9 "Record only these outputs". Per-pass rows (policy x fill bound), matched-clock rounds and
    # status, and the sidecar record count are not on it, so a document carrying them refuses.
    doc = document()
    mutate(doc)
    with pytest.raises(BundleError, match="rehearsal_whitelist:" + path + "$"):
        rehearsal.whitelisted(doc)


def test_the_decision_digest_reads_a_key_the_engine_summary_has():
    assert "decision_sha256=" in inspect.getsource(EngineV2.summary)


@pytest.mark.parametrize("path", ["data/88a/2026-09-30/bundle", "x/2026-10-14", "x/2026-09-26/bundle", "x/bundle",
                                  "x/not-a-date"])
def test_non_calibration_paths_refuse_from_the_name_alone(path, tmp_path):
    # the path does not exist: the refusal is from its text, before anything is opened
    with pytest.raises(BundleError, match="rehearsal_restricted_to_calibration_dates"):
        rehearsal.calibration_day(tmp_path / path)


def test_calibration_paths_name_their_date():
    assert rehearsal.calibration_day(Path("r/2026-09-28/bundle")) == date(2026, 9, 28)
    assert rehearsal.calibration_day(Path("r/2026-09-29")) == date(2026, 9, 29)


def test_modes():
    days = list(CALIBRATION_DATES)
    assert rehearsal.check_mode("per_date", days[:1]) == days[:1]
    assert rehearsal.check_mode("carried", days) == days
    with pytest.raises(BundleError, match="rehearsal_per_date_requires_one_date"):
        rehearsal.check_mode("per_date", days)
    with pytest.raises(BundleError, match="rehearsal_carried_requires_the_three_calibration_dates"):
        rehearsal.check_mode("carried", days[::-1])
    with pytest.raises(BundleError, match="rehearsal_mode_invalid"):
        rehearsal.check_mode("sampled", days)


def test_the_document_is_not_mutated_by_the_check():
    doc = document()
    before = copy.deepcopy(doc)
    rehearsal.whitelisted(doc)
    assert doc == before


@pytest.mark.parametrize("mutate, path", [
    # a value smuggled under an allowed name in another shape or type (CONSOLIDATED row 16)
    (lambda d: d.update(interpretation="fills 12.5"), "interpretation"),
    (lambda d: d.update(format="maker_core.replay.v2.rehearsal.v9"), "format"),
    (lambda d: d.update(calibration_sha256="0.6123"), "calibration_sha256"),
    (lambda d: d.update(measured_at="P&L 0.61"), "measured_at"),
    (lambda d: d.update(replicates=1.5), "replicates"),
    (lambda d: d.update(replicates=True), "replicates"),
    (lambda d: d.update(pull_candidates=-1), "pull_candidates"),
    (lambda d: d.update(hazard_per_minute=1.5), "hazard_per_minute"),
    (lambda d: d.update(dates=["2026-09-26"]), r"dates\[0\]"),
    (lambda d: d["measured"].update(records={"x": 1}), "measured.records"),  # a structure under a leaf
    (lambda d: d["measured"].update(runtime_seconds=float("nan")), "measured.runtime_seconds"),
    (lambda d: d["measured"]["records_by_kind"].update(pnl_0_61=1), r"measured.records_by_kind.<key>"),
    (lambda d: d["measured"]["records_by_kind"].update(book="12.5"), "measured.records_by_kind.book"),
    (lambda d: d["hashes"].update(decision_sha256=["a" * 64]), "hashes.decision_sha256"),
    (lambda d: d["hashes"]["input_hashes"].update({"2026-09-26": {}}), "hashes.input_hashes.<key>"),
    (lambda d: d["hashes"]["input_hashes"]["2026-09-27"].update({"x.txt": "a" * 64}),
     "hashes.input_hashes.2026-09-27.<key>"),
    (lambda d: d["reachability"].update(f_cal=0.61), "reachability.f_cal"),
    (lambda d: d["reachability"].update(f_cal="0.61 fills"), "reachability.f_cal"),
    (lambda d: d["reachability"].update(screen_pass_rate="0.4"), "reachability.screen_pass_rate"),
    (lambda d: d["reachability"]["screen_pass_rate"].update(reading="pnl 3"), "reachability.screen_pass_rate.reading"),
    (lambda d: d["reachability"]["decision_reasons"].update({"net 0.61": 1}), "reachability.decision_reasons.<key>"),
    (lambda d: d["reachability"]["quoted_fraction"].update(oracle={}), "reachability.quoted_fraction.<key>"),
    (lambda d: d["reachability"]["quoted_fraction"]["blind_re1"].update(quoted_fraction=0.9),
     "reachability.quoted_fraction.blind_re1.quoted_fraction"),
    (lambda d: d["reachability"].update(expected_clock_removed="4.68"), "reachability.expected_clock_removed"),
    (lambda d: d["environment"].update(hash_seed="seed"), "environment.hash_seed"),
    (lambda d: d["environment"]["thread_pins"].update(OPENBLAS_NUM_THREADS="0.61"),
     "environment.thread_pins.OPENBLAS_NUM_THREADS"),
])
def test_every_leaf_has_its_type_and_every_data_key_its_shape(mutate, path):
    doc = document()
    mutate(doc)
    with pytest.raises(BundleError, match="rehearsal_whitelist:" + path + "$"):
        rehearsal.whitelisted(doc)


def test_nullable_leaves_take_none():
    doc = document()
    doc["reachability"].update(f_cal=None, status="UNIDENTIFIED", expected_clock_removed=None)
    doc["reachability"]["screen_pass_rate"]["rate"] = None
    doc["environment"].update(numpy=None, hash_seed="random")
    assert rehearsal.whitelisted(doc) is doc


def test_the_environment_records_the_sources_versions_pins_and_the_seed_in_force():
    env = rehearsal.environment({"PYTHONHASHSEED": "7", "OPENBLAS_NUM_THREADS": "1"})
    assert env["hash_seed"] == "7" and env["hash_probe"] == hash(rehearsal.HASH_PROBE)
    assert env["thread_pins"]["OPENBLAS_NUM_THREADS"] == "1" and env["thread_pins"]["OMP_NUM_THREADS"] is None
    assert rehearsal.environment({})["hash_seed"] == "random"
    assert env["source_sha256"] == rehearsal.environment({})["source_sha256"]
    rehearsal.whitelisted(dict(environment=env))
