"""MG-1 look receipt writer (``mg1_look_receipt/1``) and its registered entry point.

Guards: master's R3 ruling of 2026-10-26 on the B-1 binding: the MG-1 look receipt is written by code only, never by
hand; ``looked_at_utc`` is stamped by the clock immediately before the look's first outcome join (the start marker is
on disk before the loader runs); receipt and start marker are written in mode "x" at fixed ``weather.paths``
data paths keyed by the MG-1 rule sha; the entry point is registered by module name and source sha256 in
``MG1_CONFIRMATION_ENTRY_POINTS``; a hand-made or hand-edited receipt fails the checks B-1's VOID 5 runs.

The scoring tests guard MG-1 Clarification 2 (master ruling of 2026-11-03, with R11). They use synthetic fixtures
only:

- the A3 per-market-day mask before the join, and the key-only hole check that holds the look without consuming
  it;
- ``write_countable``;
- the A6 status hold;
- the A7 absence record;
- the A4 wait for finality and the R24 freeze;
- the A2 labels through ``read_venue_labels`` on the frozen copy;
- the T2 mask of a refused label;
- both branches of the owner constants A1, A5 and A12.
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



# --- the MG-1 scoring (pre-registration sections 3, 4, 6; Clarifications 1 and 2): synthetic data only -----------

D0 = date(2026, 10, 15)
LAST = date(2026, 11, 28)
NOW = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)
FROZEN_AT = "2026-11-30T12:00:00+00:00"
THROUGH = date(2026, 11, 29)  # FREEZE_THROUGH at FROZEN_AT: 11-29 has ended in every market (Pacific last)
HOURS = (3, 8, 14, 15, 19)
BANDS = (("lte", np.nan, 59.0), ("range", 60.0, 61.0), ("range", 62.0, 63.0), ("gte", 64.0, np.nan))
WU_COLUMNS = ["local_date", "temperature_unit", "row_count", "max_temp_native", "max_temp_bucket_native"]


def _flags(countable, support=None):
    return {name: bool(countable) for name in (support or m.support_markets())}


def _countable(path, rows=None, markets=None):
    """``rows``: (date, countable); ``markets``: {date: {market: bool}} overrides for single dates."""
    if rows is None:
        rows = [(D0 + timedelta(days=k), True) for k in range(45)]
    dates = []
    for d, c in rows:
        flags = dict((markets or {}).get(d) or _flags(c))
        dates.append({"date": d.isoformat(), "promotion_countable": any(flags.values()), "markets": flags,
                      "parser_v2_verified": True, "shadow_stage_captured": None})
    path.write_text(json.dumps({"schema": m.COUNTABLE_SCHEMA, "dates": dates}), encoding="utf-8")
    return path


def _bucket_winner(truth):
    bucket = int(np.floor(truth + 0.5))
    return bucket, 0 if bucket <= 59 else 1 if bucket <= 61 else 2 if bucket <= 63 else 3


def _freeze(root, labels, drop=(), thin=(), skipped=(), keys=True):
    """The R24 frozen copy (label_root layout) and its freeze receipt. ``labels``: {(market, date): (high, bucket)}.

    - ``drop``: (market, date) rows left out of the frozen files and of the key list (metadata predicts them);
    - ``skipped``: the same, but recorded in the manifest's ``skipped_dates``;
    - ``thin``: rows written with 10 observations and still listed (the reader refuses them; the metadata does not
      predict it);
    - ``keys``: whether the receipt carries the proposed ``label_dates`` key list.
    """
    import csv

    from weather.backtesting import venue_rule_labels as vrl

    markets = {}
    for name in sorted({mk for mk, _ in labels}):
        days = sorted(d for mk, d in labels if mk == name and (mk, d) not in set(drop) | set(skipped))
        rows = {d: 10 if (name, d) in thin else 24 for d in days}
        wu = root / name / "wu" / "daily_summary.csv"
        wu.parent.mkdir(parents=True)
        with wu.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=WU_COLUMNS)
            writer.writeheader()
            for d in days:
                high, bucket = labels[(name, d)]
                writer.writerow({"local_date": d.isoformat(), "temperature_unit": "F", "row_count": rows[d],
                                 "max_temp_native": high, "max_temp_bucket_native": bucket})
        venue = vrl.write_label_csv(root / name / "daily" / "daily_summary.csv", [
            {"local_date": d.isoformat(), "temperature_unit": "F", "row_count": rows[d],
             "max_temp": labels[(name, d)][0],
             "max_temp_bucket": labels[(name, d)][1], "label_source": vrl.LABEL_SOURCE_METAR,
             "label_station": "KXXX", "label_station_basis": vrl.STATION_BASIS_REGISTRY,
             "label_rule_version": vrl.VENUE_RULE_VERSION,
             "label_cutover_date": vrl.VENUE_RULE_CUTOVER_DATE.isoformat(), "label_value_basis": "t_group"}
            for d in days if d >= vrl.VENUE_RULE_CUTOVER_DATE])
        manifest = root / name / "manifest.json"
        post = sum(1 for d in days if d >= vrl.VENUE_RULE_CUTOVER_DATE)
        manifest.write_text(json.dumps({
            "market_id": name, "label_dates": [d.isoformat() for d in days],
            "skipped_dates": {d.isoformat(): "no_routine_metar_and_no_wu_row" for mk, d in skipped if mk == name},
            "label_source_counts": {vrl.LABEL_SOURCE_METAR: post, vrl.LABEL_SOURCE_WU: len(days) - post}}),
            encoding="utf-8")
        markets[name] = {key: {"path": str(path), "sha256": m.sha256_file(path)}
                         for key, path in (("label_csv", venue), ("manifest", manifest), ("wu_daily_summary", wu))}
        markets[name].update(label_csv_matches_manifest=True, wu_daily_summary_matches_manifest=True)
        if keys:
            body = json.loads(manifest.read_text(encoding="utf-8"))
            markets[name].update(label_dates=body["label_dates"], skipped_dates=body["skipped_dates"])
    receipt = root / "freeze_receipt.json"
    receipt.write_text(json.dumps({"schema_version": m.FREEZE_RECEIPT_SCHEMA, "look_id": m.FREEZE_LOOK_ID,
                                   "through": THROUGH.isoformat(), "frozen_at_utc": FROZEN_AT, "audit_status": "OK",
                                   "label_root": str(root), "markets": markets}), encoding="utf-8")
    return receipt


def _market_manifest(market, layout_root, /, **edits):
    """The host producer's ``mg1_market/1`` manifest beside a synthetic --market file (shas and booleans only)."""
    body = {"schema": m.MARKET_MANIFEST_SCHEMA, "look_id": "mg1", "market_sha256": m.sha256_file(market),
            "layout": {"snapshots_sha256": m.sha256_file(layout_root / "inputs_snapshots.parquet"),
                       "bands_sha256": m.sha256_file(layout_root / "inputs_bands.parquet")},
            "range_ok": True, "duplicate_free": True}
    body.update(edits)
    path = Path(market).parent / m.MARKET_MANIFEST
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _synthetic(tmp_path, *, bad_markets=(),mutate=None, drop_labels=(), thin_labels=(), skipped_labels=(),
               keys=True, seed=7):
    """45 dates x the support markets x 5 hours; MG-1 centred near the truth (``bad_markets``: 6 F too warm), served
    uniform, market sharp. Returns the paths ``score`` takes."""
    rng = np.random.default_rng(seed)
    snaps, bands, market, labels = [], [], [], {}
    for k in range(45):
        day = D0 + timedelta(days=k)
        for name in m.support_markets():
            truth = 62.0 + rng.normal(0, 2)
            bucket, winner = _bucket_winner(truth)
            labels[(name, day)] = (round(truth, 1), bucket)
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
    snaps, bands, market = pd.DataFrame(snaps), pd.DataFrame(bands), pd.DataFrame(market)
    if mutate:
        snaps = mutate(snaps)
    layout = tmp_path / "layout"
    layout.mkdir()
    snaps.to_parquet(layout / "inputs_snapshots.parquet", index=False)
    bands.to_parquet(layout / "inputs_bands.parquet", index=False)
    outcomes = tmp_path / "outcomes"
    outcomes.mkdir()
    market.to_parquet(outcomes / "market.parquet", index=False)
    _market_manifest(outcomes / "market.parquet", layout)
    freeze = _freeze(tmp_path / "frozen" / "mg1", labels, drop_labels, thin_labels, skipped_labels, keys)
    return {"rule": RULE, "layout_root": layout, "countable": _countable(tmp_path / "countable.json"),
            "label_freeze": freeze, "market": outcomes / "market.parquet", "out": tmp_path / "out"}


