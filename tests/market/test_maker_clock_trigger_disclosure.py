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


def write(path, records, gz=False, raw_lines=()):
    raw = "".join(json.dumps(r) + "\n" for r in records).encode() + b"".join(raw_lines)
    with (gzip.open(path, "wb") if gz else open(path, "wb")) as handle:
        handle.write(raw)
    return path


def live(tmp_path, records, gz=False, raw_lines=()):
    folder = tmp_path / "snapshots"
    folder.mkdir(exist_ok=True)
    name = "observation_triggers.jsonl" + (".gz" if gz else "")
    return write(folder / name, records, gz, raw_lines)


@pytest.mark.parametrize("offset", range(16))
def test_every_reserved_day_is_refused_before_any_file_opens(offset, tmp_path, capsys):
    day = (date(2026, 9, 30) + timedelta(days=offset)).isoformat()
    missing = tmp_path / "observation_triggers.jsonl"
    assert tool.main(["--date", "2026-09-27", "--date", day, "--triggers", str(missing)]) == 3
    assert "reserved_window_day_refused" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("text", ["20260927", "2026-9-27", "2026-09-27T00:00:00", ""])
def test_noncanonical_days_are_refused(text, tmp_path):
    assert tool.main(["--date", text, "--triggers", str(tmp_path / "observation_triggers.jsonl")]) == 3


@pytest.mark.parametrize("text", ["2026-09-29", "2026-10-16"])
def test_window_edges_are_allowed(text):
    assert tool.allowed_day(text).isoformat() == text


@pytest.mark.parametrize("name", ["observation_triggers.20260927T000000Z.jsonl", "triggers.jsonl",
                                  "observation_triggers.20260927T000000Z.1.jsonl.gz"])
def test_only_the_live_file_the_exporter_reads_is_accepted(name, tmp_path, capsys):
    path = write(tmp_path / name, [row("metar_temp_bucket_crossed", "metar")])
    assert tool.main(["--date", DAY, "--triggers", str(path)]) == 2
    assert "not_the_live_trigger_file" in capsys.readouterr().err


def test_counts_onsets_and_added_pulled_time(tmp_path):
    rows = [
        row("wu_history_high_increased", "wu_history", current=72., at=AT + timedelta(minutes=30)),  # old pull
        row("metar_temp_bucket_crossed", "metar"),                                     # new only, first onset
        row("metar_temp_bucket_crossed", "metar", at=AT + timedelta(minutes=7)),      # new only
        row("wu_current_max_since_7am_bucket_crossed", "wu_current", at=AT + timedelta(minutes=30)),  # same as WU
        row("metar_temp_bucket_crossed", "metar", at=AT + timedelta(minutes=11), current=70.),  # decrease
        row("metar_became_fresh", "metar", previous=None, current=None),               # no value
    ]
    nested = {"record_type": "observation_trigger_event", "event_slug": NYC,
              "trigger_context": {"triggers": rows[:4]}}
    path = live(tmp_path, [nested, *rows[4:]])
    conditions = tmp_path / "conditions.json"
    conditions.write_text(json.dumps({NYC: 11}))
    out = tmp_path / "result.json"
    assert tool.main(["--date", DAY, "--triggers", str(path), "--conditions", str(conditions),
                      "--out", str(out)]) == 0
    result = json.loads(out.read_text())
    [nyc] = result["cells"]
    assert nyc["trigger_rows_detected_on_day"] == 6 and nyc["clock_unavailable"] is None
    assert nyc["new_only_detection_minutes"] == 2
    assert nyc["first_new_high_utc_new"] == AT.isoformat()
    assert nyc["first_new_high_utc_old"] == (AT + timedelta(minutes=30)).isoformat()
    assert nyc["added_pulled_event_minutes"] == 30.
    assert nyc["added_pulled_condition_minutes"] == 330.
    assert result["by_day"][DAY]["events_with_added_pull"] == 1
    assert set(result) == {"schema", "days", "reserved_window", "by_day", "cells"}
    assert tool.main(["--date", DAY, "--triggers", str(path), "--out", str(out)]) == 2  # never overwrites


def test_no_old_pull_carries_to_end_of_day_and_from_previous_day(tmp_path):
    # Target 09-26 local evening detected on UTC 09-27 01:00: the 09-27 bundle is pulled from there.
    slug = "highest-temperature-in-nyc-on-september-26-2026"
    evening = datetime(2026, 9, 27, 1, 0, tzinfo=timezone.utc)
    early = row("metar_temp_bucket_crossed", "metar", slug=slug, target="2026-09-26",
                at=datetime(2026, 9, 26, 20, tzinfo=timezone.utc))
    late = row("metar_temp_bucket_crossed", "metar", slug=slug, target="2026-09-26", at=evening)
    path = live(tmp_path, [early, late])
    cells = tool.count(tool.trigger_rows(path, [date(2026, 9, 27)]), [date(2026, 9, 27)])
    [cell] = cells
    # The 09-26 row (read as context only) already pulls from the bundle's first minute.
    assert cell["first_new_high_utc_new"] == early["current_captured_at_utc"]
    assert cell["added_pulled_event_minutes"] == 24 * 60.
    assert cell["new_only_detection_minutes"] == 1


