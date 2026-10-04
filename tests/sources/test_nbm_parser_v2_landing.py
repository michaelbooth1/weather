"""Landing controls for parser v2 on retained NOAA station blocks; no outcomes."""
from datetime import timedelta
from pathlib import Path

import pytest

from weather.sources.nbm_probabilistic_tmax import (
    NBM_NBP_TXN_CYCLES,
    NBM_PROB_TMAX_FEATURE_COLUMNS,
    _parse_issue_time,
    _parse_pair_row,
    _row_code,
    parse_nbp_station_tmax,
    parse_nbp_station_tmax_v1,
    station_nbp_block,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "nbm_target_fix"
BLOCKS = sorted([*FIXTURES.glob("20260917T*.txt"), FIXTURES / "p0" / "20260917T00Z-KLGA.txt",
                 FIXTURES / "p0" / "20260917T12Z-KLGA.txt"])


def _maximum_valid_times(path):
    station = path.stem.split("-")[1]
    block = station_nbp_block(path.read_text(), station)
    issue = _parse_issue_time(block[0])
    rows = {_row_code(line): _parse_pair_row(line) for line in block if _row_code(line)}
    leads = [lead for pair in rows["FHR"] for lead in pair if lead is not None]
    return issue, [issue + timedelta(hours=lead) for lead in leads if (issue + timedelta(hours=lead)).hour == 0]


@pytest.mark.parametrize("path", BLOCKS, ids=lambda p: p.stem)
def test_cycles_from_12z_publish_no_maximum_for_the_issue_date(path):
    """NOAA labels a maximum at 00Z for the 12Z-06Z window named by its daytime date.

    That window for the issue date opens at 12Z on the issue date. A bulletin
    issued at 12Z or later is issued inside (or at the start of) that window,
    and its first published period is the 12Z minimum, so its first maximum is
    the following day's. 00/01/07Z bulletins still carry the issue date's.
    """
    issue, maxima = _maximum_valid_times(path)
    issue_day_max_label = issue.replace(hour=0) + timedelta(days=1)
    window_opens = issue.replace(hour=12)
    assert issue.hour in NBM_NBP_TXN_CYCLES
    if issue.hour < 12:
        assert maxima[0] == issue_day_max_label and issue < window_opens
    else:
        assert issue >= window_opens
        assert issue_day_max_label not in maxima
        assert maxima[0] == issue_day_max_label + timedelta(days=1)
        station = path.stem.split("-")[1]
        today = parse_nbp_station_tmax(path.read_text(), station, issue.date())
        assert (today["available"], today["reason"]) == (False, "target_max_not_in_cycle")


def test_version_one_replay_keeps_its_original_live_only_fields():
    path = FIXTURES / "20260917T07Z-KLGA.txt"
    payload = parse_nbp_station_tmax_v1(path.read_text(), "KLGA", "2026-09-17")
    assert payload["available"] and "parser_version" not in payload
    assert payload["live_only_fields"] == list(NBM_PROB_TMAX_FEATURE_COLUMNS)
    assert len(payload["live_only_fields"]) == 15