def _score(monkeypatch, inputs, now=NOW, **kw):
    _as_main(monkeypatch)
    return m.score(**inputs, now=now, **kw)


def _result(tmp_path):
    return json.loads((tmp_path / "out" / m.RESULT).read_text(encoding="utf-8"))


def _nothing_spent(tmp_path):
    return not m.started_path(m.MG1_RULE_SHA256).exists() and not (tmp_path / "out" / m.RESULT).exists()


def test_the_registered_rule_constants_are_the_preregistrations():
    assert (m.N_DATES, m.PRIMARY, m.DRAWS, m.SEED, m.CROSSED_SEED) == (45, ("00-16", 0, 16), 2000, 20261004,
                                                                        20260921)
    assert (m.A1_MIN_NEGATIVE_MARKETS, m.MATERIALITY, m.COVERAGE_MIN, m.REPLAY_TOLERANCE) == (8, 0.05, 0.90, 1e-12)
    assert len(m.MARKETS) == 11 and set(m.MARKET_TZ) == set(m.MARKETS)
    assert sorted(m.VOID_CONDITIONS) == ["coverage", "parser", "pit", "replay", "window_leakage"]


def test_the_owner_constants_keep_the_reviewed_behaviour_until_answered():
    """A1 (with its Q3 count), A5 and A12 are owner questions, open (MG-1 Clarification 2 section 3)."""
    assert m.owner_constants() == {"A1_DENVER_SCORED": True, "A1_MIN_NEGATIVE_MARKETS": 8, "A5_BAR": "as_written",
                                   "A12_FALSIFIER_4": "point"}
    assert m.support_markets() == m.MARKETS


