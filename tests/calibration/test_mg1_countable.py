"""MG-1 countability, counts-only (R11 Head 2; rulings A3/T5 2026-11-03), on synthetic ledgers only.

Guards: A3 (a date counts iff at least one support market-day satisfies Clarification 4 in the latest
revision); the 0 / 1 / all / pending cases; pending is non-countable in --final; the clock refusal before
2026-11-14T00:00Z; only ended dates are read; report mode carries per-date status only; --final writes
``mg1_countable/2`` with ``markets{m: bool}`` through ``mg1_look.write_countable`` and round-trips through
``read_countable``; it refuses when the 45th date is after the recorded MG1_LAST; no sentinel label byte reaches
any output.
"""
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from functools import partial

import pytest

from weather import mg1_reserved_window as window
from weather.calibration import mg1_countable as c
from weather.calibration import mg1_look

D0, LAST = window.window()
MARKETS = tuple(mg1_look.support_markets())
FIRST = MARKETS[0]
REPORT_NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
FINAL_NOW = datetime(2026, 12, 5, 12, tzinfo=timezone.utc)
SENTINEL = "SENTINEL-LABEL-7f3a"
SENTINEL_NUMBER = 987654.125


def _row(m, d, countable, revision=1, slug=None):
    return {"event_slug": slug or f"highest-temperature-in-{m}-on-{d.isoformat()}", "market_id": m,
            "target_date": d.isoformat(), "revision_number": revision, "promotion_countable": countable,
            "material_coverage_grade": "strict_complete" if countable else "insufficient",
            "polymarket_reconciliation": {"event_closed": True, "winning_markets": [{"label": SENTINEL}]},
            "settlement_high": SENTINEL_NUMBER, "winning_band": SENTINEL, "settlement_bucket": SENTINEL_NUMBER}


def _days(through):
    return [D0 + timedelta(days=k) for k in range((through - D0).days + 1)]


def write_ledger(root, through, override=None):
    """Every market-day countable unless ``override(m, d)`` returns False, None (no row) or a row list."""
    for m in MARKETS:
        rows = []
        for d in _days(through):
            value = override(m, d) if override else True
            if value is None:
                continue
            rows += value if isinstance(value, list) else [_row(m, d, value)]
        path = root / m / "ledger.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return root



def freeze_keys(root, now, missing=()):
    """Real hashed R24 metadata, but sentinel CSV bytes: no label reader may be called."""
    through = mg1_look.latest_final_date(now)
    frozen = mg1_look.settled_at(through)
    folder = root / "frozen"
    entries = {}
    for m in MARKETS:
        keys = [d.isoformat() for d in _days(through) if (m, d.isoformat()) not in missing]
        paths = {"label_csv": folder / m / "daily/daily_summary.csv",
                 "wu_daily_summary": folder / m / "wu/daily_summary.csv",
                 "manifest": folder / m / "manifest.json"}
        for path in paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SENTINEL, encoding="utf-8")
        paths["manifest"].write_text(json.dumps({"label_dates": keys, "skipped_dates": {},
                "label_source_counts": {"synthetic": len(keys)}}), encoding="utf-8")
        entries[m] = {k: {"sha256": c.sha256_file(v)} for k, v in paths.items()}
        entries[m].update(label_dates=keys, skipped_dates={}, label_csv_matches_manifest=True,
                          wu_daily_summary_matches_manifest=True)
    path = folder / "freeze_receipt.json"
    path.write_text(json.dumps({"schema_version": mg1_look.FREEZE_RECEIPT_SCHEMA, "look_id": "mg1",
        "through": through.isoformat(), "frozen_at_utc": frozen.isoformat(), "audit_status": "OK",
        "markets": entries}), encoding="utf-8")
    return path


def _call(name, *, ledger_root, now=None, **kwargs):
    now = now or FINAL_NOW
    return getattr(c, name)(ledger_root=ledger_root, label_freeze=freeze_keys(ledger_root, now), now=now, **kwargs)


_report = partial(_call, "report")
_final_rows = partial(_call, "final_rows")
_final = partial(_call, "final")

