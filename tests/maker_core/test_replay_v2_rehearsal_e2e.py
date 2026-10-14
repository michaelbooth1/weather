"""End-to-end score-free rehearsal on fictional calibration bundles (registration §9, §10 E5-E7; U2 part 2).

The bundles are ``fixtures.panel_v02`` fictional v0.2 days on the real calibration dates; no captured data is read.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from collections import Counter
import itertools

import pytest

from maker_core.replay import bundle_v02
from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.clarification_3 import quote_presence
from maker_core.replay.v2 import ceilings, reachability, rehearsal
from maker_core.replay.v2.pull import pull_endpoint

from .fixtures.panel_v02 import Panel

NOW = datetime(2026, 10, 13, 17, tzinfo=timezone.utc)
CAL = "c" * 64
REPLICATES = 100  # the bootstrap floor (pull_efficiency); the rehearsal itself defaults to 2000


def fixture():
    return Panel(bands=1, step=5, full=True, capture_minutes=range(0, 600))


@pytest.fixture(scope="module")
def calibration(tmp_path_factory):
    panel = fixture()
    root = tmp_path_factory.mktemp("calibration")
    paths = {d: panel.write(root / d.isoformat(), d, provenance="captured") for d in CALIBRATION_DATES}
    return panel, paths, panel.inventory


def memory_probe(step=1000):
    """A fake ``process_memory``: the peak grows by ``step`` per call, so above-baseline is ``step``."""
    counter = itertools.count(1)
    return lambda: (0, next(counter) * step)


def rehearse(paths, inventory, mode, **overrides):
    options = dict(mode=mode, hazard_per_minute=.001, calibration_sha256=CAL, now=NOW, replicates=REPLICATES,
                   memory=memory_probe())
    options.update(overrides)
    return rehearsal.rehearse(paths, inventory, **options)


@pytest.fixture(scope="module")
def per_date(calibration):
    _, paths, inventory = calibration
    return {d.isoformat(): rehearse([paths[d]], inventory([d]), "per_date") for d in CALIBRATION_DATES}


def test_a_per_date_rehearsal_is_whitelisted_and_measures_the_whole_pipeline(per_date):
    doc = per_date[CALIBRATION_DATES[0].isoformat()]
    assert rehearsal.whitelisted(doc) is doc
    assert doc["format"] == rehearsal.FORMAT and doc["mode"] == "per_date"
    assert doc["dates"] == [CALIBRATION_DATES[0].isoformat()]
    assert doc["report_status"] == "FIXTURE_ONLY" and doc["replicates"] == REPLICATES
    measured = doc["measured"]
    assert set(measured) == set(rehearsal.MEASURED_KEYS)
    assert sum(measured["records_by_kind"].values()) == measured["records"] > 0
    assert {"book", "descriptor"} <= set(measured["records_by_kind"])
    assert measured["decisions"] > 0 and measured["wakes"] > 0 and measured["span_runs"] > 0
    assert measured["report_bytes"] > 0 and measured["sidecar_bytes"] > 0
    assert measured["peak_memory_above_baseline_bytes"] == 1000
    assert not {"passes", "clock"} & set(doc)  # §9: per-pass and matched-clock rows are not recorded (D3.1)


def test_nothing_scored_is_in_the_document(per_date):
    text = repr(per_date)
    for key in ("fills", "final_cash", "band_days", "scores", "registered_decision", "exclusions_sha256"):
        assert f"'{key}'" not in text


@pytest.fixture(scope="module")
def repeat(calibration):
    _, paths, inventory = calibration
    day = CALIBRATION_DATES[1]
    return rehearse([paths[day]], inventory([day]), "per_date")


@pytest.fixture(scope="module")
def carried(calibration):
    """The carried max_m rehearsal, with the run and the decision counts ``reachability.block`` read (captured)."""
    _, paths, inventory = calibration
    seen = {}
    block = reachability.block

    def capture(run, counts, **kwargs):
        seen.update(run=run, counts=Counter(counts))
        return block(run, counts, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(reachability, "block", capture)
        doc = rehearse([paths[d] for d in reversed(CALIBRATION_DATES)], inventory(CALIBRATION_DATES), "carried")
    return doc, seen


def test_two_rehearsals_of_one_date_are_byte_identical_e7(per_date, repeat):
    day = CALIBRATION_DATES[1]
    again = repeat
    first = per_date[day.isoformat()]
    assert again["hashes"] == first["hashes"]
    for key in set(rehearsal.MEASURED_KEYS) - {"runtime_seconds"}:
        assert again["measured"][key] == first["measured"][key], key


def test_the_carried_run_feeds_the_ceiling_rule_and_e5(per_date, carried):
    carried, _ = carried
    assert carried["dates"] == [d.isoformat() for d in CALIBRATION_DATES]
    assert carried["measured"]["records"] == sum(d["measured"]["records"] for d in per_date.values())
    assert carried["measured"]["input_bytes"] == sum(d["measured"]["input_bytes"] for d in per_date.values())
    rows = {day: rehearsal.ceiling_input(doc) for day, doc in per_date.items()}
    derived = ceilings.derive(rows, rehearsal.ceiling_input(carried))
    assert derived["executable"] is True and derived["host_limit_binding"] == []
    largest = max(r["records"] for r in rows.values())
    assert derived["ceilings"]["records"] == ceilings.next_power_of_two(ceilings.N * largest)
    assert ceilings.e5_memory(rows, rehearsal.ceiling_input(carried), derived)["status"] == "PASS"
    limits = ceilings.run_limits(derived)
    assert limits["max_records"] >= carried["measured"]["records"]


def test_a_non_calibration_path_refuses_before_any_bundle_is_opened(calibration, monkeypatch, tmp_path):
    _, paths, inventory = calibration
    inventory = inventory(CALIBRATION_DATES)
    monkeypatch.setattr(bundle_v02, "open_stream_bundle", lambda *a, **k: pytest.fail("a bundle was opened"))
    with pytest.raises(BundleError, match="rehearsal_restricted_to_calibration_dates"):
        rehearse([tmp_path / "2026-10-02" / "bundle"], inventory, "per_date")
    with pytest.raises(BundleError, match="rehearsal_per_date_requires_one_date"):
        rehearse([paths[d] for d in CALIBRATION_DATES[:2]], inventory, "per_date")
    with pytest.raises(BundleError, match="rehearsal_carried_requires_the_three_calibration_dates"):
        rehearse([paths[d] for d in CALIBRATION_DATES[:2]], inventory, "carried")
    with pytest.raises(BundleError, match="rehearsal_duplicate_date"):
        rehearse([paths[CALIBRATION_DATES[0]]] * 3, inventory, "carried")
    with pytest.raises(BundleError, match="rehearsal_hazard_variant_invalid"):
        rehearse([paths[CALIBRATION_DATES[0]]], inventory, "per_date", hazard_variant="per_band")


def test_a_bundle_whose_manifest_names_another_day_refuses(calibration, tmp_path):
    panel, _, inventory = calibration
    inventory = inventory(CALIBRATION_DATES[:1])
    moved = panel.write(tmp_path / CALIBRATION_DATES[1].isoformat(), CALIBRATION_DATES[0], provenance="captured")
    with pytest.raises(BundleError, match="rehearsal_restricted_to_calibration_dates"):
        rehearse([moved], inventory, "per_date")


def test_ceiling_input_refuses_an_incomplete_or_foreign_document(per_date):
    doc = dict(per_date[CALIBRATION_DATES[0].isoformat()])
    with pytest.raises(BundleError, match="rehearsal_format_invalid"):
        rehearsal.ceiling_input(dict(doc, format="maker_core.replay.rehearsal.v1"))
    measured = dict(doc["measured"])
    del measured["span_runs"]
    with pytest.raises(BundleError, match="incomplete_ceiling_measurement"):
        rehearsal.ceiling_input(dict(doc, measured=measured))
    assert set(rehearsal.ceiling_input(doc)) == set(ceilings.MEASURED)


def test_an_undeclared_source_refuses_before_the_relabel(calibration, monkeypatch):
    # Defender D3.2 / m06: the relabel to ``synthetic`` is only for declared sources. A synthetic, undeclared
    # source (every envelope active) would otherwise run through the whole pipeline unrefused.
    from maker_core.replay.v2 import intervals
    _, paths, inventory = calibration
    day = CALIBRATION_DATES[0]
    real = intervals.sources

    def undeclared(*args, **kwargs):
        declared, rest = real(*args, **kwargs)
        return [replace(s, plan=replace(s.plan, provenance="synthetic", declared=False)) for s in declared], rest

    monkeypatch.setattr(intervals, "sources", undeclared)
    with pytest.raises(BundleError, match="rehearsal_requires_declared_intervals"):
        rehearse([paths[day]], inventory([day]), "per_date")


def test_a_record_count_that_disagrees_with_the_replay_refuses(calibration, monkeypatch):
    # Defender D3.2 / m11: records-by-kind must count every replayed record; a count that skips one refuses.
    _, paths, inventory = calibration
    day = CALIBRATION_DATES[0]
    real = rehearsal._counting

    def skipping(source, counts, done):
        counted = real(source, counts, done)

        def records():
            first = source.plan.day not in done
            for i, record in enumerate(counted.records()):
                if first and i == 0:
                    counts[record.kind] -= 1  # one record goes uncounted
                yield record
        return replace(counted, records=records)

    monkeypatch.setattr(rehearsal, "_counting", skipping)
    with pytest.raises(BundleError, match="rehearsal_record_count_mismatch"):
        rehearse([paths[day]], inventory([day]), "per_date")


# -- §11 reachability and the E1-E8 gate report (U3) -------------------------------------------------------------------

def test_only_the_carried_rehearsal_carries_the_reachability_block(per_date, carried):
    doc, seen = carried
    assert all("reachability" not in d for d in per_date.values())
    reach = doc["reachability"]
    assert set(reach) == set(rehearsal.REACHABILITY_KEYS)
    assert doc["hazard_variant"] == "max_m" and doc["hazard_map_sha256"] is None
    f_cal = reachability.D(reach["f_cal"])
    assert 0 <= f_cal <= 1
    assert reach["status"] == ("PASS" if f_cal >= reachability.THRESHOLD else "FAIL")
    assert set(reach["quoted_fraction"]) == set(reachability.QUOTED_FRACTION_POLICIES)
    assert reach["quoted_fraction"]["informed-v0"]["quoted_fraction"] == reach["f_cal"]
    # the fixture's 5-minute captures leave no 5-minute endpoint inside the 120 s tolerance, so N_cal may be 0 here;
    # the counting itself is pinned in test_replay_v2_reachability
    assert 0 <= reach["l_cal"] <= reach["n_cal"] <= reach["pull_candidates"] and reach["pull_candidates"] > 0
    assert reach["n_cal"] + sum(reach["opportunity_exclusions"].values()) == reach["pull_candidates"]
    removed = reachability.D(reach["l_cal"]) * (1 - f_cal)
    assert reach["expected_clock_removed"]["calibration"] == str(removed)
    assert reach["expected_clock_removed"]["panel"] == str(removed * reachability.PANEL_SCALE)
    informed = seen["run"].passes["strictly_through"]["informed-v0"].engine.summary()["decisions"]
    assert sum(reach["decision_reasons"].values()) == informed > 0
    assert reach["screen_pass_rate"]["reached"] <= informed


def test_f_cal_is_clarification_3_quote_presence_and_n_cal_bounds_the_pull_endpoint(carried):
    doc, seen = carried
    run = seen["run"]
    rows = {p: run.passes["strictly_through"][p].band_days(run.books, run.markets)
            for p in reachability.QUOTED_FRACTION_POLICIES}
    presence = quote_presence(rows)
    for policy, row in doc["reachability"]["quoted_fraction"].items():
        pooled = presence[policy]["pooled"]
        assert row["eligible_seconds"] == str(pooled["eligible_seconds"])
        assert reachability.D(row["quoted_fraction"]) == pooled["quoted_fraction"]
    passes = run.passes["strictly_through"]
    endpoint = pull_endpoint(run.plan, passes["informed-v0"].scorer, passes["clock_only"].scorer, run.books,
                             run.matches["strictly_through"], replicates=REPLICATES)
    assert endpoint["candidates"] == doc["reachability"]["pull_candidates"]
    assert endpoint["counts"]["opportunities"] <= doc["reachability"]["n_cal"]
    assert endpoint["counts"]["large_moves"] <= doc["reachability"]["l_cal"]


def test_r1_with_the_scalar_for_every_market_is_identical_to_max_m(carried, calibration):
    """The R1 hook is neutral when every market reads the scalar: the carried run is identical to max_m's."""
    doc, _ = carried
    _, paths, inventory = calibration
    rows = inventory(CALIBRATION_DATES)
    same = {r["market_id"]: .001 for r in rows}
    r1 = rehearse([paths[d] for d in CALIBRATION_DATES], rows, "carried", hazard_variant="r1_per_city",
                  hazard_by_market=same)
    assert r1["hashes"]["decision_sha256"] == doc["hashes"]["decision_sha256"]
    assert r1["reachability"] == doc["reachability"]
    assert r1["hazard_map_sha256"] is not None