@pytest.mark.parametrize("name,value", [("A1_DENVER_SCORED", "yes"), ("A5_BAR", "abs"),
                                        ("A12_FALSIFIER_4", "both"), ("A1_MIN_NEGATIVE_MARKETS", 0),
                                        ("A1_MIN_NEGATIVE_MARKETS", 12), ("A1_MIN_NEGATIVE_MARKETS", True),
                                        ("A1_MIN_NEGATIVE_MARKETS", "8"), ("A1_MIN_NEGATIVE_MARKETS", 8.0)])
def test_an_unbuilt_owner_branch_is_refused(monkeypatch, name, value):
    monkeypatch.setattr(m, name, value)
    with pytest.raises(m.MG1LookRefused, match="not one of the built branches"):
        m.owner_constants()


def test_a_clean_synthetic_window_passes_and_writes_one_receipt(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    path, payload = _score(monkeypatch, inputs)
    assert path == m.receipt_path(m.MG1_RULE_SHA256) and m.receipt_problems(path) == []
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["dates_scored"] == {"count": 45, "first": "2026-10-15", "last": "2026-11-28"}
    assert receipt["result"]["sha256"] == m.sha256_file(inputs["out"] / m.RESULT)
    assert receipt["label_freeze_receipt_sha256"] == m.sha256_file(inputs["label_freeze"])
    d = payload["decision"]
    assert d["verdict"] == "PASS" and d["falsifiers"] == [] and d["n_markets_negative"] == 11
    assert d["ci95"][1] < 0 and d["estimate"] <= d["materiality_bar"] < 0
    assert _result(tmp_path)["decision"]["verdict"] == "PASS"
    assert payload["owner_constants"] == m.owner_constants() and payload["markets"] == list(m.MARKETS)
    assert payload["outcome_blind_checks"]["coverage"]["share_00_16"] == 1.0
    assert payload["label_masked"]["market_days"] == 0 and receipt["flags"] == [] and payload["receipt_flags"] == []
    keys = payload["inputs"]["label_key_check"]
    assert keys["countable_market_days"] == keys["with_label_key"] == 45 * 11
    assert sorted(keys["label_source_counts"]) == sorted(m.MARKETS)
    assert payload["inputs"]["market_day_mask"] == {"countable_market_days": 45 * 11, "masked_market_days": 0}
    assert payload["inputs"]["label_freeze_receipt_sha256"] == receipt["label_freeze_receipt_sha256"]
    assert payload["reported"]["15-16"]["label"].startswith("known development cost")
    assert payload["matched_rows"]["label"] == "selected on availability"
    assert payload["served_releases"] == {"column": "model_version", "counts": {"rel-1": 2475}}
    assert payload["clarification_1_caveats"]["2026-10-15"] == {"parser_v2_verified": True,
                                                                "shadow_stage_captured": None}
    leak = payload["outcome_blind_checks"]["window_leakage"]["marker_and_receipt_absent_at_start"]
    assert leak["both_absent"] is True and leak["started_marker"].endswith(f"started-{m.MG1_RULE_SHA256}.json")
    with pytest.raises(m.MG1LookRefused, match="exactly one look"):
        m.score(**inputs, now=NOW)


def test_labels_come_from_the_frozen_copy_through_the_venue_label_reader(tmp_path, monkeypatch):
    """A2 (b): read_through is the 45th date, the reserved window is allowed, Denver reads KDEN rows."""
    from weather.backtesting import venue_label_reader as vlr

    inputs = _synthetic(tmp_path)
    calls = []
    real = vlr.read_venue_labels

    def spy(market_id, target_dates, **kw):
        calls.append((market_id, kw["read_through"], kw["allow_reserved_window"], kw["model_scoring"],
                      Path(kw["venue_label_csv"]).parent.parent.name))
        return real(market_id, target_dates, **kw)

    monkeypatch.setattr(vlr, "read_venue_labels", spy)
    _score(monkeypatch, inputs)
    assert sorted(c[0] for c in calls) == sorted(m.MARKETS)
    assert all(c[1] == LAST and c[2] is True and c[4] == c[0] for c in calls)
    assert {c[0]: c[3] for c in calls}["denver"] is False
    assert all(c[3] is True for c in calls if c[0] != "denver")


def test_winner_band_maps_a_label_bucket_to_exactly_one_band():
    ladder = [(kind, lo, hi, i) for i, (kind, lo, hi) in enumerate(BANDS)]
    assert [m.winner_band(ladder, b) for b in (40, 59, 60, 61, 62, 63, 64, 90)] == [0, 0, 1, 1, 2, 2, 3, 3]
    with pytest.raises(m.MG1LookRefused, match="falls in 0 bands"):
        m.winner_band(ladder[1:3], 70)


def test_an_unpredicted_reader_refusal_masks_its_market_day_and_flags_the_receipt(tmp_path, monkeypatch):
    """Q2 after the stamp (T2): a refusal the metadata did not predict (a thin day still listed) masks that
    market-day, is disclosed in label_masked, raises the receipt flag and never voids."""
    thin = ("nyc", D0 + timedelta(days=12))
    path, payload = _score(monkeypatch, _synthetic(tmp_path, thin_labels={thin}))
    masked = payload["label_masked"]
    assert masked["market_days"] == masked["unpredicted_by_metadata"] == 1 and masked["snapshots"] == len(HOURS)
    assert masked["market_days_masked"] == [f"{thin[1].isoformat()}:nyc"]
    assert payload["decision"]["verdict"] == "PASS" and payload["primary"]["n_market_days"] == 45 * 11 - 1
    receipt = json.loads(path.read_text(encoding="utf-8"))
    assert receipt["flags"] == [m.UNPREDICTED_REFUSAL_FLAG] == payload["receipt_flags"]
    assert m.receipt_problems(path) == []


@pytest.mark.parametrize("kw,match", [
    ({"drop_labels": {("nyc", D0 + timedelta(days=12))}}, r"held: 1 countable market-days have no label key .*"
                                                           r"'unexplained_absence': 1.*2026-10-27:nyc"),
    ({"skipped_labels": {("denver", D0 + timedelta(days=30))}}, r"held: 1 countable .*'skipped': 1"),
])
def test_a_countable_market_day_without_a_label_key_holds_before_the_stamp(tmp_path, monkeypatch, kw, match):
    """Q2 before the stamp: metadata only (no CSV parse, no reader call); a hole holds and consumes nothing."""
    from weather.backtesting import venue_label_reader as vlr

    inputs = _synthetic(tmp_path, **kw)

    def no_reader(*args, **kwargs):
        raise AssertionError("the label reader ran before the stamp")

    monkeypatch.setattr(vlr, "read_venue_labels", no_reader)
    monkeypatch.setattr(pd, "read_csv", no_reader)
    with pytest.raises(m.MG1LookHeld, match=match):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)
    m.Look(RULE)  # the look is still available


