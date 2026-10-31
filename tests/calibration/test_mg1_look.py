"""MG-1 look receipt writer (``mg1_look_receipt/1``) and its registered entry point.

Guards: master's R3 ruling of 2026-10-26 on the B-1 binding: the MG-1 look receipt is written by code only, never by
hand; ``looked_at_utc`` is stamped by the clock immediately before the look's first outcome join (the start marker is
on disk before the loader runs); receipt and start marker are written in mode "x" at fixed ``weather.paths``
data paths keyed by the MG-1 rule sha; the entry point is registered by module name and source sha256 in
``MG1_CONFIRMATION_ENTRY_POINTS``; a hand-made or hand-edited receipt fails the checks B-1's VOID 5 runs.
"""
import json
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather import mg1_reserved_window as window
from weather import paths
from weather.calibration import mg1_look as m
from weather.schema_families import schema_version

ROOT = Path(__file__).resolve().parents[2]
RULE = ROOT / "docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md"
DATES = ["2026-10-15", "2026-11-28", "2026-10-20"]


@pytest.fixture(autouse=True)
def _root(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "LOOK_ROOT", tmp_path / "_mg1_look")
    monkeypatch.setattr(m, "head_commit", lambda root=None: "c" * 40)


def _as_main(monkeypatch, name=m.MODULE, origin=None):
    main = types.ModuleType("__main__")
    main.__spec__ = types.SimpleNamespace(name=name, origin=str(origin or m.__file__))
    monkeypatch.setitem(sys.modules, "__main__", main)


def _written(tmp_path, monkeypatch):
    _as_main(monkeypatch)
    look = m.Look(RULE)
    look.join_outcomes(lambda: None)
    result = tmp_path / "result.json"
    result.write_text("{}", encoding="utf-8")
    return look, look.finish(result=result, dates=DATES)


def test_the_entry_point_is_registered_at_its_current_source_sha():
    assert window.MG1_CONFIRMATION_ENTRY_POINTS == {m.MODULE: m.module_sha256()}
    assert m.MG1_RULE_SHA256 == m.sha256_file(RULE)


def test_the_receipt_and_start_marker_live_at_fixed_repo_paths(monkeypatch):
    monkeypatch.undo()
    assert m.LOOK_ROOT == paths.data_path("mg1_look")
    assert m.receipt_path("ab").name == "receipt-ab.json" and m.started_path("ab").name == "started-ab.json"


def test_looked_at_is_stamped_and_on_disk_before_the_first_outcome_join(tmp_path, monkeypatch):
    _as_main(monkeypatch)
    look = m.Look(RULE)
    seen = []

    def loader(x):
        started = json.loads(m.started_path(m.MG1_RULE_SHA256).read_text(encoding="utf-8"))
        seen.append(started["looked_at_utc"])
        return x

    assert look.join_outcomes(loader, 7) == 7 and look.join_outcomes(loader, 8) == 8
    assert seen == [look.looked_at_utc] * 2  # stamped once, before the first join only
    result = tmp_path / "r.json"
    result.write_text("{}", encoding="utf-8")
    receipt = json.loads(look.finish(result=result, dates=DATES).read_text(encoding="utf-8"))
    assert receipt["looked_at_utc"] == look.looked_at_utc <= receipt["completed_at_utc"]
    assert tuple(sorted(receipt)) == tuple(sorted(m.RECEIPT_FIELDS))
    assert receipt["schema"] == schema_version("mg1_look_receipt") == m.RECEIPT_SCHEMA
    assert receipt["dates_scored"] == {"count": 3, "first": "2026-10-15", "last": "2026-11-28"}
    assert receipt["entry_point"] == {"module": m.MODULE, "source_sha256": m.module_sha256()}
    assert receipt["result"]["sha256"] == m.sha256_file(result) and receipt["repo_commit"] == "c" * 40
    with pytest.raises(m.MG1LookRefused, match="finished"):
        look.join_outcomes(loader, 9)


