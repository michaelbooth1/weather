"""MG-1 look: freeze audit-status and FREEZE_THROUGH holds, the dry ``check-keys`` run, and the exit codes.

Guards: master's rulings of 2026-11-03 on the MG-1 look-day runbook draft (b015497a3):

- (1) the look holds unless the R24 freeze receipt's ``audit_status`` is ``OK``;
- (3) ``check-keys`` runs every pre-stamp metadata check and exits without stamping. It writes a counts-only
  record;
- (4) refused exits 2 and held exits 4;
- (6) FREEZE_THROUGH is the latest date that has ended in every scored MG-1 market at the freeze. Any other
  ``through`` holds, and one before the 45th date holds first.

Synthetic fixtures only (the helpers of ``test_mg1_look``); no data/, no label value is read.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from tests.calibration.test_mg1_look import (  # noqa: F401  (_root autouse; pre_answer_branches fixture)
    D0,
    NOW,
    RULE,
    _as_main,
    _edit_freeze,
    _market_manifest,
    _nothing_spent,
    _root,
    _score,
    _synthetic,
    pre_answer_branches,
)
from weather.calibration import mg1_look as m
from weather.schema_families import schema_version


def _no_outcome_reads(monkeypatch):
    from weather.backtesting import venue_label_reader as vlr

    def forbidden(*args, **kwargs):
        raise AssertionError("an outcome, label or price was read by a pre-stamp check")

    monkeypatch.setattr(vlr, "read_venue_labels", forbidden)
    monkeypatch.setattr(pd, "read_csv", forbidden)
    monkeypatch.setattr(m, "load_outcomes", forbidden)


def _argv(inputs, out, layout=False):
    argv = ["check-keys", "--rule", str(RULE), "--countable", str(inputs["countable"]), "--label-freeze",
            str(inputs["label_freeze"]), "--out", str(out)]
    return argv + (["--layout", str(inputs["layout_root"])] if layout else [])


def _run_argv(inputs):
    return ["run", "--rule", str(RULE), "--layout", str(inputs["layout_root"]), "--countable",
            str(inputs["countable"]), "--label-freeze", str(inputs["label_freeze"]), "--market",
            str(inputs["market"]), "--out", str(inputs["out"])]


def test_the_exit_codes_are_distinct():
    assert (m.EXIT_REFUSED, m.EXIT_HELD) == (2, 4)
    assert issubclass(m.MG1LookHeld, m.MG1LookRefused)


@pytest.mark.parametrize("status", ["STATION_DRIFT", "ok", None])
def test_a_freeze_whose_audit_status_is_not_ok_holds_before_the_stamp(tmp_path, monkeypatch, status):
    inputs = _synthetic(tmp_path)
    _edit_freeze(inputs["label_freeze"], audit_status=status)
    _no_outcome_reads(monkeypatch)
    with pytest.raises(m.MG1LookHeld, match="held: the label freeze's audit status is .*not 'OK'"):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)
    m.Look(RULE)  # the look is still available


@pytest.mark.parametrize("at,expected", [
    (datetime(2026, 11, 30, 12, tzinfo=timezone.utc), date(2026, 11, 29)),
    (datetime(2026, 11, 30, 8, tzinfo=timezone.utc), date(2026, 11, 29)),   # Pacific midnight: 11-29 just ended
    (datetime(2026, 11, 30, 7, 59, tzinfo=timezone.utc), date(2026, 11, 28)),
    (datetime(2026, 11, 30, 5, tzinfo=timezone.utc), date(2026, 11, 28)),   # ended in New York, not in Seattle
])
def test_freeze_through_is_the_latest_date_ended_in_every_scored_market(at, expected):
    assert m.latest_final_date(at) == expected
    assert m.settled_at(expected) <= at < m.settled_at(expected + timedelta(days=1))


@pytest.mark.parametrize("through,match", [
    ("2026-11-28", "runs through 2026-11-28, not FREEZE_THROUGH 2026-11-29"),
    ("2026-11-30", "runs through 2026-11-30, not FREEZE_THROUGH 2026-11-29"),
    ("2026-11-27", "runs through 2026-11-27, before the countable date 2026-11-28"),
])
def test_a_freeze_through_other_than_freeze_through_holds(tmp_path, monkeypatch, through, match):
    inputs = _synthetic(tmp_path)
    _edit_freeze(inputs["label_freeze"], through=through)
    _no_outcome_reads(monkeypatch)
    with pytest.raises(m.MG1LookHeld, match="held: .*" + match + ".*label metadata inconsistency"):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)


@pytest.mark.usefixtures("pre_answer_branches")
def test_check_keys_passes_without_stamping_or_reading_an_outcome(tmp_path, monkeypatch, capsys):
    inputs = _synthetic(tmp_path)
    _no_outcome_reads(monkeypatch)
    monkeypatch.setattr(m, "_now_utc", lambda: NOW)
    out = tmp_path / "check" / "check_keys.json"
    assert m.main(_argv(inputs, out, layout=True)) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "pass"
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["schema"] == m.CHECK_SCHEMA == schema_version("mg1_check_keys")
    assert record["stamped"] is False and record["layout_checked"] is True and "reason" not in record
    assert record["market_checked"] is False
    assert record["label_key_check"]["countable_market_days"] == 45 * 11
    assert record["label_freeze"]["audit_status"] == "OK" and record["label_freeze"]["through"] == "2026-11-29"
    assert record["counted_dates"] == {"count": 45, "first": "2026-10-15", "last": "2026-11-28"}
    assert record["entry_sha256"] == m.module_sha256()
    assert set(record) == {"schema", "checked_at_utc", "entry_sha256", "stamped", "layout_checked",
                           "market_checked", "owner_constants", "countable_sha256", "counted_dates", "label_freeze",
                           "label_key_check", "verdict"}
    assert _nothing_spent(tmp_path) and not m.receipt_path(m.MG1_RULE_SHA256).exists()
    # written once; a second dry run with the same record path refuses (exit 2), and the look is still available
    assert m.main(_argv(inputs, out)) == m.EXIT_REFUSED
    assert "written once" in capsys.readouterr().err
    m.Look(RULE)


@pytest.mark.parametrize("edit,code,verdict,match", [
    ("drop", 4, "held", "no label key in the frozen label metadata"),
    ("drift", 4, "held", "audit status is 'STATION_DRIFT'"),
    ("through", 4, "held", "not FREEZE_THROUGH"),
    ("hole", 4, "held", "no layout rows"),
    ("absent", 2, "refused", "does not exist: the look waits"),
    ("early", 2, "refused", "has not closed"),
])
def test_check_keys_records_every_outcome_and_exits_by_verdict(tmp_path, monkeypatch, capsys, edit, code,
                                                               verdict, match):
    hole = (D0 + timedelta(days=20)).isoformat()
    kw = {"drop": {"drop_labels": {("nyc", D0 + timedelta(days=12))}},
          "hole": {"mutate": lambda s: s[~((s.market == "austin") & (s.date == hole))]}}.get(edit, {})
    inputs = _synthetic(tmp_path, **kw)
    if edit == "drift":
        _edit_freeze(inputs["label_freeze"], audit_status="STATION_DRIFT")
    elif edit == "through":
        _edit_freeze(inputs["label_freeze"], through="2026-11-28")
    elif edit == "absent":
        inputs["label_freeze"].unlink()
    now = datetime(2026, 11, 28, 23, tzinfo=timezone.utc) if edit == "early" else NOW
    monkeypatch.setattr(m, "_now_utc", lambda: now)
    _no_outcome_reads(monkeypatch)
    out = tmp_path / "check_keys.json"
    assert m.main(_argv(inputs, out, layout=edit == "hole")) == code
    printed = json.loads(capsys.readouterr().out)
    record = json.loads(out.read_text(encoding="utf-8"))
    assert printed["verdict"] == record["verdict"] == verdict and match in record["reason"]
    assert record["stamped"] is False and "label_key_check" not in record
    assert _nothing_spent(tmp_path)


def test_check_keys_without_layout_skips_only_the_layout_hole_check(tmp_path, monkeypatch):
    hole = (D0 + timedelta(days=20)).isoformat()
    inputs = _synthetic(tmp_path, mutate=lambda s: s[~((s.market == "austin") & (s.date == hole))])
    path, record = m.check_keys(rule=RULE, countable=inputs["countable"], label_freeze=inputs["label_freeze"],
                                out=tmp_path / "c.json", now=NOW)
    assert record["verdict"] == "pass" and record["layout_checked"] is False


@pytest.mark.parametrize("edit,code,stream", [("drop", 4, "held: "), ("drift", 4, "held: "),
                                              ("absent", 2, "refused: ")])
def test_the_run_command_exits_4_on_a_hold_and_2_on_a_refusal(tmp_path, monkeypatch, capsys, edit, code, stream):
    kw = {"drop_labels": {("nyc", D0 + timedelta(days=12))}} if edit == "drop" else {}
    inputs = _synthetic(tmp_path, **kw)
    if edit == "drift":
        _edit_freeze(inputs["label_freeze"], audit_status="STATION_DRIFT")
    elif edit == "absent":
        inputs["label_freeze"].unlink()
    monkeypatch.setattr(m, "_now_utc", lambda: NOW)
    _as_main(monkeypatch)
    assert m.main(_run_argv(inputs)) == code
    assert capsys.readouterr().err.startswith(stream)
    assert _nothing_spent(tmp_path)


# ----------------------------------------------------------------------------- the --market pre-stamp check
# Master 2026-11-03, --market ruling 3: the file exists, its parquet schema names exactly the three columns, its
# sha equals the host producer's manifest, and the manifest's range_ok and duplicate_free are true. No price value
# is read before the stamp.


def _no_price_value_reads(monkeypatch):
    import pyarrow.parquet as pq

    def forbidden(*args, **kwargs):
        raise AssertionError("a price value was read by the pre-stamp --market check")

    monkeypatch.setattr(pd, "read_parquet", forbidden)
    monkeypatch.setattr(pq, "read_table", forbidden)
    monkeypatch.setattr(pq, "ParquetFile", forbidden)


def test_the_market_check_reads_only_schema_shas_and_booleans(tmp_path, monkeypatch):
    inputs = _synthetic(tmp_path)
    _no_price_value_reads(monkeypatch)
    record = m.market_check(inputs["market"], inputs["layout_root"])
    assert record["columns"] == list(m.MARKET_COLUMNS) and record["range_ok"] and record["duplicate_free"]
    assert record["market_sha256"] == m.sha256_file(inputs["market"])
    assert set(record) == {"market_sha256", "manifest_sha256", "columns", "range_ok", "duplicate_free"}
    assert (m.MARKET_MANIFEST, m.MARKET_MANIFEST_SCHEMA) == ("mg1_market_manifest.json", "mg1_market/1")


def _break_market(inputs, edit):
    market, layout = inputs["market"], inputs["layout_root"]
    if edit == "absent":
        market.unlink()
    elif edit == "no_manifest":
        (market.parent / m.MARKET_MANIFEST).unlink()
    elif edit == "extra_column":
        frame = pd.read_parquet(market)
        frame["best_bid"] = 0.0
        frame.to_parquet(market, index=False)
        _market_manifest(market, layout)
    elif edit == "index_column":
        pd.read_parquet(market).set_index("row_key").to_parquet(market)
        _market_manifest(market, layout)
    elif edit == "sha":
        _market_manifest(market, layout, market_sha256="0" * 64)
    elif edit == "look_b":
        _market_manifest(market, layout, look_id="b")
    elif edit == "schema":
        _market_manifest(market, layout, schema="mg1_market/0")
    elif edit == "other_layout":
        _market_manifest(market, layout, layout={"snapshots_sha256": "1" * 64, "bands_sha256": "2" * 64})
    elif edit == "range":
        _market_manifest(market, layout, range_ok=False)
    elif edit == "duplicates":
        _market_manifest(market, layout)
        manifest = market.parent / m.MARKET_MANIFEST
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data.pop("duplicate_free")
        manifest.write_text(json.dumps(data), encoding="utf-8")


MARKET_EDITS = [
    ("absent", 2, "does not exist: the look waits for the host producer"),
    ("no_manifest", 2, "manifest .* is missing or unreadable"),
    ("extra_column", 2, "not exactly \\['row_key', 'band_index', 'p_market_yes'\\]"),
    ("index_column", 2, "not exactly"),
    ("sha", 2, "differs from its manifest's market_sha256"),
    ("look_b", 2, "is for look 'b', not 'mg1'"),
    ("schema", 2, "is not mg1_market/1"),
    ("other_layout", 2, "built on another layout"),
    ("range", 4, "held: the --market manifest's range_ok is False, not true"),
    ("duplicates", 4, "held: the --market manifest's duplicate_free is None, not true"),
]


@pytest.mark.parametrize("edit,code,match", MARKET_EDITS)
def test_a_bad_market_file_refuses_or_holds_before_the_stamp(tmp_path, monkeypatch, capsys, edit, code, match):
    inputs = _synthetic(tmp_path)
    _break_market(inputs, edit)
    monkeypatch.setattr(m, "_now_utc", lambda: NOW)
    monkeypatch.setattr(m, "load_outcomes", lambda *a, **k: (_ for _ in ()).throw(AssertionError("joined")))
    expected = m.MG1LookHeld if code == m.EXIT_HELD else m.MG1LookRefused
    with pytest.raises(expected, match=match):
        _score(monkeypatch, inputs)
    assert _nothing_spent(tmp_path)
    _as_main(monkeypatch)
    assert m.main(_run_argv(inputs)) == code
    assert _nothing_spent(tmp_path)
    m.Look(RULE)  # the look is still available


@pytest.mark.parametrize("edit,code,match", [MARKET_EDITS[4], MARKET_EDITS[8]])
def test_check_keys_runs_the_market_check_when_given(tmp_path, monkeypatch, capsys, edit, code, match):
    inputs = _synthetic(tmp_path)
    monkeypatch.setattr(m, "_now_utc", lambda: NOW)
    _no_outcome_reads(monkeypatch)
    ok = tmp_path / "ok.json"
    assert m.main(_argv(inputs, ok, layout=True) + ["--market", str(inputs["market"])]) == 0
    record = json.loads(ok.read_text(encoding="utf-8"))
    assert record["market_checked"] is True and record["market_check"]["range_ok"] is True
    _break_market(inputs, edit)
    bad = tmp_path / "bad.json"
    assert m.main(_argv(inputs, bad, layout=True) + ["--market", str(inputs["market"])]) == code
    record = json.loads(bad.read_text(encoding="utf-8"))
    assert "market_check" not in record and record["verdict"] == ("held" if code == 4 else "refused")
    assert _nothing_spent(tmp_path)