def _edit_market(path, market, **changes):
    body = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            body["markets"][market].pop(key)
        else:
            body["markets"][market][key] = value
    path.write_text(json.dumps(body), encoding="utf-8")


def _rewrite_manifest(path, market, **changes):
    """Edit one frozen manifest and re-record its sha in the receipt (an internally consistent but bad freeze)."""
    manifest = path.parent / market / "manifest.json"
    body = json.loads(manifest.read_text(encoding="utf-8"))
    body.update(changes)
    manifest.write_text(json.dumps(body), encoding="utf-8")
    _edit_market(path, market, manifest={"path": str(manifest), "sha256": m.sha256_file(manifest)})


def test_a_freeze_without_the_label_key_list_is_refused_by_name(tmp_path, monkeypatch):
    """No CSV fallback, ever: the look refuses naming the field the R24 freeze must carry."""
    inputs = _synthetic(tmp_path, keys=False)
    with pytest.raises(m.MG1LookRefused, match=r"no markets\['atlanta'\]\.label_dates key list"):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)


@pytest.mark.parametrize("edit,match", [
    ("receipt_differs", "label_dates differs from its manifest's"),
    ("count", "count differs from its manifest's label_source_counts"),
    ("overlap", "overlap its manifest's skipped_dates"),
    ("skipped_differs", "skipped_dates differ from its manifest's"),
    ("unsorted", "not a sorted list of distinct dates"),
    ("through", "runs through 2026-11-27, before the countable date 2026-11-28"),
])
def test_inconsistent_label_metadata_holds_before_the_stamp(tmp_path, monkeypatch, edit, match):
    """Master 2026-11-03 (as b_transfer): ANY metadata inconsistency holds; nothing is consumed."""
    inputs = _synthetic(tmp_path)
    freeze = inputs["label_freeze"]
    listed = json.loads(freeze.read_text(encoding="utf-8"))["markets"]["houston"]["label_dates"]
    if edit == "receipt_differs":
        _edit_market(freeze, "houston", label_dates=listed[:-1])
    elif edit == "count":
        _rewrite_manifest(freeze, "houston", label_source_counts={"wu": 1})
    elif edit == "overlap":
        _rewrite_manifest(freeze, "houston", skipped_dates={listed[0]: "x"})
        _edit_market(freeze, "houston", skipped_dates={listed[0]: "x"})
    elif edit == "skipped_differs":
        _edit_market(freeze, "houston", skipped_dates={listed[0]: "x"})
    elif edit == "through":
        _edit_freeze(freeze, through="2026-11-27")
    else:
        _edit_market(freeze, "houston", label_dates=listed[::-1])
        _rewrite_manifest(freeze, "houston", label_dates=listed[::-1])
    with pytest.raises(m.MG1LookHeld, match="held: .*" + match + ".*label metadata inconsistency"):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)
    m.Look(RULE)  # the look is still available


