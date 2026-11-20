"""Synthetic restart witnesses; no captured data or calibration study.

Guards: T123 Nov24 restart, owner-seen freeze gate, N68 denominator and block3.
"""

import math
import random
from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest

from tests.backtesting.test_low_ask_io import synthetic_freeze, write_pack
from weather.backtesting.low_ask.contracts import (
    CITIES, DATE_COUNT, FIRST, FREEZE_BEFORE, LAST, LOOK, UTC, Refusal,
    canonical, digest, schedule, trial_day,
)
from weather.backtesting.low_ask.inference import completeness, evaluate, interval
from weather.backtesting.low_ask.runner import validate_freeze


def test_authorized_endpoints_population_and_unopened_old_dates():
    assert FIRST == date(2026, 11, 24) and LAST == date(2027, 1, 30)
    assert FREEZE_BEFORE == datetime(2026, 11, 24, 5, tzinfo=UTC)
    assert LOOK == datetime(2027, 2, 9, 23, tzinfo=UTC)
    slots = list(schedule(LOOK))
    assert DATE_COUNT == 68 and len(slots) == 1632
    assert len({(city, day) for city, day, _, _ in slots}) == 816
    for day in ("2026-11-17", "2026-11-23", "2027-01-31"):
        with pytest.raises(Refusal, match="date_scope"):
            trial_day(day)


def test_historical_calibration_cli_refuses_restart_before_import_or_output(tmp_path, monkeypatch, capsys):
    from weather.backtesting import low_ask_calibration as calibration
    def forbid_libraries():
        pytest.fail("historical generator imported numerical libraries for N68")
    monkeypatch.setattr(calibration, "libraries", forbid_libraries)
    output = tmp_path / "uncreated-calibration"
    with pytest.raises(SystemExit) as stopped:
        calibration.main(["train", "--out", str(output)])
    assert stopped.value.code == 2
    assert "historical N75 calibration cannot certify" in capsys.readouterr().err
    assert not output.exists()


def test_partial_final_block_preserves_constant_and_scalar_resampling():
    constant = interval([[.5] * 12 for _ in range(68)], critical=3, resamples=128)
    for lower, upper in constant["intervals"].values():
        assert lower == upper == .5
    # Independent scalar construction checks the actual 68-draw distribution,
    # its random-stream interleaving, and the partial final circular block.
    daily = [((i * 7) % 17) / 10 - .5 for i in range(68)]
    mean = sum(daily) / 68
    rng = random.Random(20261110)
    draws = []
    for _ in range(128):
        for _ in range(68):
            rng.randrange(68)
        selected = []
        while len(selected) < 68:
            start = rng.randrange(68)
            selected.extend(((start + j) % 68) for j in range(min(3, 68 - len(selected))))
        draws.append(sum(daily[i] for i in selected) / 68 - mean)
        for _ in range(12):
            rng.randrange(12)
    draws.sort()
    result = interval([[v] * 12 for v in daily], critical=3, resamples=128)
    expected = [mean - draws[math.ceil(.9875 * 128) - 1],
                mean - draws[math.ceil(.0125 * 128) - 1]]
    assert result["intervals"]["block3"] == pytest.approx(expected, abs=1e-14)


@pytest.mark.parametrize("mutation,reason", [
    ("missing_confirmation", "fields"),
    ("unseen", "owner_seen_confirmation"),
    ("unconfirmed", "owner_seen_confirmation"),
    ("charter_changed", "charter_binding"),
    ("n75", "calibration_population"),
    ("old_statistic", "calibration_statistic"),
    ("unapproved_screen", "sha256"),
])
def test_restart_freeze_requires_master_evidence_and_matching_calibration(tmp_path, mutation, reason):
    _, manifest = write_pack(tmp_path)
    freeze = synthetic_freeze(manifest)
    now = datetime(2026, 11, 25, tzinfo=UTC)
    validate_freeze(freeze, digest(canonical(freeze)), now)
    if mutation == "missing_confirmation":
        del freeze["restart_authority"]
    elif mutation == "unseen":
        freeze["restart_authority"]["owner_seen_utc"] = "2026-11-21T00:00:00Z"
    elif mutation == "unconfirmed":
        freeze["restart_authority"]["master_confirmed_utc"] = "2026-11-21T00:00:00Z"
    elif mutation == "charter_changed":
        freeze["restart_authority"]["charter_sha256"] = "0" * 64
    elif mutation == "n75":
        freeze["calibration"].update(first_date="2026-11-17", date_count=75)
    elif mutation == "old_statistic":
        freeze["calibration"]["inference_sha256"] = "0" * 64
    elif mutation == "unapproved_screen":
        freeze["restart_authority"]["screen_only_disposition_sha256"] = None
    with pytest.raises(Refusal, match=reason):
        validate_freeze(freeze, digest(canonical(freeze)), now)


def full_coverage_ledger():
    return {"decisions": [
        {"target_date": (FIRST + timedelta(days=d)).isoformat(), "city": city, "cut": hour,
         "status": "resolved", "shares": "5", "conservative_net": ".5"}
        for d in range(68) for city in CITIES for hour in (17, 18)],
        "doubtful_fills": 0, "unresolved": 0}


def test_literal_completeness_gates_and_chicago_missing_cannot_pass():
    ledger = full_coverage_ledger()
    calibration = {"status": "CALIBRATED", "critical_value": "3"}
    family = {"F3-SIM-1": .03}
    def verdict(value):
        return evaluate(value, calibration=calibration, family_pvalues=family,
                        claimants=["F3-SIM-1", "LOW-ASK-1"], resamples=128)
    assert verdict(ledger)["verdict"] == "SUCCESS"
    for row in ledger["decisions"]:
        if row["city"] == "chicago":
            row.update(status="skip", reason="missing_event")
    counts = completeness(ledger)
    assert counts["adequate_dates"] == 68 and counts["both_executable_city_days"] == 748
    assert verdict(ledger)["verdict"] == "DESCRIBE"

    ledger = full_coverage_ledger()
    # Six missing city-days on distinct dates leave exactly 810. A seventh
    # leaves 809 while adequate dates stay 68: the literal gate must refuse.
    for missing in (6, 7):
        trial = deepcopy(ledger)
        for row in trial["decisions"]:
            if row["city"] == "chicago" and row["target_date"] < (FIRST + timedelta(days=missing)).isoformat():
                row.update(status="skip", reason="missing_event")
        assert verdict(trial)["both_executable_city_days"] == 816 - missing
        assert verdict(trial)["verdict"] == ("SUCCESS" if missing == 6 else "DESCRIBE")
