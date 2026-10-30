"""Lane L3 new-city price forward recorder (tools/research/new_city_price_forward_recorder.py; DRAFT, not registered).

Guards: new-city market table vs config/locations.json, T+0/T+1 local dates, reused allowlist, schema and combined sha,
imports, PowerShell parse and control characters (incident 2026-10-30, docs/research/new-city-thin-markets-2026-10-30.md).

Detail:
- the market table matches config/locations.json (slug prefix and time zone);
- T+0 and T+1 rows are dated by market-local date;
- the reused T+1 module keeps its URL allowlist, and its own globals are untouched by import;
- the schema and combined recorder sha256 show in every cycle record;
- the module imports nothing credential-bearing;
- both PowerShell scripts parse with the PowerShell parser;
- the branch's new files hold no control characters other than CRLF/LF (the 2026-10-30 launcher trap).
No network: the T+1 tests' in-memory fake serves Gamma events and CLOB books.
"""
from __future__ import annotations

import ast
import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys

import pytest

from weather.paths import REPO_ROOT

RESEARCH = REPO_ROOT / "tools" / "research"
_spec = importlib.util.spec_from_file_location("new_city_price_forward_recorder",
                                               RESEARCH / "new_city_price_forward_recorder.py")
nc = importlib.util.module_from_spec(_spec)
sys.modules["new_city_price_forward_recorder"] = nc
_spec.loader.exec_module(nc)
_tspec = importlib.util.spec_from_file_location("_t1_price_tests", REPO_ROOT / "tests/sources/test_t1_price_forward_recorder.py")
t1tests = importlib.util.module_from_spec(_tspec)
_tspec.loader.exec_module(t1tests)

UTC = dt.timezone.utc


def test_market_table_matches_locations_config():
    locs = {l["id"]: l for l in json.loads((REPO_ROOT / "config/locations.json").read_text(encoding="utf-8"))["locations"]}
    assert len(nc.NEW_CITY_MARKETS) == 9
    for mid, (prefix, tz) in nc.NEW_CITY_MARKETS.items():
        city = mid.removesuffix("-lowest")
        loc = locs[city]
        want = loc["polymarket"]["event_slug_prefix"]
        if mid.endswith("-lowest"):
            want = "lowest-" + want.removeprefix("highest-")
        assert prefix == want and tz == loc["timezone"], mid
        assert nc.STATIONS[city] == loc["settlement"]["station_id"], city
    for city in nc.STATIONS:
        assert locs[city]["market_unit"] == "C"


class Fake(t1tests.Fake):
    def request(self, method, url, body=None):
        nc.t1.check_url(method, url, body)  # the reused module's allowlist, not the test module's copy
        return super().request(method, url, body)


def test_t0_and_t1_rows_by_local_date_with_schema_and_combined_sha(tmp_path):
    t = dt.datetime(2026, 10, 30, 21, 0, 15, tzinfo=UTC)  # 16:00 Panama (10-30), 05:00 Qingdao (10-31)
    markets = {k: nc.NEW_CITY_MARKETS[k] for k in ("panama-city", "qingdao")}
    rec = nc.NewCityRecorder(tmp_path / "out", Fake(), markets=markets, clock=lambda: t, sleep=lambda s: None,
                             horizons=(0, 1), min_free_gb=0.0)
    cycle = rec.step()
    assert cycle["ran"] and cycle["complete"]
    got = nc.t1.read_jsonl(rec.out / "20261030" / "prices.jsonl")
    events, cyc = got[:-1], got[-1]
    assert [(r["market"], r["horizon"], r["target_date"]) for r in events] == [
        ("panama-city", 0, "2026-10-30"), ("panama-city", 1, "2026-10-31"),
        ("qingdao", 0, "2026-10-31"), ("qingdao", 1, "2026-11-01")]
    assert events[2]["event_slug"] == "highest-temperature-in-qingdao-on-october-31-2026"
    assert all(r["schema"] == "l3_new_city_price_forward/1" for r in got)
    want = hashlib.sha256((RESEARCH / "new_city_price_forward_recorder.py").read_bytes() + b"\0"
                          + (RESEARCH / "t1_price_forward_recorder.py").read_bytes()).hexdigest()
    assert cyc["recorder_sha256"] == want == rec.code_sha256


def test_horizon_three_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        nc.NewCityRecorder(tmp_path / "out", Fake(), clock=lambda: dt.datetime.now(UTC), horizons=(0, 3),
                           min_free_gb=0.0)


def test_reused_module_allowlist_still_refuses_other_endpoints():
    for method, url, body in [("GET", "https://gamma-api.polymarket.com/events?tag_slug=x", None),
                              ("POST", "https://clob.polymarket.com/order", [{"token_id": "1" * 20}]),
                              ("GET", "https://clob.polymarket.com/auth/api-key", None)]:
        with pytest.raises(Exception):
            nc.t1.check_url(method, url, body)


def test_import_leaves_the_t1_module_used_by_other_tests_alone():
    assert t1tests.rc.SCHEMA == "l3_t1_price_forward/1" and t1tests.rc.HORIZONS == (1, 2)
    assert nc.t1 is not t1tests.rc


def test_module_imports_nothing_credential_bearing():
    src = (RESEARCH / "new_city_price_forward_recorder.py").read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert mods <= {"__future__", "argparse", "hashlib", "importlib.util", "json", "os", "sys", "pathlib"}, mods
    for banned in ("dotenv", "py_clob_client", "Authorization", "POLY_", "private_key", "api_key", ".env"):
        assert banned not in src


@pytest.mark.spawns
@pytest.mark.parametrize("name", ["new_city_price_forward_recorder_launch.ps1",
                                  "register_new_city_price_forward_recorder_task.ps1"])
def test_powershell_scripts_parse(name):
    cmd = ("$t = $null; $e = $null; "
           f"[void][System.Management.Automation.Language.Parser]::ParseFile('{RESEARCH / name}', [ref]$t, [ref]$e); "
           "'ERRORS=' + @($e).Count; foreach ($x in $e) { $x.Message }")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "ERRORS=0" in result.stdout, result.stdout


@pytest.mark.parametrize("rel", [
    "tools/research/new_city_price_forward_recorder.py",
    "tools/research/new_city_price_forward_recorder_launch.ps1",
    "tools/research/register_new_city_price_forward_recorder_task.ps1",
    "tools/research/temperature_market_survey.py",
    "tests/sources/test_new_city_price_forward_recorder.py",
    "tests/sources/test_new_city_price_forward_recorder_registrar.py",
])
def test_no_control_characters_other_than_line_endings(rel):
    data = (REPO_ROOT / rel).read_bytes()
    bad = sorted({b for b in data if (b < 0x20 and b not in (0x0A, 0x0D)) or b == 0x7F})
    assert not bad, f"{rel}: control bytes {bad}"
    assert data.replace(b"\r\n", b"").count(b"\r") == 0, f"{rel}: lone CR"


def test_launcher_pins_both_recorder_blobs():
    text = (RESEARCH / "new_city_price_forward_recorder_launch.ps1").read_text(encoding="ascii")
    for name in ("new_city_price_forward_recorder.py", "t1_price_forward_recorder.py"):
        raw = (RESEARCH / name).read_bytes().replace(b"\r\n", b"\n")
        blob = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
        assert f"{name}' = '{blob}'" in text, name