def test_an_unexplained_absence_holds_and_is_never_masked(tmp_path, monkeypatch):
    """Master 2026-11-03: UNEXPLAINED_ABSENCE_HOLDS is a ruling, not an owner branch."""
    assert m.UNEXPLAINED_ABSENCE_HOLDS is True
    monkeypatch.setattr(m, "UNEXPLAINED_ABSENCE_HOLDS", False)
    with pytest.raises(m.MG1LookRefused, match="must be True"):
        _score(monkeypatch, _synthetic(tmp_path, drop_labels={("miami", D0 + timedelta(days=2))}))
    assert _nothing_spent(tmp_path)


def test_the_primary_is_equal_cell_and_date_clustered_at_seed_20261004(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    _, payload = _score(monkeypatch, inputs)
    _, rows = m.read_countable(inputs["countable"])
    snaps, bands, _ = m.read_inputs(inputs["layout_root"], rows)
    freeze = m.read_freeze_receipt(inputs["label_freeze"], LAST, m.settled_at(LAST))
    lab, mkt, _, _, keep, _ = m.load_outcomes(freeze, inputs["market"], snaps, bands, LAST)
    assert keep.all()
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


def test_a5_bar_branches(monkeypatch):
    """A5 (owner question, open): as written a negative served - market gap makes the bar positive."""
    assert m.materiality_bar(-0.1) == pytest.approx(0.005) and m.materiality_bar(0.1) == pytest.approx(-0.005)
    assert m.materiality_bar(None) is None
    monkeypatch.setattr(m, "A5_BAR", "magnitude")
    assert m.materiality_bar(-0.1) == pytest.approx(-0.005) and m.materiality_bar(0.1) == pytest.approx(-0.005)
    per = {k: {"mean_delta": -0.01} for k in m.MARKETS}
    d = m.decide({"estimate": -0.001, "ci95": [-0.002, -0.0005]}, per, -0.1, -0.001)
    assert d["materiality_bar"] == pytest.approx(-0.005) and "2 immaterial" in d["falsifiers"]


def test_a12_falsifier_4_branches(monkeypatch):
    """A12 (owner question, open): the point reading compares signs; the interval reading needs the crossed 95%
    interval wholly on the other side of 0."""
    per = {k: {"mean_delta": -0.01} for k in m.MARKETS}
    primary = {"estimate": -0.01, "ci95": [-0.02, -0.001]}
    straddles = {"estimate": 0.002, "ci95": [-0.001, 0.004]}
    above = {"estimate": 0.004, "ci95": [0.001, 0.006]}
    assert m.decide(primary, per, 0.1, straddles)["falsifiers"] == ["4 crossed disagreement"]
    monkeypatch.setattr(m, "A12_FALSIFIER_4", "interval")
    assert m.decide(primary, per, 0.1, straddles)["verdict"] == "PASS"
    assert m.decide(primary, per, 0.1, above)["falsifiers"] == ["4 crossed disagreement"]
    assert m.decide(primary, per, 0.1, -0.01)["verdict"] == "PASS"  # a bare point estimate has no interval


def test_a1_min_negative_markets_is_the_fleet_wide_count(monkeypatch):
    """Q3 (owner question tied to A1): one constant, 8 with Denver in and out until the owner records a value."""
    per = {k: {"mean_delta": -0.01 if i < 7 else 0.01} for i, k in enumerate(m.MARKETS)}
    primary = {"estimate": -0.01, "ci95": [-0.02, -0.001]}
    d = m.decide(primary, per, 0.1, -0.01)
    assert d["n_markets_negative"] == 7 and d["conditions"]["markets_negative"] is False
    monkeypatch.setattr(m, "A1_MIN_NEGATIVE_MARKETS", 7)
    assert m.decide(primary, per, 0.1, -0.01)["verdict"] == "PASS"
    monkeypatch.setattr(m, "A1_DENVER_SCORED", False)
    monkeypatch.setattr(m, "A1_MIN_NEGATIVE_MARKETS", 10)
    assert m.owner_constants()["A1_MIN_NEGATIVE_MARKETS"] == 10
    monkeypatch.setattr(m, "A1_MIN_NEGATIVE_MARKETS", 11)
    with pytest.raises(m.MG1LookRefused, match="exceeds the 10 scored markets"):
        m.owner_constants()


def test_a1_without_denver_scores_the_ten(tmp_path, monkeypatch):
    """A1 (owner question, open), the other branch: Denver leaves the support and the scored markets."""
    monkeypatch.setattr(m, "A1_DENVER_SCORED", False)
    assert "denver" not in m.support_markets() and len(m.support_markets()) == 10
    _, payload = _score(monkeypatch, _synthetic(tmp_path))
    assert payload["markets"] == [x for x in m.MARKETS if x != "denver"]
    assert payload["owner_constants"]["A1_MIN_NEGATIVE_MARKETS"] == 8
    assert sorted(payload["per_market"]) == sorted(payload["markets"])
    assert payload["inputs"]["market_day_mask"]["countable_market_days"] == 45 * 10
    with pytest.raises(m.MG1LookRefused, match="exactly the support"):
        m._parse_countable({"schema": m.COUNTABLE_SCHEMA, "dates": [
            {"date": D0.isoformat(), "promotion_countable": True, "markets": _flags(True, m.MARKETS),
             "parser_v2_verified": None, "shadow_stage_captured": None}]})


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


def test_a_used_row_whose_status_is_not_available_holds_the_look(tmp_path, monkeypatch):
    """A6: an outcome-blind pre-join count; non-zero holds the look and consumes nothing."""
    inputs = _synthetic(tmp_path, mutate=_set_first_used("v2_status", "stale"))
    with pytest.raises(m.MG1LookHeld, match="held: 1 used rows have a v2_status"):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)
    m.Look(RULE)  # the look is still available


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
    assert pit["pass"] and pit["used_available_after_capture"] == 0 and pit["used_status_not_available"] == 0
    assert pit["disclosed_finite_v2_available_after_capture"] == 1 and payload["coverage_reasons"]["absent"] == 1


