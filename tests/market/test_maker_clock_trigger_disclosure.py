"""Disclosure counter for the clock supporting-trigger fix. Fictional trigger rows only."""
from datetime import date, datetime, timedelta, timezone
import gzip
import json
import math

import pytest

from weather.market.maker_plugin.inputs import timestamp
from tools.research import maker_clock_trigger_disclosure as tool

DAY = "2026-09-27"
NYC = "highest-temperature-in-nyc-on-september-27-2026"
TOR = "highest-temperature-in-toronto-on-september-27-2026"
AT = datetime(2026, 9, 27, 18, 0, 30, tzinfo=timezone.utc)  # 14:00 in New York and Toronto


def row(reason, source, *, slug=NYC, market="nyc", unit="F", at=AT, previous=70.4, current=71.6,
        observed=None, target="2026-09-27"):
    observed = (at - timedelta(minutes=2)).isoformat() if observed is None else observed
    return {"reason": reason, "source": source, "previous_value": previous, "current_value": current,
            "previous_bucket": None if previous is None else round(previous),
            "current_bucket": None if current is None else round(current),
            "observed_at": observed, "detail": "Fictional.", "market_id": market, "event_slug": slug,
            "target_date": target, "unit": unit, "current_captured_at_utc": at.isoformat(),
            "previous_captured_at_utc": (at - timedelta(minutes=1)).isoformat()}


def old_new_high(row, as_of):
    """Literal copy of the pre-fix trigger filters (clock.py @ 501f4757) for new_high only."""
    from weather.market.maker_plugin.inputs import event_identity
    spec, target = event_identity(row["event_slug"])
    detected = timestamp(row["current_captured_at_utc"])
    observed = timestamp(row["observed_at"]) if row.get("observed_at") else None
    if detected > as_of or (observed and observed > detected):
        return set()
    if detected.astimezone(spec.tz).date() != target or (
            observed and observed.astimezone(spec.tz).date() != target):
        return set()
    if row.get("market_id") != spec.id or row.get("unit") != spec.unit:
        return set()
    if row.get("target_date") != target.isoformat():
        return set()
    previous, current = row.get("previous_value"), row.get("current_value")
    if current is None or not math.isfinite(float(current)):
        return set()
    if previous is not None and float(current) <= float(previous):
        return set()
    if row.get("reason") != "wu_history_high_increased" or row.get("source") != "wu_history":
        return set()
    return {detected.replace(second=0, microsecond=0)}


def write(path, records, gz=False):
    raw = "".join(json.dumps(r) + "\n" for r in records).encode()
    with (gzip.open(path, "wb") if gz else open(path, "wb")) as handle:
        handle.write(raw)
    return path


@pytest.mark.parametrize("offset", range(16))
def test_every_reserved_day_is_refused_before_any_file_opens(offset, tmp_path, capsys):
    day = (date(2026, 9, 30) + timedelta(days=offset)).isoformat()
    missing = tmp_path / "never-opened.jsonl"
    assert tool.main(["--date", "2026-09-27", "--date", day, "--triggers", str(missing)]) == 3
    assert "reserved_window_day_refused" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("text", ["20260927", "2026-9-27", "2026-09-27T00:00:00", ""])
def test_noncanonical_days_are_refused(text, tmp_path):
    assert tool.main(["--date", text, "--triggers", str(tmp_path / "x.jsonl")]) == 3


@pytest.mark.parametrize("text", ["2026-09-29", "2026-10-16"])
def test_window_edges_are_allowed(text):
    assert tool.allowed_day(text).isoformat() == text