def test_r1_changes_the_hazard_each_city_reads(carried, calibration):
    doc, _ = carried
    _, paths, inventory = calibration
    rows = inventory(CALIBRATION_DATES)
    markets = sorted({r["market_id"] for r in rows})
    harsh = {m: (1.0 if m == markets[0] else .001) for m in markets}
    r1 = rehearse([paths[d] for d in CALIBRATION_DATES], rows, "carried", hazard_variant="r1_per_city",
                  hazard_by_market=harsh)
    assert r1["hashes"]["decision_sha256"] != doc["hashes"]["decision_sha256"]
    assert reachability.D(r1["reachability"]["f_cal"]) <= reachability.D(doc["reachability"]["f_cal"])
    assert r1["reachability"]["decision_reasons"].get("NO_QUOTE:NONPOSITIVE_NET", 0) > \
        doc["reachability"]["decision_reasons"].get("NO_QUOTE:NONPOSITIVE_NET", 0)
    with pytest.raises(BundleError, match="r1_hazard_market_missing"):
        rehearse([paths[d] for d in CALIBRATION_DATES], rows, "carried", hazard_variant="r1_per_city",
                 hazard_by_market={markets[0]: .001})
    with pytest.raises(BundleError, match="max_m_takes_no_hazard_map"):
        rehearse([paths[d] for d in CALIBRATION_DATES], rows, "carried", hazard_by_market=harsh)