def test_replay_against_a_captured_shadow_vector(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    _, rows = m.read_countable(inputs["countable"])
    snaps, bands, _ = m.read_inputs(inputs["layout_root"], rows)
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


@pytest.mark.parametrize("now,match", [(datetime(2026, 11, 28, 23, tzinfo=timezone.utc), "has not closed"),
                                       (datetime(2026, 11, 29, 7, tzinfo=timezone.utc), "not ended in every")])
def test_refusals_before_the_window_closes_and_settles_read_nothing(tmp_path, monkeypatch, now, match):
    inputs = _synthetic(tmp_path)
    with pytest.raises(m.MG1LookRefused, match=match):
        _score(monkeypatch, inputs, now=now)
    assert _nothing_spent(tmp_path)


def _edit_freeze(path, **changes):
    body = json.loads(path.read_text(encoding="utf-8"))
    body.update(changes)
    path.write_text(json.dumps(body), encoding="utf-8")


@pytest.mark.parametrize("change,match", [
    ("absent", "does not exist: the look waits"),
    ({"frozen_at_utc": "2026-11-29T06:00:00+00:00"}, "before the 45th date ended in every"),
    ({"look_id": "b"}, "freeze for look 'mg1'"),
    ("tamper", "nyc label_csv is missing or differs"),
    ("mismatch", "do not match their manifest"),
])
def test_a4_the_look_waits_for_finality_and_the_r24_freeze(tmp_path, monkeypatch, change, match):
    inputs = _synthetic(tmp_path)
    freeze = inputs["label_freeze"]
    if change == "absent":
        freeze.unlink()
    elif change == "tamper":
        csv_path = freeze.parent / "nyc" / "daily" / "daily_summary.csv"
        csv_path.write_bytes(csv_path.read_bytes() + b"\n")
    elif change == "mismatch":
        body = json.loads(freeze.read_text(encoding="utf-8"))
        body["markets"]["denver"]["label_csv_matches_manifest"] = False
        freeze.write_text(json.dumps(body), encoding="utf-8")
    else:
        _edit_freeze(freeze, **change)
    with pytest.raises(m.MG1LookRefused, match=match):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)


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