def _status(result, d):
    return {r["date"]: r["status"] for r in result["dates"]}[d.isoformat()]


def test_report_refuses_before_the_p1_instant(tmp_path):
    root = write_ledger(tmp_path, LAST)
    with pytest.raises(c.CountableRefused, match="opens at"):
        _report(ledger_root=root, now=c.NOT_BEFORE_UTC - timedelta(seconds=1))
    with pytest.raises(c.CountableRefused, match="opens at"):
        _final_rows(ledger_root=root, now=c.NOT_BEFORE_UTC - timedelta(seconds=1))


@pytest.mark.parametrize("case, override, status", [
    ("zero countable", lambda m: False, c.NON_COUNTABLE),
    ("one countable", lambda m: m == "seattle", c.COUNTABLE),
    ("all countable", lambda m: True, c.COUNTABLE),
    ("all pending", lambda m: None, c.PENDING),
    ("non-countable and pending", lambda m: None if m == "nyc" else False, c.PENDING),
    ("one countable, rest pending", lambda m: True if m == "miami" else None, c.COUNTABLE),
])
def test_a3_date_status(tmp_path, case, override, status):
    target = D0 + timedelta(days=10)
    root = write_ledger(tmp_path, REPORT_NOW.date(), lambda m, d: override(m) if d == target else True)
    result = _report(ledger_root=root, now=REPORT_NOW)
    assert _status(result, target) == status, case
    assert _status(result, target - timedelta(days=1)) == c.COUNTABLE


def test_latest_revision_decides_and_two_events_are_not_countable(tmp_path):
    up, down, twin = (D0 + timedelta(days=k) for k in (3, 4, 5))

    def override(m, d):
        if d == up:
            return [_row(m, d, False), _row(m, d, True, revision=2)]
        if d == down:
            return [_row(m, d, True), _row(m, d, False, revision=2)]
        if d == twin:
            return [_row(m, d, True), _row(m, d, True, slug="another-event")]
        return True

    result = _report(ledger_root=write_ledger(tmp_path, REPORT_NOW.date(), override), now=REPORT_NOW)
    assert [_status(result, d) for d in (up, down, twin)] == [c.COUNTABLE, c.NON_COUNTABLE, c.NON_COUNTABLE]


def test_report_reads_only_ended_dates_and_says_when_mg1_last_must_move(tmp_path):
    bad = {D0 + timedelta(days=2), D0 + timedelta(days=20)}
    root = write_ledger(tmp_path, LAST + timedelta(days=5), lambda m, d: d not in bad)
    result = _report(ledger_root=root, now=REPORT_NOW)
    assert result["through"] == (REPORT_NOW.date() - timedelta(days=1)).isoformat()  # 11-20 has not ended in LA
    assert result["counts"][c.NON_COUNTABLE] == 2
    assert result["required_mg1_last"] == (LAST + timedelta(days=2)).isoformat()
    assert result["extend_mg1_last"] is True and result["recorded_mg1_last"] == LAST.isoformat()
    assert set(result["ledger_sha256"]) == set(MARKETS)
    assert all(set(r) == {"date", "status"} for r in result["dates"])  # nothing per market
    clean = _report(ledger_root=write_ledger(tmp_path / "clean", LAST), now=REPORT_NOW)
    assert clean["extend_mg1_last"] is False and clean["required_mg1_last"] == LAST.isoformat()


