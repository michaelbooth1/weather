"""Light, serial credential-free historical observations download; no scoring.

Endpoint verified 2026-09-21 against the IEM's own asos.py?help documentation.
Separate routine/special requests retain report classification independently of
whether the raw METAR text includes a SPECI prefix. Never writes repository data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

STATIONS = {"CYYZ": "CYYZ", **{s: s[1:] for s in (
    "KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO")}}
ENDPOINT = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"


def fetch(output):
    output = Path(output).resolve()
    if "data" in output.parts or "weather-mirror" in str(output).lower():
        raise ValueError("download must use dedicated scratch outside data/mirrors")
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    records = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    existing = {r["file"]: r for r in records}
    for icao, station in STATIONS.items():
        for report_type in (3, 4):
            name = f"{icao}-{report_type}.csv"
            target = output / name
            if name in existing:
                if hashlib.sha256(target.read_bytes()).hexdigest() != existing[name]["sha256"]:
                    raise ValueError(f"existing download changed: {name}")
                continue
            params = {"station": station, "data": "all", "sts": "2026-08-01T00:00:00Z",
                      "ets": "2026-09-20T12:00:00Z", "tz": "UTC", "format": "onlycomma",
                      "latlon": "no", "elev": "no", "missing": "M", "trace": "T",
                      "report_type": str(report_type)}
            url = ENDPOINT + "?" + urllib.parse.urlencode(params)
            time.sleep(1.1)
            with urllib.request.urlopen(url, timeout=45) as response:
                raw = response.read(20_000_001)
            if len(raw) > 20_000_000 or not raw.startswith(b"station,valid,"):
                raise ValueError(f"unexpected/oversize response: {name}")
            with target.open("xb") as stream:
                stream.write(raw)
            records.append({"station": icao, "report_type": report_type, "file": name,
                            "url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                            "bytes": len(raw), "downloaded_at": datetime.now(timezone.utc).isoformat()})
            manifest_path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            print(f"{name}: {len(raw)} bytes", flush=True)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    fetch(parser.parse_args().output)