def test_a_date_counts_iff_some_support_market_day_counts(tmp_path):
    """A3 / R11 (1): the date flag must agree with its market-day flags."""
    day = D0 + timedelta(days=4)
    one = dict(_flags(False), houston=True)
    counted, rows = m.read_countable(_countable(tmp_path / "a.json", markets={day: one}))
    assert day in counted and m.market_day_flags(rows)[(day.isoformat(), "nyc")] is False
    body = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    body["dates"][4]["promotion_countable"] = False
    with pytest.raises(m.MG1LookRefused, match="true iff some support market-day"):
        m._parse_countable(body)


def test_an_extended_window_counts_past_a_non_countable_date(tmp_path, monkeypatch):
    monkeypatch.setattr(window, "MG1_LAST", LAST + timedelta(days=1))
    counted, rows = m.read_countable(_countable(tmp_path / "c.json", _rows(countable_off={D0 + timedelta(days=5)},
                                                                         extra=1)))
    assert len(counted) == 45 and counted[-1] == LAST + timedelta(days=1) and not rows[5]["countable"]


def test_non_countable_market_days_are_dropped_before_the_join(tmp_path, monkeypatch):
    """A3 mask: a counted date's non-countable market-days are not scored."""
    inputs = _synthetic(tmp_path)
    day = D0 + timedelta(days=9)
    _countable(inputs["countable"], markets={day: dict(_flags(True), miami=False, seattle=False)})
    _, payload = _score(monkeypatch, inputs)
    assert payload["inputs"]["market_day_mask"] == {"countable_market_days": 45 * 11 - 2, "masked_market_days": 2}
    assert payload["primary"]["n_market_days"] == 45 * 11 - 2 and payload["counted_dates"]["count"] == 45