def test_final_writes_the_masked_list_and_it_round_trips(tmp_path):
    partial = D0 + timedelta(days=7)
    root = write_ledger(tmp_path, LAST + timedelta(days=3),
                        lambda m, d: (m == FIRST or None) if d == partial else True)
    out = tmp_path / "mg1_countable.json"
    result = _final(ledger_root=root, out=out, now=FINAL_NOW)
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["schema"] == mg1_look.COUNTABLE_SCHEMA and result["last"] == LAST.isoformat()
    assert len(body["dates"]) == mg1_look.N_DATES and all(r["countable"] for r in body["dates"])
    row = {r["date"]: r for r in body["dates"]}[partial.isoformat()]
    assert row["markets"] == {m: m == FIRST for m in MARKETS}  # pending market-days are masked out
    assert all(r["parser_v2_verified"] is None and r["shadow_stage_captured"] is None for r in body["dates"])
    assert all(set(r["caveat_reasons"]) == {"parser_v2_verified", "shadow_stage_captured"} for r in body["dates"])
    assert result["sha256"] == c.sha256_file(out) and set(result["ledger_sha256"]) == set(MARKETS)
    counted, rows = mg1_look.read_countable(out)
    assert counted[0] == D0 and counted[-1] == LAST and len(rows) == mg1_look.N_DATES
    flags = mg1_look.market_day_flags(rows)
    assert flags[(partial.isoformat(), FIRST)] is True
    assert not any(flags[(partial.isoformat(), m)] for m in MARKETS[1:])
    with pytest.raises(c.CountableRefused, match="written once"):
        _final(ledger_root=root, out=out, now=FINAL_NOW)


@pytest.mark.parametrize("missing", [False, None])  # a non-countable date, or a pending one
def test_final_refuses_until_mg1_last_is_extended(tmp_path, missing):
    hole = D0 + timedelta(days=12)
    root = write_ledger(tmp_path, LAST + timedelta(days=5), lambda m, d: missing if d == hole else True)
    out = tmp_path / "list.json"
    with pytest.raises(c.CountableRefused, match="extend the window"):
        _final(ledger_root=root, out=out, now=FINAL_NOW)
    assert not out.exists()


def test_final_refuses_too_early(tmp_path):
    root = write_ledger(tmp_path, LAST + timedelta(days=3))
    out = tmp_path / "x.json"
    with pytest.raises(c.CountableRefused, match="at least 2 days"):
        _final(ledger_root=root, out=out, now=datetime(2026, 11, 29, 20, tzinfo=timezone.utc))
    assert not out.exists()


def test_no_sentinel_label_byte_in_any_output(tmp_path, capsys):
    root = write_ledger(tmp_path, LAST + timedelta(days=3))
    texts = [json.dumps(_report(ledger_root=root, now=REPORT_NOW))]
    out = tmp_path / "list.json"
    _final(ledger_root=root, out=out, now=FINAL_NOW)
    texts.append(out.read_text(encoding="utf-8"))
    for text in texts:
        assert SENTINEL not in text and str(SENTINEL_NUMBER) not in text and "987654" not in text


def test_the_cli_reports_a_refusal_with_exit_2(tmp_path, capsys):
    assert c.main(["--ledger-root", str(tmp_path / "absent"), "--label-freeze", str(tmp_path / "absent.json")]) == 2  # clock or missing ledger, both refuse
    assert json.loads(capsys.readouterr().out)["status"] == "refused"
    assert c.main(["--ledger-root", str(tmp_path), "--label-freeze", str(tmp_path / "absent.json"), "--final"]) == 2


def test_report_schema_is_registered():
    from weather.schema_families import schema_version

    assert c.REPORT_SCHEMA == schema_version("mg1_countable_report") == "mg1_countable_report/2"


def test_import_refuses_from_a_production_package():
    saved = sys.modules.pop("weather.calibration.mg1_countable")
    try:
        with pytest.raises(ImportError, match="research-only"):
            exec("import weather.calibration.mg1_countable", {"__name__": "weather.serving.anything"})
    finally:
        sys.modules["weather.calibration.mg1_countable"] = saved


def test_the_module_reads_no_label_reader_or_panel():
    source = Path(c.__file__).read_text(encoding="utf-8")
    for name in ("venue_label_reader", "read_venue_labels", "settlement_high", "winning_band", "p_market_yes"):
        assert name not in source, name
    assert date(2026, 11, 14) == c.NOT_BEFORE_UTC.date()


def test_support_follows_the_owner_a1_constant(tmp_path, monkeypatch):
    root = write_ledger(tmp_path, LAST)
    monkeypatch.setattr(mg1_look, "A1_DENVER_SCORED", False)
    result = _report(ledger_root=root, now=REPORT_NOW)
    assert "denver" not in result["ledger_sha256"] and result["support_market_count"] == 10
