"""Guards: T046 FIX7 synthetic provenance, embargo hygiene and optional local format scans."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import runpy

import pytest

from weather.market.metar_reports import parse_metar
from weather.paths import data_path, repo_path

ROOT = repo_path("tests", "fixtures", "weather_expansion")
CORPUS = ROOT / "inputs" / "metar-72h"
REAL = data_path("fixtures", "weather_expansion_real", "metar-72h")
START, END = datetime(2026, 9, 20, tzinfo=timezone.utc), datetime(2026, 9, 24, tzinfo=timezone.utc)
MANIFEST = json.loads((CORPUS / "provenance.json").read_text())
CASES = json.loads((CORPUS / "cases.json").read_text())["cases"]


def test_seeded_generator_reproduces_every_byte():
    generator = runpy.run_path(str(ROOT / "make_synthetic_metars.py"), run_name="fixture_generator")
    expected = generator["build"]()
    assert set(expected) == {p.relative_to(CORPUS).as_posix() for p in CORPUS.rglob("*") if p.is_file()}
    assert generator["build"]() == expected
    for name, text in expected.items():
        assert (CORPUS / name).read_bytes() == text.encode("utf-8")


def test_provenance_hashes_bind_generator_inventory_and_all_payloads():
    assert MANIFEST["kind"] == "synthetic" and MANIFEST["seed"] == 20260920
    assert MANIFEST["generator_sha256"] == hashlib.sha256((ROOT / "make_synthetic_metars.py").read_bytes()).hexdigest()
    assert MANIFEST["quirk_inventory_sha256"] == hashlib.sha256((ROOT / "metar_quirks.json").read_bytes()).hexdigest()
    assert MANIFEST["station_metadata_sha256"] == hashlib.sha256((ROOT / "inputs/stations.json").read_bytes()).hexdigest()
    inventory = json.loads((ROOT / "metar_quirks.json").read_text())
    for station in inventory["stations"]:
        assert set(station) == {"icao", "cadence_minutes", "t_groups", "render_formats"}
        assert set(station["render_formats"]) <= {"wind_mps", "automated_cloud", "runway_feet_without_r"}
    for name, digest in MANIFEST["files"].items():
        assert hashlib.sha256((CORPUS / name).read_bytes()).hexdigest() == digest


def test_tracked_streams_use_only_seeded_development_dates():
    for path in (CORPUS / "per-station").glob("*.txt"):
        for raw in path.read_text().splitlines():
            record = parse_metar(raw, START, END)
            if record.observation_time is not None:
                assert datetime(2026, 9, 20, tzinfo=timezone.utc) <= record.observation_time <= datetime(2026, 9, 23, tzinfo=timezone.utc)
            else:
                assert "unreadable_time" in {case["name"] for case in CASES if case["raw"] == raw}
    assert not any("2026-11" in p.read_text() for p in CORPUS.rglob("*") if p.is_file())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_named_format_quirks_survive(case):
    record = parse_metar(case["raw"], START, END)
    critical = [flag for flag in record.flags if flag.startswith(("malformed_", "ambiguous_"))]
    assert Counter(critical) == Counter(case["expected_flags"])
    assert case["raw"] in (CORPUS / "per-station" / (case["station"] + ".txt")).read_text().splitlines()


def require_real_survey(root):
    if not (root / "summary.csv").is_file() or not (root / "per-station").is_dir():
        pytest.skip("Optional embargoed real survey absent; normal tests use seeded synthetic METAR fixtures")
    if os.environ.get("WEATHER_EXPANSION_REAL_FORMAT_AUDIT") != "1":
        pytest.skip("Real survey is embargoed; format-only audit requires explicit named authorization and opt-in")
    return root


def test_missing_real_survey_has_an_explicit_skip(tmp_path, monkeypatch):
    monkeypatch.setitem(test_optional_real_survey_format_inventory.__globals__, "REAL", tmp_path)
    with pytest.raises(pytest.skip.Exception, match="Optional embargoed real survey absent"):
        test_optional_real_survey_format_inventory()


def test_archive_presence_alone_never_enables_a_real_data_read(tmp_path, monkeypatch):
    (tmp_path / "summary.csv").write_text("")
    (tmp_path / "per-station").mkdir()
    monkeypatch.setitem(test_optional_real_survey_format_inventory.__globals__, "REAL", tmp_path)
    monkeypatch.delenv("WEATHER_EXPANSION_REAL_FORMAT_AUDIT", raising=False)
    with pytest.raises(pytest.skip.Exception, match="requires explicit named authorization and opt-in"):
        test_optional_real_survey_format_inventory()


def test_optional_real_survey_format_inventory():
    # Format-only audit of the ignored archive: no temperature conversion,
    # daily extrema, labels, outcomes or prices. Clean checkouts skip this.
    root = require_real_survey(REAL)
    inventory = json.loads((ROOT / "metar_quirks.json").read_text())
    assert sorted(p.stem for p in (root / "per-station").glob("*.txt")) == sorted(s["icao"] for s in inventory["stations"])
    observed = set()
    for path in (root / "per-station").glob("*.txt"):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            observed.update(name for name, pattern in {
                "speci": r"^SPECI ", "cor": r"\bCOR\b", "auto": r"\bAUTO\b",
                "negative_body": r"\bM\d{2}/", "valid_t_group": r"\bT[01]\d{7}\b",
                "taf_validity": r"\b\d{4}/\d{4}\b", "visibility_fraction": r"\d/\dSM\b",
            }.items() if re.search(pattern, line))
    assert {"speci", "cor", "auto", "negative_body", "valid_t_group", "taf_validity", "visibility_fraction"} <= observed
