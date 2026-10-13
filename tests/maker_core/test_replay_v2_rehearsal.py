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
    passes = [dict(policy=p, fill_bound=b, instants=10, wakes=20, timer_pops=3, stale_timers=0, decisions=5,
                   intervals=2, decision_sha256="a" * 64)
              for p in ("informed_v0", "blind_re1") for b in ("strictly_through", "touch")]
    return dict(format=rehearsal.FORMAT, mode="carried", dates=[d.isoformat() for d in CALIBRATION_DATES],
                hazard_variant="max_m", calibration_sha256="c" * 64, measured_at="2026-10-13T12:00:00+00:00",
                interpretation=rehearsal.INTERPRETATION,
                measured=dict(input_bytes=1, records=2, records_by_kind={"book": 1, "descriptor": 1}, wakes=3,
                              decisions=4, span_runs=5, report_bytes=6, sidecar_bytes=7, sidecar_records=8,
                              runtime_seconds=9.5, peak_memory_above_baseline_bytes=10, baseline_memory_bytes=11),
                passes=passes,
                clock=dict(rounds=3, matches={"strictly_through": dict(status="MATCHED", attempts=2)}),
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
    lambda d: d["passes"][2],
    lambda d: d["clock"]["matches"]["strictly_through"],
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
    (lambda d: d["passes"][0].update(day_roll={}), "passes[0].day_roll"),
    (lambda d: d["clock"]["matches"].update(touch=dict(status="MATCHED", attempts=1, fraction=0.3)),
     "clock.matches.touch.fraction"),
    (lambda d: d.update(passes={"x": 1}), "passes.x"),
    (lambda d: d.update(measured=[1]), "measured"),
])
def test_unknown_keys_and_wrong_shapes_refuse_at_their_path(mutate, path):
    doc = document()
    mutate(doc)
    with pytest.raises(BundleError, match="rehearsal_whitelist:" + path.replace("[", r"\[").replace("]", r"\]")):
        rehearsal.whitelisted(doc)


def test_project_pass_drops_scores_from_a_real_engine_summary():
    source = inspect.getsource(EngineV2.summary)
    for key in rehearsal.PASS_KEYS:
        assert f"{key}=" in source, key  # every projected key exists in the engine's summary
    full = {k: 1 for k in rehearsal.PASS_KEYS} | dict(fills=7, final_cash=3.5, exclusions={"x": 1},
                                                      exclusions_sha256="0" * 64, day_roll=None)
    projected = rehearsal.project_pass(full)
    assert set(projected) == set(rehearsal.PASS_KEYS)
    assert not set(projected) & rehearsal.FORBIDDEN
    with pytest.raises(BundleError, match="rehearsal_pass_summary_incomplete"):
        rehearsal.project_pass({k: 1 for k in rehearsal.PASS_KEYS[:-1]})


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