def test_counts_new_only_minutes_per_day_and_market(tmp_path):
    rows = [
        row("wu_history_high_increased", "wu_history", current=72.),          # old and new
        row("metar_temp_bucket_crossed", "metar"),                            # same minute as WU: not new-only
        row("metar_temp_bucket_crossed", "metar", at=AT + timedelta(minutes=7)),            # new only
        row("wu_current_max_since_7am_bucket_crossed", "wu_current", at=AT + timedelta(minutes=9)),  # new only
        row("metar_temp_bucket_crossed", "metar", at=AT + timedelta(minutes=11), current=70.),  # decrease
        row("metar_became_fresh", "metar", previous=None, current=None),      # no value
        # Toronto SWOB: observed_at is a local "HH:MM", which the clock refuses.
        row("eccc_swob_latest_temp_bucket_crossed", "eccc_swob", slug=TOR, market="toronto", unit="C",
            previous=20.4, current=21.6, observed="14:00"),
        row("metar_temp_bucket_crossed", "metar", slug=TOR, market="toronto", unit="C",
            previous=20.4, current=21.6, at=AT + timedelta(minutes=3)),
    ]
    # A reserved-day row (detected 2026-09-30) is dropped even though its event is allowed-day shaped.
    reserved = row("metar_temp_bucket_crossed", "metar", at=datetime(2026, 9, 30, 3, tzinfo=timezone.utc))
    nested = {"record_type": "observation_trigger_event", "event_slug": NYC,
              "trigger_context": {"triggers": rows[:4]}}
    flat_path = write(tmp_path / "observation_triggers.jsonl", [nested, *rows[4:], reserved])
    conditions = tmp_path / "conditions.json"
    conditions.write_text(json.dumps({NYC: 11}))
    out = tmp_path / "result.json"
    assert tool.main(["--date", DAY, "--triggers", str(flat_path), "--conditions", str(conditions),
                      "--out", str(out)]) == 0
    result = json.loads(out.read_text())
    cells = {c["market_id"]: c for c in result["cells"]}
    assert set(cells) == {"nyc", "toronto"}
    nyc, tor = cells["nyc"], cells["toronto"]
    assert nyc["trigger_rows"] == 6  # the reserved row is not counted anywhere
    assert (nyc["old_new_high_event_minutes"], nyc["new_new_high_event_minutes"], nyc["new_only_event_minutes"]) == (
        1, 3, 2)
    assert nyc["new_only_condition_minutes"] == 22 and nyc["row_errors"] == {}
    assert (tor["new_only_event_minutes"], tor["new_only_condition_minutes"]) == (1, None)
    assert list(tor["row_errors"]) == ["eccc_swob:ValueError:Invalid isoformat string: '14:00'"]
    assert result["by_day"][DAY]["new_only_event_minutes"] == 3
    assert result["by_day"][DAY]["new_only_condition_minutes"] == 22
    assert result["by_day"][DAY]["events_without_condition_count"] == 1
    assert "reserved_window" not in result["skipped_rows"]
    assert tool.main(["--date", DAY, "--triggers", str(flat_path), "--out", str(out)]) == 2  # never overwrites


def test_gzip_rotation_and_other_days_are_read_only_for_wanted_days(tmp_path):
    other = row("metar_temp_bucket_crossed", "metar", at=AT - timedelta(days=1),
                slug="highest-temperature-in-nyc-on-september-26-2026", target="2026-09-26")
    path = write(tmp_path / "observation_triggers.jsonl.gz",
                 [row("metar_temp_bucket_crossed", "metar"), other], gz=True)
    cells = tool.count(tool.trigger_rows([path], [date(2026, 9, 27)], __import__("collections").Counter()))
    assert [(c["day"], c["new_only_event_minutes"]) for c in cells] == [(DAY, 1)]


def test_old_side_equals_the_literal_pre_fix_filters():
    variants = []
    for reason, source in [("wu_history_high_increased", "wu_history"), ("metar_temp_bucket_crossed", "metar"),
                           ("wu_history_high_increased", "metar"), ("metar_temp_above_wu_floor", "metar")]:
        for change in [{}, {"current_value": 70.}, {"unit": "C"}, {"market_id": "chicago"},
                       {"observed_at": (AT + timedelta(minutes=1)).isoformat()}, {"target_date": "2026-09-28"},
                       {"previous_value": None}]:
            variants.append(dict(row(reason, source), **change))
    for item in variants:
        as_of = timestamp(item["current_captured_at_utc"])
        assert tool._new_high_minutes(item, old=True) == old_new_high(item, as_of), item
    # The new side differs from the old exactly on valid increasing supporting rows.
    assert tool._new_high_minutes(row("metar_temp_bucket_crossed", "metar"), old=False) == {AT.replace(second=0)}
    assert tool._new_high_minutes(row("metar_temp_bucket_crossed", "metar"), old=True) == set()


def test_tool_never_decides_or_writes_without_out(tmp_path, capsys):
    path = write(tmp_path / "t.jsonl", [row("wu_history_high_increased", "wu_history", current=99.)])
    before = sorted(p.name for p in tmp_path.iterdir())
    assert tool.main(["--date", DAY, "--triggers", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["cells"][0]["new_new_high_event_minutes"] == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == before