def test_a_written_receipt_passes_and_one_look_per_rule(tmp_path, monkeypatch):
    _, path = _written(tmp_path, monkeypatch)
    assert path == m.receipt_path(m.MG1_RULE_SHA256) and m.receipt_problems(path) == []
    with pytest.raises(m.MG1LookRefused, match="exactly one look"):
        m.Look(RULE)
    m.receipt_path(m.MG1_RULE_SHA256).unlink()  # even without the receipt, the start marker refuses
    with pytest.raises(m.MG1LookRefused, match="started-.*exactly one look"):
        m.Look(RULE)


def test_a_crash_after_the_first_join_still_spends_the_look(monkeypatch):
    _as_main(monkeypatch)
    look = m.Look(RULE)
    with pytest.raises(RuntimeError):
        look.join_outcomes(lambda: (_ for _ in ()).throw(RuntimeError("join broke")))
    assert m.started_path(m.MG1_RULE_SHA256).is_file()
    with pytest.raises(m.MG1LookRefused, match="exactly one look"):
        m.Look(RULE)


@pytest.mark.parametrize("name,origin", [("weather.calibration.mg1_look2", None), ("mg1_look", None),
                                         (None, None), (m.MODULE, "edited")])
def test_only_the_registered_entry_point_can_stamp(tmp_path, monkeypatch, name, origin):
    if origin:
        origin = tmp_path / "mg1_look.py"
        origin.write_bytes(Path(m.__file__).read_bytes() + b"# edited\n")
    _as_main(monkeypatch, name, origin)
    look = m.Look(RULE)
    with pytest.raises(m.MG1LookRefused, match="not the registered MG-1 look"):
        look.join_outcomes(lambda: None)
    assert not m.started_path(m.MG1_RULE_SHA256).exists() and look.looked_at_utc is None


def test_refusals_before_anything_is_read(tmp_path, monkeypatch):
    other = tmp_path / "rule.md"
    other.write_bytes(RULE.read_bytes() + b"\n")
    with pytest.raises(m.MG1LookRefused, match="not the signed"):
        m.Look(other)
    _as_main(monkeypatch)
    look = m.Look(RULE)
    with pytest.raises(m.MG1LookRefused, match="no outcome was joined"):
        look.finish(result=other, dates=DATES)


def test_hand_made_or_hand_edited_receipts_fail(tmp_path, monkeypatch):
    _, path = _written(tmp_path, monkeypatch)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert m.receipt_problems(tmp_path / "absent.json") == [f"MG-1 look receipt {tmp_path / 'absent.json'} "
                                                            "does not exist"]
    hand = tmp_path / "hand.json"
    hand.write_text(json.dumps({"looked_at_utc": "2026-12-14T00:00:00Z"}), encoding="utf-8")
    assert m.receipt_problems(hand) == ["MG-1 look receipt schema is not mg1_look_receipt/1"]
    edited = dict(receipt, looked_at_utc="2026-12-01T00:00:00Z")
    hand.write_text(json.dumps(edited), encoding="utf-8")
    problems = m.receipt_problems(hand)
    assert any("body_sha256" in p for p in problems) and any("differ from the written" in p for p in problems)
    path.write_text(json.dumps(edited, indent=1, sort_keys=True) + "\n", encoding="utf-8")  # edited in place
    assert any("body_sha256" in p for p in m.receipt_problems(path))
    stranger = dict(receipt, entry_point={"module": m.MODULE, "source_sha256": "0" * 64})
    stranger["body_sha256"] = m.body_sha256(stranger)
    path.write_text(json.dumps(stranger), encoding="utf-8")
    assert m.receipt_problems(path) == [
        "MG-1 look receipt was not written by the registered entry point at its registered sha"]


# --- the MG-1 scoring (pre-registration sections 3, 4, 6; Clarification 1): synthetic data only -------------------

D0 = date(2026, 10, 15)
LAST = date(2026, 11, 28)
NOW = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
HOURS = (3, 8, 14, 15, 19)
BANDS = (("lte", np.nan, 59.0), ("range", 60.0, 61.0), ("range", 62.0, 63.0), ("gte", 64.0, np.nan))