def test_the_gate_report_reads_e2_e4_e5_e6_e7_and_section_11_and_waits_for_e1_e3_e8(per_date, carried, repeat):
    doc, _ = carried
    report = reachability.gate_report(per_date, doc, repeat)
    gates = report["executability"]["gates"]
    for name in ("E2", "E4", "E5", "E7"):
        assert gates[name]["status"] == "PASS", name
    # E6's max_events clause is not evaluable until the owner rules (§9 derives no max_events): never PASS (D6.2)
    assert gates["E6"]["status"] == "INCOMPLETE"
    assert report["executability"]["status"] == "INCOMPLETE"
    assert report["executability"]["not_supplied"] == ["E1", "E3", "E8"]
    assert report["executability"]["not_evaluated"] == ["E6"]
    assert gates["E7"]["identical"] == dict(decision_sha256=True, report_sha256=True, sidecar_sha256=True)
    assert gates["E6"]["projected_pull_candidates"] == doc["reachability"]["pull_candidates"] * ceilings.N // 3
    evidence = {k: dict(status="PASS", evidence="fixture") for k in ("e1", "e3", "e8")}
    supplied = reachability.gate_report(per_date, doc, repeat, **evidence)["executability"]
    assert supplied["status"] == "INCOMPLETE" and supplied["not_supplied"] == [] and supplied["not_evaluated"] == ["E6"]
    failed = dict(evidence, e3=dict(status="FAIL", evidence="fixture"))
    assert reachability.gate_report(per_date, doc, repeat, **failed)["executability"]["status"] == "FAIL"
    verdict = report["reachability"]["verdict"]
    assert verdict == reachability.verdict(doc["reachability"]["status"])
    text = repr(report)
    for key in ("fills", "final_cash", "band_days", "scores", "pnl", "markout"):
        assert f"'{key}'" not in text


