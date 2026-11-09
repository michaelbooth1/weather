"""Generate development-date METAR fixtures from format metadata, never real values."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import random
import re

ROOT = Path(__file__).resolve().parent
SEED = 20260920
START = datetime(2026, 9, 20, tzinfo=timezone.utc)
END = datetime(2026, 9, 23, tzinfo=timezone.utc)


def encoded(value):
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def body_number(value):
    return ("M" if value < 0 else "") + f"{abs(value):02d}"


def t_number(tenths):
    return f"{int(tenths < 0)}{abs(tenths):03d}"


def build(inventory_path=None):
    inventory_path = Path(inventory_path) if inventory_path else ROOT / "metar_quirks.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    metadata_path = ROOT / "inputs/stations.json"
    metadata = {row["id"]: row for row in json.loads(metadata_path.read_text(encoding="utf-8"))}
    rng = random.Random(SEED)
    lines, cases, flags = {}, [], {}
    for station in inventory["stations"]:
        icao, cadence = station["icao"], station["cadence_minutes"]
        latitude = abs(metadata[icao]["lat"])
        base = rng.randint(20, 30) if latitude < 25 else rng.randint(10, 24) if latitude < 45 else rng.randint(0, 16)
        observations = []
        for index in range(int((END - START).total_seconds() // (cadence * 60)) + 1):
            instant = START + timedelta(minutes=index * cadence)
            temp = rng.randint(-2, 2) if icao == "UUWW" else base + rng.randint(-3, 3)
            if icao == "UUWW" and instant == datetime(2026, 9, 21, 6, tzinfo=timezone.utc):
                temp = 5
            if icao == "UUWW" and instant == datetime(2026, 9, 21, 12, tzinfo=timezone.utc):
                temp = -3
            dew = temp - rng.randint(1, 6)
            prefix = "METAR COR " if index % 19 == 0 else "" if index % 17 == 0 else "METAR "
            auto = "AUTO " if index % 7 == 0 else ""
            wind = "31005MPS" if "wind_mps" in station["render_formats"] else "23006KT"
            cloud = "BKN020///" if "automated_cloud" in station["render_formats"] else "FEW030"
            extra = " 05R/2400FT" if "runway_feet_without_r" in station["render_formats"] else " R24/190050"
            raw = f"{prefix}{icao} {instant:%d%H%MZ} {auto}{wind} 9999 {cloud} {body_number(temp)}/{body_number(dew)} Q1018{extra}"
            if station["t_groups"]:
                raw += " RMK AO2 T" + t_number(temp * 10 + rng.randint(-4, 4)) + t_number(dew * 10)
            observations.append(raw)
        warm = max(10, base + 5)
        observations.append(f"SPECI {icao} 211215Z 04004KT 1/2SM BKN006 {body_number(warm)}/{body_number(warm - 6)} Q1008")
        lines[icao], flags[icao] = observations, Counter()

    def case(name, station, raw, expected_flags=()):
        lines[station].append(raw)
        flags[station].update(expected_flags)
        cases.append(dict(name=name, station=station, raw=raw, expected_flags=list(expected_flags)))

    case("good_cor", "KLGA", "METAR COR KLGA 211301Z 21/04 RMK T02060040")
    case("malformed_cor_before_station", "KLGA", "METAR C0R KLGA 211302Z 21/04", ["malformed_correction_marker"])
    case("malformed_cor_after_station", "KLGA", "METAR KLGA COR0 211303Z 21/04", ["malformed_correction_marker"])
    case("malformed_cor_after_time", "KLGA", "METAR KLGA 211304Z C0R 21/04", ["malformed_correction_marker"])
    case("malformed_type", "KLGA", "MTAR KLGA 211305Z 21/04", ["malformed_report_type"])
    case("unlabelled_off_hour", "CYYZ", "CYYZ 211337Z 16/04")
    case("auto", "CYYZ", "METAR CYYZ 211306Z AUTO 15/04")
    case("shortened_t", "KDEN", "METAR KDEN 211307Z 06/M03 RMK T0056", ["malformed_t_group"])
    case("nine_digit_t", "KDEN", "METAR KDEN 211308Z 06/M03 RMK T005600391", ["malformed_t_group"])
    case("invalid_t_sign_2", "KDEN", "METAR KDEN 211309Z 06/M03 RMK T20560039", ["malformed_t_group"])
    case("unused_dew_sign_2", "KDEN", "METAR KDEN 211310Z 06/M03 RMK T00562039")
    case("negative_t", "KDEN", "METAR KDEN 211311Z M03/M05 RMK T10251050")
    for minute, token in enumerate(("210/04", "21/100", "21//04", "21//", "21/040000"), 12):
        case("corrupted_body_" + str(minute), "KLGA", f"METAR KLGA 2113{minute:02d}Z {token}", ["malformed_body_temperature"])
    case("malformed_body_valid_t", "KLGA", "METAR KLGA 211317Z 2X/10 RMK T01830100", ["malformed_body_temperature"])
    case("missing_dewpoint_12_slashes", "KLGA", "METAR KLGA 211318Z 12/// RMK AO2")
    case("missing_temperature", "CYYZ", "METAR CYYZ 211319Z NIL")
    case("missing_fields", "MPMG", "METAR MPMG 211320Z AUTO 13003KT //// R01///// // FEW019/// OVC200/// 27/24 Q1009")
    case("stationless", "KLGA", "METAR 211500Z 18/04", ["malformed_station"])
    case("unreadable_time", "CYYZ", "CYYZ 2X1800Z 25/04", ["malformed_or_ambiguous_time"])
    case("taf_validity", "UUWW", "METAR UUWW 210209Z 2103/2203 31005MPS 6000 FEW007 BKN016 TX05/2112Z TNM03/2104Z BECMG 2112/2115 25005MPS")
    case("sea_state_s", "LTFM", "METAR LTFM 211321Z 15/10 W15/S4")
    case("sea_state_h", "LTFM", "METAR LTFM 211322Z 15/10 W15/H7")
    case("runway_r", "MMMX", "METAR MMMX 211323Z 15/10 R88/290050")
    case("visibility_fraction", "KMIA", "METAR KMIA 211324Z 04010KT 1 1/2SM BR 15/10")
    case("ambiguous_t", "KLGA", "METAR KLGA 211325Z 20/04 RMK T02060040 T02160040", ["ambiguous_t_group"])
    case("ambiguous_body", "KLGA", "METAR KLGA 211326Z 20/04 21/05", ["ambiguous_body_temperature"])
    case("ambiguous_body_valid_t", "KLGA", "METAR KLGA 211327Z 20/04 21/05 RMK T02060040", ["ambiguous_body_temperature"])

    files, summary = {}, []
    for station in inventory["stations"]:
        icao = station["icao"]
        reports = lines[icao]
        files[f"per-station/{icao}.txt"] = "\n".join(reports) + "\n"
        valid_t = lambda raw: len([token for token in raw.split() if re.fullmatch(r"T[01]\d{7}", token)]) == 1
        summary.append(dict(icao=icao, reports=len(reports), speci=sum(r.startswith("SPECI ") for r in reports),
                            tgroup_routine=sum(not r.startswith("SPECI ") and valid_t(r) for r in reports),
                            per_hour=60 // station["cadence_minutes"]))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=("icao", "reports", "speci", "tgroup_routine", "per_hour"), lineterminator="\n")
    writer.writeheader()
    writer.writerows(summary)
    files["summary.csv"] = output.getvalue()
    files["cases.json"] = encoded(dict(kind="synthetic", cases=cases))
    manifest = dict(schema_version="synthetic-metar-v1", kind="synthetic", seed=SEED,
                    start_utc=START.isoformat(), end_utc=END.isoformat(),
                    generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    quirk_inventory_sha256=hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
                    station_metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                    files={name: hashlib.sha256(text.encode()).hexdigest() for name, text in sorted(files.items())},
                    expected_parse_flags={station: dict(counter) for station, counter in flags.items()},
                    synthetic_shortened_t_divergence_dates=[["KDEN", "2026-09-21"]])
    files["provenance.json"] = encoded(manifest)
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "inputs/metar-72h")
    args = parser.parse_args()
    for name, text in build().items():
        path = args.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