def _countable(path, rows=None):
    if rows is None:
        rows = [(D0 + timedelta(days=k), True) for k in range(45)]
    body = {"schema": m.COUNTABLE_SCHEMA,
            "dates": [{"date": d.isoformat(), "promotion_countable": c, "parser_v2_verified": True,
                       "shadow_stage_captured": None} for d, c in rows]}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _synthetic(tmp_path, *, bad_markets=(), mutate=None, labels_mutate=None, seed=7):
    """45 dates x 11 markets x 5 hours; MG-1 centred near the truth (``bad_markets``: 6 F too warm), served
    uniform, market sharp. Returns the paths ``score`` takes."""
    rng = np.random.default_rng(seed)
    snaps, bands, labels, market = [], [], [], []
    for k in range(45):
        day = D0 + timedelta(days=k)
        for name in m.MARKETS:
            truth = 62.0 + rng.normal(0, 2)
            winner = 0 if truth < 59.5 else 1 if truth < 61.5 else 2 if truth < 63.5 else 3
            labels_rows = []
            for h in HOURS:
                key = f"{name}|{day.isoformat()}|{h:02d}"
                cap = datetime(day.year, day.month, day.day, h, 30, tzinfo=timezone.utc)
                mu = truth + rng.normal(0, 0.5) + (6.0 if name in bad_markets else 0.0)
                snaps.append({"row_key": key, "date": day.isoformat(), "market": name, "local_hour": h,
                              "captured_at_utc": cap.isoformat(),
                              "v2_available_at": (cap - timedelta(hours=2)).isoformat(),
                              "v2_mean": mu, "v2_stddev": 1.5, "v2_period_kind": "maximum",
                              "v2_status": "available", "v2_parser_version": 2, "floor": 50.0,
                              "guidance_physical_floor": 50.0, "high_so_far": np.nan,
                              "trusted_current_max": np.nan, "n_bands": 4, "model_version": "rel-1"})
                for i, (kind, lo, hi) in enumerate(BANDS):
                    bands.append({"row_key": key, "band_index": i, "kind": kind, "low": lo, "high": hi,
                                  "p_served": 0.25})
                    market.append({"row_key": key, "band_index": i, "p_market_yes": 0.7 if i == winner else 0.1})
                labels_rows.append({"row_key": key, "winner": winner})
            labels.extend(labels_rows)
    snaps, bands = pd.DataFrame(snaps), pd.DataFrame(bands)
    labels, market = pd.DataFrame(labels), pd.DataFrame(market)
    if mutate:
        snaps = mutate(snaps)
    if labels_mutate:
        labels = labels_mutate(labels)
    layout = tmp_path / "layout"
    layout.mkdir()
    snaps.to_parquet(layout / "inputs_snapshots.parquet", index=False)
    bands.to_parquet(layout / "inputs_bands.parquet", index=False)
    outcomes = tmp_path / "outcomes"
    outcomes.mkdir()
    labels.to_parquet(outcomes / "labels.parquet", index=False)
    market.to_parquet(outcomes / "market.parquet", index=False)
    return {"rule": RULE, "layout_root": layout, "countable": _countable(tmp_path / "countable.json"),
            "labels": outcomes / "labels.parquet", "market": outcomes / "market.parquet", "out": tmp_path / "out"}


def _score(monkeypatch, inputs, now=NOW, **kw):
    _as_main(monkeypatch)
    return m.score(**inputs, now=now, **kw)


def _result(tmp_path):
    return json.loads((tmp_path / "out" / m.RESULT).read_text(encoding="utf-8"))


def test_the_registered_rule_constants_are_the_preregistrations():
    assert (m.N_DATES, m.PRIMARY, m.DRAWS, m.SEED, m.CROSSED_SEED) == (45, ("00-16", 0, 16), 2000, 20261004,
                                                                        20260921)
    assert (m.MIN_NEGATIVE_MARKETS, m.MATERIALITY, m.COVERAGE_MIN, m.REPLAY_TOLERANCE) == (8, 0.05, 0.90, 1e-12)
    assert len(m.MARKETS) == 11 and set(m.MARKET_TZ) == set(m.MARKETS)
    assert sorted(m.VOID_CONDITIONS) == ["coverage", "parser", "pit", "replay", "window_leakage"]