def test_the_gate_report_refuses_mislabelled_rehearsals(per_date, carried, repeat):
    doc, _ = carried
    day = CALIBRATION_DATES[0].isoformat()
    with pytest.raises(BundleError, match="gate_carried_rehearsal_required:max_m"):
        reachability.gate_report(per_date, per_date[day], repeat)
    with pytest.raises(BundleError, match="gate_per_date_rehearsal_required"):
        reachability.gate_report(dict(per_date, **{day: doc}), doc, repeat)
    with pytest.raises(BundleError, match="gate_repeat_rehearsal_required"):
        reachability.gate_report(per_date, doc, doc)
    with pytest.raises(BundleError, match="gate_carried_rehearsal_required:r1_per_city"):
        reachability.gate_report(per_date, doc, repeat, r1=doc)
    with pytest.raises(BundleError, match="gate_evidence_invalid:E1"):
        reachability.gate_report(per_date, doc, repeat, e1=dict(status="MAYBE", evidence="x"))


def test_e6_fails_when_the_ceilings_are_not_executable(per_date, carried, repeat, monkeypatch):
    doc, _ = carried
    real = ceilings.derive
    monkeypatch.setattr(ceilings, "derive", lambda *a, **k: dict(real(*a, **k), executable=False))
    report = reachability.gate_report(per_date, doc, repeat)
    assert report["executability"]["gates"]["E6"]["status"] == "FAIL"
    assert report["executability"]["status"] == "FAIL"


