"""Rehearsal output contract (registration §9; U2): calibration-date guard, pass projection, whitelist."""
from __future__ import annotations

import copy
import inspect
from datetime import date
from pathlib import Path

import pytest

from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.v2 import rehearsal
from maker_core.replay.v2.engine import EngineV2


def document():
    return dict(format=rehearsal.FORMAT, mode="carried", dates=[d.isoformat() for d in CALIBRATION_DATES],
                hazard_variant="max_m", calibration_sha256="c" * 64, measured_at="2026-10-13T12:00:00+00:00",
                interpretation=rehearsal.INTERPRETATION,
                measured=dict(input_bytes=1, records=2, records_by_kind={"book": 1, "descriptor": 1}, wakes=3,
                              decisions=4, span_runs=5, report_bytes=6, sidecar_bytes=7,
                              runtime_seconds=9.5, peak_memory_above_baseline_bytes=10, baseline_memory_bytes=11),
                hashes=dict(input_hashes={"2026-09-27": {"descriptor": "d" * 64}}, report_sha256="e" * 64,
                            sidecar_sha256="f" * 64, decision_sha256=["a" * 64]),
                reachability=dict(status="PASS", f_cal="0.61", screen_pass_rate="0.4",
                                  decision_reasons={"QUOTE": 3, "net_screen": 2},
                                  quoted_fraction={"blind_re1": "0.9", "clock_only": "0.5"}, n_cal=100, l_cal=12,
                                  expected_clock_removed="4.68"))


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