def test_a_countable_market_day_without_layout_rows_holds_the_look(tmp_path, monkeypatch):
    """A3 hole check: key-only, before looked_at_utc is stamped; nothing is consumed."""
    hole = (D0 + timedelta(days=20)).isoformat()
    inputs = _synthetic(tmp_path, mutate=lambda s: s[~((s.market == "austin") & (s.date == hole))])
    with pytest.raises(m.MG1LookHeld, match="held: 1 countable market-days have no layout rows"):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)
    _countable(inputs["countable"], markets={date.fromisoformat(hole): dict(_flags(True), austin=False)})
    _, payload = _score(monkeypatch, inputs)  # the same hole, masked as non-countable, scores
    assert payload["inputs"]["market_day_mask"]["masked_market_days"] == 1


def test_write_countable_round_trips_once(tmp_path):
    dates = [{"date": D0 + timedelta(days=k), "markets": _flags(k != 3), "parser_v2_verified": None,
              "shadow_stage_captured": None,
              "caveat_reasons": {"parser_v2_verified": "no outcome-blind source"} if k == 0 else None}
             for k in range(46)]
    monkey_last = D0 + timedelta(days=45)
    path = tmp_path / "countable.json"
    sha = m.write_countable(path, dates)
    assert sha == m.sha256_file(path) and schema_version("mg1_countable") == m.COUNTABLE_SCHEMA
    counted, rows = m._parse_countable(json.loads(path.read_text(encoding="utf-8")))
    assert len(counted) == 45 and counted[-1] == monkey_last and rows[3]["countable"] is False
    assert rows[0]["caveat_reasons"] == {"parser_v2_verified": "no outcome-blind source"}
    with pytest.raises(m.MG1LookRefused, match="written once"):
        m.write_countable(path, dates)
    with pytest.raises(m.MG1LookRefused, match="44 countable"):
        m.write_countable(tmp_path / "short.json", dates[:45] + [dict(dates[45], markets=_flags(False))])
    assert not (tmp_path / "short.json").exists()


def test_a_layout_carrying_labels_or_prices_is_refused_before_the_join(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path, mutate=lambda s: s.assign(winner=0))
    with pytest.raises(AssertionError, match="label/market"):
        _score(monkeypatch, inputs)
    assert not m.started_path(m.MG1_RULE_SHA256).exists()


def test_an_unregistered_entry_point_reads_no_outcome(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    _as_main(monkeypatch, "weather.calibration.mg1_look2")
    with pytest.raises(m.MG1LookRefused, match="not the registered MG-1 look"):
        m.score(**inputs, now=NOW)
    assert _nothing_spent(tmp_path)


def test_a_failure_after_the_join_is_aborted_and_still_receipted(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)

    def broken(ladder, bucket):
        raise m.MG1LookRefused("a label bucket falls in 0 bands of its snapshot's ladder, not one")

    monkeypatch.setattr(m, "winner_band", broken)
    with pytest.raises(m.MG1LookRefused, match="falls in 0 bands"):
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
    inputs = _synthetic(tmp_path)
    argv = ["run", "--rule", str(RULE), "--layout", str(inputs["layout_root"]), "--countable",
            str(inputs["countable"]), "--label-freeze", str(inputs["label_freeze"]), "--market",
            str(inputs["market"]), "--out", str(inputs["out"])]
    assert m.main(argv) == 2 and "has not closed" in capsys.readouterr().err
    assert not m.started_path(m.MG1_RULE_SHA256).exists()