F_CAL = {"PASS": "0.6", "FAIL": "0.3", "UNIDENTIFIED": None}  # a fabricated f_cal consistent with each status


def _with_status(doc, status, variant=None):
    copy = dict(doc, reachability=dict(doc["reachability"], status=status, f_cal=F_CAL[status]))
    return copy if variant is None else dict(copy, hazard_variant=variant)


@pytest.mark.parametrize("max_m, r1, outcome", [
    ("PASS", None, "PASS"),
    ("FAIL", None, "FAIL_R1_NOT_RUN"),
    ("FAIL", "PASS", "PASS_UNDER_R1"),
    ("FAIL", "FAIL", "FAIL"),
    ("FAIL", "UNIDENTIFIED", "FAIL"),
    ("UNIDENTIFIED", None, "UNIDENTIFIED"),
    ("UNIDENTIFIED", "PASS", "UNIDENTIFIED"),
])
def test_the_gate_report_verdict_passes_only_on_pass(per_date, carried, repeat, max_m, r1, outcome):
    # D6.1 (u03/u04): fabricated statuses through the whole gate report; UNIDENTIFIED is never a pass
    doc, _ = carried
    r1_doc = None if r1 is None else _with_status(doc, r1, "r1_per_city")
    report = reachability.gate_report(per_date, _with_status(doc, max_m), repeat, r1=r1_doc)
    assert report["reachability"]["verdict"] == outcome


@pytest.mark.parametrize("status, f_cal", [("PASS", "0.3"), ("FAIL", "0.5"), ("PASS", None), ("UNIDENTIFIED", "0.6")])
def test_the_gate_report_recomputes_the_section_11_status(per_date, carried, repeat, status, f_cal):
    # Defender re-check: a stale or hand-edited status that disagrees with its own f_cal refuses
    doc, _ = carried
    edited = dict(doc, reachability=dict(doc["reachability"], status=status, f_cal=f_cal))
    with pytest.raises(BundleError, match="gate_reachability_status_mismatch:max_m"):
        reachability.gate_report(per_date, edited, repeat)
    with pytest.raises(BundleError, match="gate_reachability_status_mismatch:r1_per_city"):
        reachability.gate_report(per_date, _with_status(doc, "FAIL"), repeat,
                                 r1=dict(edited, hazard_variant="r1_per_city"))
