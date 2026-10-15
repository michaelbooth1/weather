"""PL-1 reader and fetch guard: embargo windows and per-basis point-in-time visibility.

Guards: docs/operations/EVIDENCE_HOST.md (DLv2 plan S4 verify row: first_seen > as_of invisible; FULL
window refused; OUTCOME window refuses outcome_join and allows capture_check; stitched/archive_proxy
refused for PIT; the fetch guard refuses an embargo event date). Window dates come only from the two
code owners (maker_core.shadow.admission, weather.mg1_reserved_window); none is hard-coded here.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

import pytest

from maker_core.shadow.admission import EMBARGO_WINDOWS, FULL, OUTCOME
from weather.evidence import envelope as env
from weather.evidence.embargo import EmbargoRefused, check_read, embargo_guard, read_refusal
from weather.evidence.journal import EvidenceJournal
from weather.evidence.reader import read
from weather.mg1_reserved_window import window as mg1_window

FULL_START = next(date.fromisoformat(s) for s, _, scope, _ in EMBARGO_WINDOWS if scope == FULL)
OUTCOME_DAY = next(date.fromisoformat(s) for s, _, scope, _ in EMBARGO_WINDOWS if scope == OUTCOME) + timedelta(2)
OPEN_DAY = FULL_START - timedelta(days=40)  # before every window


def _clock(value):
    state = {"now": value}
    return state, lambda: state["now"]


def _write_day(root, day, rows, family="fam"):
    """rows: (key, minute, basis, provider_time, event_date)."""
    state, clock = _clock(datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc))
    with EvidenceJournal(root, family, clock=clock) as journal:
        for key, minute, basis, provider_time, event_date in sorted(rows, key=lambda r: r[1]):
            state["now"] = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=minute)
            journal.record_poll("ch", [{"key": key, "body": {"k": key}, "envelope": env.envelope(
                basis=basis, parser_version="t-1", provider_time=provider_time, event_date=event_date)}])


@pytest.mark.parametrize("seed", range(5))
def test_rows_first_seen_after_as_of_are_invisible_to_every_purpose(tmp_path, seed):
    rng = random.Random(seed)
    rows = [(f"k{i}", rng.randrange(0, 1400), env.LIVE_RECEIPT, None, None) for i in range(40)]
    _write_day(tmp_path, OPEN_DAY, rows)
    cut = rng.randrange(0, 1400)
    as_of = datetime.combine(OPEN_DAY, datetime.min.time(), tzinfo=timezone.utc) + timedelta(minutes=cut)
    for purpose in ("capture_check", "outcome_join", "candidate=t"):
        result = read("fam", env.utc_text(as_of), purpose, days=[OPEN_DAY.isoformat()], root=tmp_path)
        assert {r["key"] for r in result.rows} == {k for k, m, *_ in rows if m <= cut}
        assert all(env.parse_utc(r["first_seen_utc"]) <= as_of for r in result.rows)
        assert result.hidden["after_as_of"] == sum(1 for _, m, *_ in rows if m > cut)


@pytest.mark.parametrize("purpose", ["capture_check", "outcome_join", "candidate=t"])
def test_full_window_refuses_every_purpose_before_opening_a_file(tmp_path, purpose):
    day = FULL_START + timedelta(days=1)
    (tmp_path / "fam" / day.isoformat() / "00-0123456789ab").mkdir(parents=True)
    (tmp_path / "fam" / day.isoformat() / "00-0123456789ab" / "rows.jsonl").write_bytes(b"not json\n")
    with pytest.raises(EmbargoRefused) as refused:
        read("fam", "2030-01-01T00:00:00Z", purpose, days=[OPEN_DAY.isoformat(), day.isoformat()],
             root=tmp_path)
    assert refused.value.reason == "full_window"


def test_outcome_window_refuses_outcome_join_and_allows_capture_check(tmp_path):
    _write_day(tmp_path, OUTCOME_DAY, [("a", 5, env.LIVE_RECEIPT, None, None)])
    as_of = "2030-01-01T00:00:00Z"
    assert [r["key"] for r in read("fam", as_of, "capture_check", days=[OUTCOME_DAY.isoformat()],
                                    root=tmp_path).rows] == ["a"]
    for purpose in ("outcome_join", "candidate=t"):
        with pytest.raises(EmbargoRefused) as refused:
            read("fam", as_of, purpose, days=[OUTCOME_DAY.isoformat()], root=tmp_path)
        assert refused.value.reason == "outcome_window"


def test_mg1_reserved_days_refuse_outcome_purposes():
    start, end = mg1_window()
    probe = start if end is not None else start + timedelta(days=60)
    assert read_refusal(probe, "capture_check") is None
    assert read_refusal(probe, "outcome_join") in ("outcome_window", "mg1_reserved_window")
    assert read_refusal(probe, "candidate=t") in ("outcome_window", "mg1_reserved_window")
    check_read(OPEN_DAY, "outcome_join")


def test_row_event_date_inside_a_window_is_dropped_on_an_open_day(tmp_path):
    rows = [("open", 1, env.LIVE_RECEIPT, None, OPEN_DAY.isoformat()),
            ("full", 2, env.LIVE_RECEIPT, None, (FULL_START + timedelta(1)).isoformat())]
    _write_day(tmp_path, OPEN_DAY, rows)
    result = read("fam", "2030-01-01T00:00:00Z", "capture_check", days=[OPEN_DAY.isoformat()], root=tmp_path)
    assert [r["key"] for r in result.rows] == ["open"] and result.hidden["embargoed_event_date"] == 1


def test_pit_reads_refuse_stitched_and_archive_rows_and_tag_stamped_rows(tmp_path):
    base = datetime.combine(OPEN_DAY, datetime.min.time(), tzinfo=timezone.utc)
    stamp = env.utc_text(base + timedelta(minutes=10))
    rows = [("live", 1, env.LIVE_RECEIPT, None, None), ("stitched", 2, env.STITCHED_NO_ISSUE, stamp, None),
            ("archive", 3, env.ARCHIVE_PROXY, stamp, None), ("stamp", 4, env.PROVIDER_STAMP, stamp, None),
            ("s3", 5, env.S3_LASTMODIFIED, stamp, None)]
    _write_day(tmp_path, OPEN_DAY, rows)
    day = [OPEN_DAY.isoformat()]
    late = env.utc_text(base + timedelta(hours=2))
    no_margin = read("fam", late, "candidate=m", days=day, root=tmp_path)
    assert [r["key"] for r in no_margin.rows] == ["live"]
    assert no_margin.hidden["basis_refused_for_pit"] == 2
    assert no_margin.hidden["stamped_without_declared_margin"] == 2
    tagged = read("fam", late, "candidate=m", days=day, root=tmp_path, pit_margin_seconds=600)
    assert sorted(r["key"] for r in tagged.rows) == ["live", "s3", "stamp"]
    assert {r.get("pit_tag") for r in tagged.rows if r["key"] != "live"} == {env.PIT_UNPROVEN_TAG}
    early = read("fam", env.utc_text(base + timedelta(minutes=15)), "candidate=m", days=day, root=tmp_path,
                 pit_margin_seconds=600)
    assert [r["key"] for r in early.rows] == ["live"]
    every = read("fam", late, "capture_check", days=day, root=tmp_path)
    assert len(every.rows) == 5


@pytest.mark.parametrize("mode", ["backfill", "sweep"])
def test_fetch_guard_refuses_an_embargoed_event_date(mode):
    for day in (FULL_START, FULL_START + timedelta(days=3), OUTCOME_DAY, mg1_window()[0]):
        with pytest.raises(EmbargoRefused) as refused:
            embargo_guard("vr3_gamma", day.isoformat(), mode=mode, today=OUTCOME_DAY + timedelta(days=90))
        assert refused.value.reason == "fetch_event_date_embargoed"
    assert embargo_guard("vr3_gamma", OPEN_DAY, mode=mode)["decision"] == "allowed"


def test_live_mode_allows_todays_capture_but_not_a_past_date():
    today = OUTCOME_DAY
    assert embargo_guard("ob1", today, mode="live", today=today)["decision"] == "allowed_live_capture"
    assert embargo_guard("ob1", today - timedelta(days=1), mode="live", today=today)
    with pytest.raises(EmbargoRefused) as refused:
        embargo_guard("ob1", today - timedelta(days=5), mode="live", today=today)
    assert refused.value.reason == "live_mode_for_past_event_date"
