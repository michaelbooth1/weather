"""Conditional, serial IEM text-guidance download; preserves original issue stamps."""
from datetime import datetime, timezone
import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
import zipfile
import csv

from tools.research.missing_information.fetch_iem import STATIONS

ENDPOINT = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py"


def fetch(output):
    # Endpoint and parameters verified against its official ?help on 2026-09-21.
    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    records = []
    for station in STATIONS:
        if not station.startswith("K"):
            continue
        for model in ("NBS", "NBP", "LAV", "MAV"):
            name = f"{station}-{model}.zip"
            params = dict(pil=model+station[1:], matches=station, fmt="zip", limit=9999,
                          order="asc", sdate="2026-05-10T00:00Z", edate=end)
            url = ENDPOINT + "?" + urllib.parse.urlencode(params)
            row = {"station": station, "model": model, "url": url, "end_exclusive": end}
            time.sleep(1.1)
            try:
                with urllib.request.urlopen(url, timeout=90) as response:
                    raw = response.read(100_000_001)
                if len(raw) > 100_000_000:
                    raise ValueError("response exceeds 100 MB cap")
                # Preserve error responses as evidence, but never call them archives.
                is_zip = zipfile.is_zipfile(io.BytesIO(raw))
                if not is_zip:
                    name = name.removesuffix(".zip") + ".response.txt"
                with (output / name).open("xb") as stream:
                    stream.write(raw)
                row.update(file=name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
                if is_zip:
                    with zipfile.ZipFile(io.BytesIO(raw)) as z:
                        entries = [i for i in z.infolist() if not i.is_dir()]
                        row.update(products=len(entries), first_file=entries[0].filename if entries else None,
                                   last_file=entries[-1].filename if entries else None,
                                   expanded_bytes=sum(i.file_size for i in entries))
                    row["status"] = "LIMIT_REACHED" if len(entries) >= 9999 else ("DOWNLOADED" if entries else "EMPTY")
                else:
                    row["status"] = "NO_ARCHIVE_RESPONSE"
            except Exception as exc:
                row.update(status="ERROR", error=f"{type(exc).__name__}: {exc}")
            row["downloaded_at"] = datetime.now(timezone.utc).isoformat()
            records.append(row)
            (output / "guidance_manifest.json").write_text(json.dumps(records, indent=2)+"\n")
            print(f"{station} {model}: {row['status']} ({row.get('products', 0)} products)", flush=True)
    return records


def fetch_structured(output):
    """Supplement truncated raw-text retention with the documented MOS database.

    GFS is the database's name for the MAV product. NBP has no documented
    structured model here; its retained raw archive is reported separately.
    """
    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    records = []
    for station in STATIONS:
        if not station.startswith("K"):
            continue
        for model in ("NBS", "LAV", "GFS"):
            name = f"{station}-{model}.csv"
            params = dict(station=station, model=model, format="csv", sts="2026-05-10T00:00Z", ets=end)
            url = "https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py?" + urllib.parse.urlencode(params)
            row = dict(station=station, model=model, url=url, requested_start="2026-05-10T00:00Z", requested_end=end)
            time.sleep(1.1)
            try:
                with urllib.request.urlopen(url, timeout=90) as response:
                    raw = response.read(100_000_001)
                if len(raw) > 100_000_000 or not raw.startswith(b"runtime,ftime,model,"):
                    raise ValueError("unexpected MOS response or size")
                with (output/name).open("xb") as stream:
                    stream.write(raw)
                values = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
                runtimes = sorted({v["runtime"] for v in values})
                row.update(file=name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), rows=len(values),
                           runs=len(runtimes), first_run=runtimes[0] if runtimes else None,
                           last_run=runtimes[-1] if runtimes else None, status="DOWNLOADED" if runtimes else "EMPTY")
            except Exception as exc:
                row.update(status="ERROR", error=f"{type(exc).__name__}: {exc}")
            row["downloaded_at"] = datetime.now(timezone.utc).isoformat()
            records.append(row)
            (output/"structured_manifest.json").write_text(json.dumps(records, indent=2)+"\n")
            print(f"{station} {model}: {row['status']} ({row.get('runs',0)} runs)", flush=True)
    return records