def test_bare_hhmm_swob_row_no_longer_makes_the_event_day_unavailable(tmp_path):
    """Before the SWOB time-parse fix, a bare local "HH:MM" observed_at made the Toronto clock raise at
    every minute of the day ("all_day"). It is now read on the target date in the market zone."""
    rows = [
        row("metar_temp_bucket_crossed", "metar", slug=TOR, market="toronto", unit="C",
            previous=20.4, current=21.6, at=AT - timedelta(hours=2)),
        row("eccc_swob_latest_temp_bucket_crossed", "eccc_swob", slug=TOR, market="toronto", unit="C",
            previous=20.4, current=21.6, observed="14:00"),
        row("metar_temp_bucket_crossed", "metar"),
    ]
    path = live(tmp_path, rows)
    out = tmp_path / "r.json"
    assert tool.main(["--date", DAY, "--triggers", str(path), "--out", str(out)]) == 0
    result = json.loads(out.read_text())
    cells = {c["market_id"]: c for c in result["cells"]}
    tor = cells["toronto"]
    assert tor["clock_unavailable"] is None
    assert tor["new_only_detection_minutes"] == 2
    assert tor["added_pulled_event_minutes"] == 479.5  # 16:00:30 UTC (the METAR pull) to end of day.
    assert cells["nyc"]["clock_unavailable"] is None and cells["nyc"]["new_only_detection_minutes"] == 1
    day = result["by_day"][DAY]
    assert (day["events"], day["events_clock_unavailable_all_day"], day["events_with_added_pull"]) == (2, 0, 2)


def test_unparseable_observed_at_adds_no_pull_and_no_unavailability(tmp_path):
    rows = [row("eccc_swob_latest_temp_bucket_crossed", "eccc_swob", slug=TOR, market="toronto", unit="C",
                previous=20.4, current=21.6, observed="not a time")]
    out = tmp_path / "r.json"
    assert tool.main(["--date", DAY, "--triggers", str(live(tmp_path, rows)), "--out", str(out)]) == 0
    [tor] = json.loads(out.read_text())["cells"]
    assert tor["clock_unavailable"] is None and tor["new_only_detection_minutes"] == 0


def test_reserved_undateable_and_overlong_lines_leave_no_trace(tmp_path, monkeypatch):
    clean = [row("metar_temp_bucket_crossed", "metar")]
    base = tmp_path / "a"
    base.mkdir()
    reference = live(base, clean)
    reserved = [
        row("metar_temp_bucket_crossed", "metar", at=datetime(2026, 9, 30, 3, tzinfo=timezone.utc)),
        row("metar_temp_bucket_crossed", "metar", slug="highest-temperature-in-nyc-on-september-30-2026",
            target="2026-09-30", at=datetime(2026, 9, 30, 18, tzinfo=timezone.utc)),
        dict(clean[0], target_date="2026-10-01"),  # dated on an allowed day, but targets a reserved day
        dict(clean[0], current_captured_at_utc="not-a-time"),  # undateable
    ]
    monkeypatch.setattr(tool, "MAX_LINE_BYTES", 2048)
    noisy_dir = tmp_path / "b"
    noisy_dir.mkdir()
    noisy = live(noisy_dir, clean + reserved, raw_lines=[
        b"{not json\n", b"[1, 2]\n", b'{"trigger_context": {"triggers": "x"}}\n',
        b'{"pad": "' + b"x" * 5000 + b'"}\n',  # over-long: skipped, not aborted
        b'{"pad": "' + b"y" * 5000,             # over-long and unterminated at EOF
    ])
    out_a, out_b = tmp_path / "a.json", tmp_path / "b.json"
    assert tool.main(["--date", DAY, "--triggers", str(reference), "--out", str(out_a)]) == 0
    assert tool.main(["--date", DAY, "--triggers", str(noisy), "--out", str(out_b)]) == 0
    assert out_a.read_bytes() == out_b.read_bytes()


def test_gzip_live_variant_and_other_days_are_read_only_for_wanted_days(tmp_path):
    other = row("metar_temp_bucket_crossed", "metar", at=AT - timedelta(days=2),
                slug="highest-temperature-in-nyc-on-september-25-2026", target="2026-09-25")
    path = live(tmp_path, [row("metar_temp_bucket_crossed", "metar"), other], gz=True)
    cells = tool.count(tool.trigger_rows(path, [date(2026, 9, 27)]), [date(2026, 9, 27)])
    assert [(c["day"], c["event_slug"], c["new_only_detection_minutes"]) for c in cells] == [(DAY, NYC, 1)]


def test_old_side_equals_the_literal_pre_fix_filters():
    variants = []
    for reason, source in [("wu_history_high_increased", "wu_history"), ("metar_temp_bucket_crossed", "metar"),
                           ("wu_history_high_increased", "metar"), ("metar_temp_above_wu_floor", "metar")]:
        for change in [{}, {"current_value": 70.}, {"unit": "C"}, {"market_id": "chicago"},
                       {"observed_at": (AT + timedelta(minutes=1)).isoformat()}, {"target_date": "2026-09-28"},
                       {"previous_value": None}]:
            variants.append(dict(row(reason, source), **change))
    minute = lambda times: {t.replace(second=0, microsecond=0) for t in times}
    for item in variants:
        as_of = timestamp(item["current_captured_at_utc"])
        assert minute(tool._new_high_times(item, old=True)) == old_new_high(item, as_of), item
    assert tool._new_high_times(row("metar_temp_bucket_crossed", "metar"), old=False) == {AT}
    assert tool._new_high_times(row("metar_temp_bucket_crossed", "metar"), old=True) == set()


def test_tool_never_decides_or_writes_without_out(tmp_path, capsys):
    path = live(tmp_path, [row("wu_history_high_increased", "wu_history", current=99.)])
    before = sorted(p.name for p in tmp_path.rglob("*"))
    assert tool.main(["--date", DAY, "--triggers", str(path)]) == 0
    [cell] = json.loads(capsys.readouterr().out)["cells"]
    assert cell["first_new_high_utc_new"] == cell["first_new_high_utc_old"] == AT.isoformat()
    assert cell["added_pulled_event_minutes"] == 0.
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
