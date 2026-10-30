"""Lane L3 new-city ECMWF ENS forward recorder (tools/research/new_city_ens_forward_recorder.py; DRAFT, not registered).

Guards: new-city ENS stations vs config/locations.json, rebinding of the reused L13 module, the output root, imports,
PowerShell parse and control characters (incident 2026-10-30, docs/research/new-city-thin-markets-2026-10-30.md).

Detail:
- the five stations match config/locations.json (station id and coordinates);
- configure() rebinds the reused module's station set, grid corners, wanted indexes, schema and recorder class
  without touching L13's own module objects;
- the default output root is the new-city root, and L13's root is refused;
- the module imports nothing credential-bearing;
- both PowerShell scripts parse;
- the new files hold no control characters other than CRLF/LF;
- the launcher pins both recorder blobs.
L13's own tests cover the decoder, receipts and guards of the reused module.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys

import pytest

from weather.paths import REPO_ROOT

RESEARCH = REPO_ROOT / "tools" / "research"
_spec = importlib.util.spec_from_file_location("new_city_ens_forward_recorder", RESEARCH / "new_city_ens_forward_recorder.py")
nce = importlib.util.module_from_spec(_spec)
sys.modules["new_city_ens_forward_recorder"] = nce
_spec.loader.exec_module(nce)


def test_stations_match_locations_config():
    locs = {l["id"]: l for l in json.loads((REPO_ROOT / "config/locations.json").read_text(encoding="utf-8"))["locations"]}
    assert len(nce.NEW_CITY_STATIONS) == 5 and len({s[1] for s in nce.NEW_CITY_STATIONS}) == 5
    for market, icao, lat, lon in nce.NEW_CITY_STATIONS:
        loc = locs[market]
        assert loc["settlement"]["station_id"] == icao
        assert (loc["coordinates"]["lat"], loc["coordinates"]["lon"]) == (lat, lon)


def test_configure_rebinds_the_reused_module_only(monkeypatch):
    for name in ("STATIONS", "CORNERS", "WANTED", "SCHEMA", "code_identity", "Recorder"):
        monkeypatch.setattr(nce.ens, name, getattr(nce.ens, name))  # restored after the test
    l13_stations = nce.ens.STATIONS
    assert len(l13_stations) == 12
    nce.configure()
    assert nce.ens.STATIONS == nce.NEW_CITY_STATIONS and nce.ens.SCHEMA == "l3_new_city_ens_forward/1"
    assert set(nce.ens.CORNERS) == {"MPMG", "SBGR", "ZSQD", "LTAC", "UUWW"}
    assert nce.ens.WANTED == sorted({i for c in nce.ens.CORNERS.values() for i in c["idx"]})
    assert nce.ens.Recorder is nce.NewCityRecorder
    assert [r["icao"] for r in nce.ens.station_table()] == ["MPMG", "SBGR", "ZSQD", "LTAC", "UUWW"]
    assert set(nce.code_identity()) == {"new_city_ens_forward_recorder.py", "ecmwf_ens_forward_recorder.py"}


def test_refuses_l13_output_root():
    with pytest.raises(SystemExit, match="L13"):
        nce.main(["--out", nce.L13_OUT, "--print-stations"])


def test_default_out_is_the_new_city_root(monkeypatch):
    seen = {}
    monkeypatch.setattr(nce, "configure", lambda: None)
    monkeypatch.setattr(nce.ens, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    nce.main(["--once"])
    assert seen["argv"][:2] == ["--out", nce.DEFAULT_OUT] and "new_city_ens" in nce.DEFAULT_OUT


def test_module_imports_nothing_credential_bearing():
    src = (RESEARCH / "new_city_ens_forward_recorder.py").read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert mods <= {"__future__", "hashlib", "importlib.util", "sys", "pathlib"}, mods
    for banned in ("dotenv", "py_clob_client", "Authorization", "private_key", "api_key", ".env"):
        assert banned not in src


@pytest.mark.spawns
@pytest.mark.parametrize("name", ["new_city_ens_forward_recorder_launch.ps1",
                                  "register_new_city_ens_forward_recorder_task.ps1"])
def test_powershell_scripts_parse(name):
    cmd = ("$t = $null; $e = $null; "
           f"[void][System.Management.Automation.Language.Parser]::ParseFile('{RESEARCH / name}', [ref]$t, [ref]$e); "
           "'ERRORS=' + @($e).Count; foreach ($x in $e) { $x.Message }")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", cmd], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "ERRORS=0" in result.stdout, result.stdout


@pytest.mark.parametrize("rel", [
    "tools/research/new_city_ens_forward_recorder.py",
    "tools/research/new_city_ens_forward_recorder_launch.ps1",
    "tools/research/register_new_city_ens_forward_recorder_task.ps1",
    "tests/sources/test_new_city_ens_forward_recorder.py",
    "tests/sources/test_new_city_ens_forward_recorder_registrar.py",
])
def test_no_control_characters_other_than_line_endings(rel):
    data = (REPO_ROOT / rel).read_bytes()
    bad = sorted({b for b in data if (b < 0x20 and b not in (0x0A, 0x0D)) or b == 0x7F})
    assert not bad, f"{rel}: control bytes {bad}"
    assert data.replace(b"\r\n", b"").count(b"\r") == 0, f"{rel}: lone CR"


def test_launcher_pins_both_recorder_blobs():
    text = (RESEARCH / "new_city_ens_forward_recorder_launch.ps1").read_text(encoding="ascii")
    for name in ("new_city_ens_forward_recorder.py", "ecmwf_ens_forward_recorder.py"):
        raw = (RESEARCH / name).read_bytes().replace(b"\r\n", b"\n")
        blob = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()
        assert f"{name}' = '{blob}'" in text, name
    assert "'*new_city_ens_forward_recorder*'" in text and "'*ecmwf_ens_forward_recorder*'" not in text
