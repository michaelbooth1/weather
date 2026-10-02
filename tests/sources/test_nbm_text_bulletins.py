from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.sources.nbm_text_bulletins import (
    NbmTextBulletinError,
    extract_station_blocks,
    recent_cycles,
    text_bulletin_url,
    text_cycle_key,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nbm_text"
CYCLE = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
STATIONS = ("CYYZ", "KLGA", "KATL", "KAUS", "KORD", "KDAL", "KBKF", "KHOU", "KLAX", "KMIA", "KSFO", "KSEA")


def chunks(data: bytes, size: int = 997):
    return (data[i:i + size] for i in range(0, len(data), size))


@pytest.mark.parametrize("product,name", [("nbh", "blend_nbhtx.t12z.excerpt.txt"),
                                          ("nbs", "blend_nbstx.t12z.excerpt.txt")])
def test_keeps_only_market_station_blocks_verbatim(product, name):
    raw = (FIXTURES / name).read_bytes()
    result = extract_station_blocks(chunks(raw), product=product, cycle_time=CYCLE, stations=STATIONS)
    assert result.stations_found == sorted(STATIONS)
    assert result.stations_missing == [] and result.incomplete_stations() == []
    assert "CYTZ" not in result.blocks and "086092" not in result.blocks  # neighbours dropped
    assert result.product_versions == {"5.0"}
    text = result.extract_text()
    for station in STATIONS:
        block = "\n".join(result.blocks[station]) + "\n"
        assert block.encode("latin-1") in raw  # byte-exact, trailing spaces kept
        assert result.blocks[station][0].split()[0] == station
    assert len(text) < len(raw)


def test_chunk_boundaries_do_not_change_the_extract():
    raw = (FIXTURES / "blend_nbhtx.t12z.excerpt.txt").read_bytes()
    texts = {
        extract_station_blocks(chunks(raw, size), product="nbh", cycle_time=CYCLE, stations=STATIONS).extract_text()
        for size in (1, 64, 4096, len(raw))
    }
    assert len(texts) == 1


def test_wrong_cycle_or_product_is_malformed():
    raw = (FIXTURES / "blend_nbhtx.t12z.excerpt.txt").read_bytes()
    with pytest.raises(NbmTextBulletinError, match="requested"):
        extract_station_blocks(chunks(raw), product="nbh", cycle_time=CYCLE.replace(hour=13), stations=STATIONS)
    with pytest.raises(NbmTextBulletinError, match="expected NBS"):
        extract_station_blocks(chunks(raw), product="nbs", cycle_time=CYCLE, stations=STATIONS)


def test_duplicate_station_block_is_malformed():
    raw = (FIXTURES / "blend_nbhtx.t12z.excerpt.txt").read_bytes()
    first = extract_station_blocks(chunks(raw), product="nbh", cycle_time=CYCLE, stations=STATIONS)
    block = "\n".join(first.blocks["KLGA"]).encode("latin-1")
    with pytest.raises(NbmTextBulletinError, match="duplicate KLGA"):
        extract_station_blocks(chunks(raw + b"\n" + block + b"\n"), product="nbh", cycle_time=CYCLE,
                               stations=STATIONS)


def test_truncated_block_is_reported_incomplete():
    raw = (FIXTURES / "blend_nbhtx.t12z.excerpt.txt").read_bytes()
    cut = raw.index(b"KSEA   NBM") + 200  # header plus the UTC row only
    result = extract_station_blocks(chunks(raw[:cut]), product="nbh", cycle_time=CYCLE, stations=STATIONS)
    assert result.incomplete_stations() == ["KSEA"]


def test_urls_cycle_keys_and_candidates():
    assert text_bulletin_url("NBH", CYCLE) == (
        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/blend.20261001/12/text/blend_nbhtx.t12z")
    assert text_bulletin_url("nbs", CYCLE, "https://noaa-nbm-grib2-pds.s3.amazonaws.com/").endswith(
        ".com/blend.20261001/12/text/blend_nbstx.t12z")
    assert text_cycle_key("nbs", CYCLE) == "nbm-nbs:20261001T12Z"
    assert recent_cycles(CYCLE.replace(minute=50), 2) == [CYCLE, CYCLE.replace(hour=11), CYCLE.replace(hour=10)]
    with pytest.raises(NbmTextBulletinError):
        text_bulletin_url("nbp", CYCLE)