def test_a_clean_synthetic_window_passes_and_writes_one_receipt(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    path, payload = _score(monkeypatch, inputs)
    assert path == m.receipt_path(m.MG1_RULE_SHA256) and m.receipt_problems(path) == []
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["dates_scored"] == {"count": 45, "first": "2026-10-15", "last": "2026-11-28"}
    assert receipt["result"]["sha256"] == m.sha256_file(inputs["out"] / m.RESULT)
    d = payload["decision"]
    assert d["verdict"] == "PASS" and d["falsifiers"] == [] and d["n_markets_negative"] == 11
    assert d["ci95"][1] < 0 and d["estimate"] <= d["materiality_bar"] < 0
    assert _result(tmp_path)["decision"]["verdict"] == "PASS"
    assert payload["outcome_blind_checks"]["coverage"]["share_00_16"] == 1.0
    assert payload["reported"]["15-16"]["label"].startswith("known development cost")
    assert payload["matched_rows"]["label"] == "selected on availability"
    assert payload["served_releases"] == {"column": "model_version", "counts": {"rel-1": 2475}}
    assert payload["clarification_1_caveats"]["2026-10-15"] == {"parser_v2_verified": True,
                                                                "shadow_stage_captured": None}
    with pytest.raises(m.MG1LookRefused, match="exactly one look"):
        m.score(**inputs, now=NOW)


def test_the_primary_is_equal_cell_and_date_clustered_at_seed_20261004(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    _, payload = _score(monkeypatch, inputs)
    snaps, bands, _ = m.read_inputs(inputs["layout_root"], [D0 + timedelta(days=k) for k in range(45)])
    lab, mkt, _, _ = m.load_outcomes(inputs["labels"], inputs["market"], snaps, bands)
    table = m._table(snaps, bands, lab, mkt)
    p, _ = m._reasons(table, m.mg1_vector(snaps, bands))
    per_snap = table.brier(p) - table.brier(table.p_served)
    mask = table.local_hour <= 16
    idx, cells = table.cells(per_snap, mask)
    cell_dates = [table.keys[i][0] for i in idx]
    assert payload["primary"]["fixed_market"]["estimate"] == pytest.approx(cells.mean(), abs=1e-15)
    days = sorted(set(cell_dates))
    counts = np.random.default_rng(20261004).multinomial(45, np.full(45, 1 / 45), size=2000)
    w = counts[:, [days.index(d) for d in cell_dates]]
    boot = (w @ cells) / w.sum(axis=1)
    assert payload["primary"]["fixed_market"]["ci95"] == pytest.approx(np.quantile(boot, [.025, .975]).tolist(),
                                                                       abs=1e-15)


def test_mg1_worse_than_served_closes_the_route(tmp_path, monkeypatch):
    _, payload = _score(monkeypatch, _synthetic(tmp_path, bad_markets=m.MARKETS))
    d = payload["decision"]
    assert d["verdict"] == "NOT_PASS" and "1 route closed" in d["falsifiers"] and d["estimate"] > 0


def test_fewer_than_8_negative_markets_is_not_fleet_wide(tmp_path, monkeypatch):
    _, payload = _score(monkeypatch, _synthetic(tmp_path, bad_markets=m.MARKETS[:4]))
    d = payload["decision"]
    assert d["n_markets_negative"] == 7 and d["conditions"]["markets_negative"] is False
    assert d["verdict"] == "NOT_PASS" and "3 not fleet-wide" in d["falsifiers"]
    assert sorted(set(m.MARKETS) - set(d["markets_negative"])) == sorted(m.MARKETS[:4])


def test_decide_materiality_and_crossed_disagreement():
    per = {k: {"mean_delta": -0.01} for k in m.MARKETS}
    primary = {"estimate": -0.001, "ci95": [-0.002, -0.0005]}
    d = m.decide(primary, per, 0.1, -0.001)
    assert d["verdict"] == "NOT_PASS" and d["falsifiers"] == ["2 immaterial"]
    assert d["materiality_bar"] == pytest.approx(-0.005)
    assert m.decide({"estimate": -0.01, "ci95": [-0.02, -0.001]}, per, 0.1, -0.01)["verdict"] == "PASS"
    crossed = m.decide({"estimate": -0.01, "ci95": [-0.02, -0.001]}, per, 0.1, +0.003)
    assert crossed["verdict"] == "NOT_PASS" and crossed["falsifiers"] == ["4 crossed disagreement"]
    tie = dict(per, atlanta={"mean_delta": 0.0}, austin={"mean_delta": 0.0}, chicago={"mean_delta": None},
               dallas={"mean_delta": 0.0})
    assert m.decide({"estimate": -0.01, "ci95": [-0.02, -0.001]}, tie, 0.1, -0.01)["n_markets_negative"] == 7
    # PROVISIONAL A5: a negative served - market gap makes the bar positive, as written.
    assert m.decide({"estimate": -0.01, "ci95": [-0.02, -0.001]}, per, -0.1, -0.01)["materiality_bar"] == pytest.approx(0.005)


def _drop_v2(share):
    def mutate(snaps):
        morning = snaps.index[snaps.local_hour <= 16]
        snaps.loc[morning[: int(len(morning) * share)], "v2_mean"] = np.nan
        return snaps
    return mutate


def _set_first_used(column, value):
    def mutate(snaps):
        snaps[column] = snaps[column].astype(object)
        snaps.loc[0, column] = value
        return snaps
    return mutate


@pytest.mark.parametrize("mutate,condition", [(_drop_v2(0.15), "coverage"),
                                              (_set_first_used("v2_parser_version", 1), "parser"),
                                              (_set_first_used("v2_period_kind", "minimum"), "pit")])
def test_outcome_blind_void_conditions_void_the_look_and_still_write_the_receipt(tmp_path, monkeypatch, mutate,
                                                                                  condition):
    path, payload = _score(monkeypatch, _synthetic(tmp_path, mutate=mutate))
    assert payload["decision"]["verdict"] == "VOID" and payload["decision"]["conditions"] == [condition]
    assert m.receipt_problems(path) == [] and payload["outcomes_opened"] is True


def test_coverage_at_90_percent_does_not_void(tmp_path, monkeypatch):
    _, payload = _score(monkeypatch, _synthetic(tmp_path, mutate=_drop_v2(0.10)))
    assert payload["outcome_blind_checks"]["coverage"]["share_00_16"] == pytest.approx(0.9)
    assert payload["decision"]["verdict"] != "VOID"
    assert payload["coverage_reasons"]["absent"] == int(0.10 * 45 * 11 * 4)


def test_availability_after_capture_falls_back_and_is_disclosed(tmp_path, monkeypatch):
    def late(snaps):
        snaps.loc[0, "v2_available_at"] = (pd.Timestamp(snaps.loc[0, "captured_at_utc"])
                                           + pd.Timedelta(minutes=1)).isoformat()
        return snaps
    _, payload = _score(monkeypatch, _synthetic(tmp_path, mutate=late))
    pit = payload["outcome_blind_checks"]["pit"]
    assert pit["pass"] and pit["used_available_after_capture"] == 0
    assert pit["disclosed_finite_v2_available_after_capture"] == 1 and payload["coverage_reasons"]["absent"] == 1


def test_replay_against_a_captured_shadow_vector(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    snaps, bands, _ = m.read_inputs(inputs["layout_root"], [D0 + timedelta(days=k) for k in range(45)])
    frame = m.mg1_vector(snaps, bands)
    good, bad = tmp_path / "shadow.parquet", tmp_path / "shadow_bad.parquet"
    frame.to_parquet(good, index=False)
    off = frame.copy()
    off.loc[0, "p"] += 1e-9
    off.to_parquet(bad, index=False)
    assert m.replay_check(frame, good)["pass"] and not m.replay_check(frame, bad)["pass"]
    assert m.replay_check(frame, None)["status"].startswith("not applicable")
    _, payload = _score(monkeypatch, inputs, shadow=bad)
    assert payload["decision"]["conditions"] == ["replay"]


def _absent_outcomes(inputs, tmp_path):
    return dict(inputs, labels=tmp_path / "no-labels.parquet", market=tmp_path / "no-market.parquet")


@pytest.mark.parametrize("now,match", [(datetime(2026, 11, 28, 23, tzinfo=timezone.utc), "has not closed"),
                                       (datetime(2026, 11, 29, 7, tzinfo=timezone.utc), "not ended in every")])
def test_refusals_before_the_window_closes_and_settles_read_nothing(tmp_path, monkeypatch, now, match):
    inputs = _absent_outcomes(_synthetic(tmp_path), tmp_path)
    with pytest.raises(m.MG1LookRefused, match=match):
        _score(monkeypatch, inputs, now=now)
    assert not m.started_path(m.MG1_RULE_SHA256).exists() and not (tmp_path / "out").exists()


def _rows(skip=None, countable_off=(), extra=0):
    days = [D0 + timedelta(days=k) for k in range(45 + extra)]
    return [(d, d not in countable_off) for d in days if d != skip]


@pytest.mark.parametrize("rows,match", [
    (_rows(skip=D0 + timedelta(days=3)), "skips or repeats"),
    (_rows(countable_off={D0 + timedelta(days=3)}), "44 countable"),
    (_rows()[1:], "does not start at D0"),
    (_rows(countable_off={D0 + timedelta(days=45)}, extra=1), "past the 45th"),
    (_rows(countable_off={D0 + timedelta(days=5)}, extra=1), "after the recorded MG1_LAST"),
])
def test_countable_list_refusals(tmp_path, rows, match):
    with pytest.raises(m.MG1LookRefused, match=match):
        m.read_countable(_countable(tmp_path / "c.json", rows))


def test_an_extended_window_counts_past_a_non_countable_date(tmp_path, monkeypatch):
    monkeypatch.setattr(window, "MG1_LAST", LAST + timedelta(days=1))
    counted, rows = m.read_countable(_countable(tmp_path / "c.json", _rows(countable_off={D0 + timedelta(days=5)},
                                                                         extra=1)))
    assert len(counted) == 45 and counted[-1] == LAST + timedelta(days=1) and not rows[5]["countable"]


def test_a_layout_carrying_labels_or_prices_is_refused_before_the_join(tmp_path, monkeypatch):
    inputs = _absent_outcomes(_synthetic(tmp_path, mutate=lambda s: s.assign(winner=0)), tmp_path)
    with pytest.raises(AssertionError, match="label/market"):
        _score(monkeypatch, inputs)
    assert not m.started_path(m.MG1_RULE_SHA256).exists()


def test_an_unregistered_entry_point_reads_no_outcome(tmp_path, monkeypatch):
    inputs = _absent_outcomes(_synthetic(tmp_path), tmp_path)
    _as_main(monkeypatch, "weather.calibration.mg1_look2")
    with pytest.raises(m.MG1LookRefused, match="not the registered MG-1 look"):
        m.score(**inputs, now=NOW)
    assert not m.started_path(m.MG1_RULE_SHA256).exists() and not (tmp_path / "out" / m.RESULT).exists()


def test_a_failure_after_the_join_is_aborted_and_still_receipted(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path, labels_mutate=lambda lab: lab.iloc[1:])
    with pytest.raises(m.MG1LookRefused, match="have no label"):
        _score(monkeypatch, inputs)
    assert m.started_path(m.MG1_RULE_SHA256).is_file()
    assert _result(tmp_path)["decision"]["verdict"] == "ABORTED"
    assert m.receipt_problems(m.receipt_path(m.MG1_RULE_SHA256)) == []


def test_serving_change_segments_and_tail_lens_are_reported(tmp_path, monkeypatch):
    _, payload = _score(monkeypatch, _synthetic(tmp_path), serving_changes=["2026-11-01"])
    seg = payload["serving_change_segments"]["2026-11-01"]
    assert seg["pre"]["n_dates"] == 17 and seg["post"]["n_dates"] == 28
    tail = payload["tail_lens_00_16"]
    assert tail["band_rows"] == 45 * 11 * 4 * 4 and 0 < tail["tail_share"] < 1
    assert set(payload["market_relative"]) >= {"00-16", "17-23", "all"}


def test_the_run_command_refuses_before_the_window_closes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(m, "_now_utc", lambda: datetime(2026, 11, 28, 23, tzinfo=timezone.utc))
    inputs = _absent_outcomes(_synthetic(tmp_path), tmp_path)
    argv = ["run", "--rule", str(RULE), "--layout", str(inputs["layout_root"]), "--countable",
            str(inputs["countable"]), "--labels", str(inputs["labels"]), "--market", str(inputs["market"]),
            "--out", str(inputs["out"])]
    assert m.main(argv) == 2 and "has not closed" in capsys.readouterr().err
    assert not m.started_path(m.MG1_RULE_SHA256).exists()
