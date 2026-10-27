"""Forward-only free sources (screen F5): DWD MOSMIX_L and ECMWF ENS open data. Small pulls + parsers.

Neither is scored on development dates here: the DWD open server keeps only the latest MOSMIX runs,
and ECMWF ENS needs a GRIB decoder for its packing that this environment does not have (see
``ens_probe``). The pulls exist to build and test the parsers and to measure size and retention.

- MOSMIX_L single-station KMZ: ``https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/
  single_stations/<id>/kml/MOSMIX_L_LATEST_<id>.kmz`` (CC BY 4.0). ``parse_mosmix`` returns the issue
  time and, per forecast step, TTT (2 m temperature) and TX (12 h maximum), both converted K -> C.
- ECMWF ENS open data (CC BY 4.0) on the public AWS mirror ``ecmwf-forecasts``: ``ens_probe`` reads one
  step's ``.index`` (JSON lines, byte offsets) and range-requests a single 2 m temperature member, then
  reports its GRIB2 data-representation template.

CLI::

    python -m weather.sources.free_screens.forward_only mosmix [--root DIR]
    python -m weather.sources.free_screens.forward_only ens-probe [--root DIR] [--date YYYYMMDD]
"""
from __future__ import annotations

import argparse
import io
import json
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from weather.sources.free_screens import common

MOSMIX_URL = ("https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/single_stations/{sid}/kml/"
              "MOSMIX_L_LATEST_{sid}.kmz")
MOSMIX_DIR_URL = "https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/single_stations/{sid}/kml/"
# Ids from docs/research/data-layer-v2-s0-2026-10-15/s0ef-stations-and-licences.md (e)1.
MOSMIX_IDS = {"KATL": "72219", "KAUS": "72254", "KORD": "72530", "KDAL": "72259", "KBKF": "72469",
              "KHOU": "72243", "KLAX": "72295", "KMIA": "72202", "KLGA": "72503", "KSFO": "72494",
              "KSEA": "72793", "EGLC": "P0478", "LFPB": "07150", "EDDM": "10870", "LEMD": "08221"}
ENS_BUCKET = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
NS = {"kml": "http://www.opengis.net/kml/2.2",
      "dwd": "https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd"}


def parse_mosmix(kmz_bytes):
    with zipfile.ZipFile(io.BytesIO(kmz_bytes)) as z:
        kml = z.read(z.namelist()[0])
    root = ElementTree.fromstring(kml)
    issue = root.find(".//dwd:IssueTime", NS)
    steps = [e.text for e in root.findall(".//dwd:ForecastTimeSteps/dwd:TimeStep", NS)]
    out = {"issue_time": issue.text if issue is not None else None, "steps": steps, "elements": {}}
    for fc in root.findall(".//kml:Placemark/kml:ExtendedData/dwd:Forecast", NS):
        name = fc.get("{%s}elementName" % NS["dwd"])
        if name not in ("TTT", "TX", "TN"):
            continue
        vals = (fc.find("dwd:value", NS).text or "").split()
        out["elements"][name] = [None if v == "-" else round(float(v) - 273.15, 2) for v in vals]
    return out


def fetch_mosmix(root, session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / "dwd_mosmix"
    receipts = common.ReceiptLog(src)
    summary = {}
    for icao, sid in MOSMIX_IDS.items():
        resp = common.polite_get(session, MOSMIX_URL.format(sid=sid))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
        rel, sha = common.store_gzip(src, f"{icao}_{sid}_{stamp}.kmz.gz", resp.content)
        parsed = parse_mosmix(resp.content) if resp.status_code == 200 else {}
        tx = [v for v in parsed.get("elements", {}).get("TX", []) if v is not None]
        receipts.record({"key": f"{icao}|{stamp}", "file": rel, "sha256": sha, "status": resp.status_code,
                         "bytes": len(resp.content), "rows": len(parsed.get("steps", [])), "station": icao,
                         "issue_time": parsed.get("issue_time"), "tx_values": len(tx)})
        summary[icao] = {"issue_time": parsed.get("issue_time"), "steps": len(parsed.get("steps", [])),
                         "tx_values": len(tx), "bytes": len(resp.content)}
        log(f"{icao} {summary[icao]}")
    listing = common.polite_get(session, MOSMIX_DIR_URL.format(sid=MOSMIX_IDS["KATL"])).text
    summary["_retention_listing_KATL"] = [line.split('"')[1] for line in listing.splitlines() if 'href="' in line
                                          and ".kmz" in line]
    (src / "probe_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def grib2_templates(buf):
    """(grid template, data representation template, packing bits) of a GRIB2 message."""
    pos, out = 16, {}
    while pos < len(buf) - 4 and buf[pos:pos + 4] != b"7777":
        length, num = struct.unpack(">IB", buf[pos:pos + 5])
        if num == 3:
            out["grid_template"] = struct.unpack(">H", buf[pos + 12:pos + 14])[0]
        elif num == 5:
            out["data_template"] = struct.unpack(">H", buf[pos + 9:pos + 11])[0]
            out["n_values"] = struct.unpack(">I", buf[pos + 5:pos + 9])[0]
        pos += length
    return out


def ens_probe(root, day="20260929", session=None, log=print):
    import requests

    session = session or requests.Session()
    src = Path(root) / "ecmwf_ens"
    receipts = common.ReceiptLog(src)
    base = f"{ENS_BUCKET}/{day}/00z/ifs/0p25/enfo/{day}000000-24h-enfo-ef"
    index = common.polite_get(session, base + ".index")
    rel, sha = common.store_gzip(src, f"{day}_00z_24h.index.gz", index.content)
    fields = [json.loads(x) for x in index.text.splitlines() if x.strip()]
    t2 = [f for f in fields if f.get("param") == "2t" and f.get("number") == "1"]
    probe = {"day": day, "index_bytes": len(index.content), "index_fields": len(fields),
             "params": sorted({f.get("param") for f in fields}), "members_2t": sum(f.get("param") == "2t" for f in fields)}
    if t2:
        f = t2[0]
        rng = f"bytes={f['_offset']}-{f['_offset'] + f['_length'] - 1}"
        import time

        for wait in (5, 30, 120, 300):
            time.sleep(wait)
            msg = session.get(base + ".grib2", headers={"Range": rng, "User-Agent": common.USER_AGENT}, timeout=120)
            if msg.status_code == 206:
                break
        probe["range_status"] = msg.status_code
        rel2, sha2 = common.store_gzip(src, f"{day}_00z_24h_2t_m1.grib2.gz", msg.content)
        probe.update(member_bytes=len(msg.content), **grib2_templates(msg.content))
        probe["decodable_here"] = probe.get("data_template") in (0, 41)
        receipts.record({"key": f"{day}|2t|m1", "file": rel2, "sha256": sha2, "bytes": len(msg.content), "rows": 1})
    receipts.record({"key": f"{day}|index", "file": rel, "sha256": sha, "bytes": len(index.content),
                     "rows": len(fields)})
    (src / "probe_summary.json").write_text(json.dumps(probe, indent=1), encoding="utf-8")
    log(json.dumps(probe))
    return probe


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m weather.sources.free_screens.forward_only")
    parser.add_argument("command", choices=("mosmix", "ens-probe"))
    parser.add_argument("--root", default=str(common.DEFAULT_ROOT))
    parser.add_argument("--date", default="20260929")
    args = parser.parse_args(argv)
    if args.command == "mosmix":
        fetch_mosmix(args.root, log=lambda m: print(m, flush=True))
    else:
        ens_probe(args.root, args.date, log=lambda m: print(m, flush=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
