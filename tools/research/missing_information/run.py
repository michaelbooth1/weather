"""Guarded offline driver for the fixed descriptive missing-information mission.

Stages: prepare verifies all archives before safe extraction; extract creates the
one-snapshot table; analyze scores only that table. Inputs/outputs are explicit
scratch paths. No provider calls, credentials, orders, fitting of models, or
production mutation. Error kernels are the plan's past-date-only diagnostics.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

from weather.paths import REPO_ROOT, repo_path
from tools.research.missing_information.extract import extract, sha256

ARCHIVES = ("mi-core.tgz", "mi-tape.tgz", "mi-books-sample.tgz")
SETTINGS = repo_path("tools/research/missing_information/analysis_settings.json")
PLAN = repo_path("docs/research/missing-information-test-plan-2026-09-21.md")


def scratch_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("absolute scratch paths required")
    path = path.resolve()
    if any(p.lower() == "data" or "mirror" in p.lower() for p in path.parts):
        raise ValueError("data and mirror paths are outside this mission")
    if "scratch" not in [p.lower() for p in path.parts]:
        raise ValueError("path must be beneath an explicit scratch directory")
    return path


def write_json(path, data):
    # NaN is forbidden evidence: normalize missing floating results to JSON null.
    def clean(value):
        import math
        import numpy as np
        if isinstance(value, dict):
            return {str(k): clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        if isinstance(value, np.ndarray):
            return clean(value.tolist())
        if isinstance(value, (float, np.floating)):
            return float(value) if math.isfinite(value) else None
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.bool_):
            return bool(value)
        return value
    encoded = json.dumps(clean(data), indent=2, allow_nan=False)+"\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def manifest_entries(manifest):
    """Accept explicit file/digest records; never infer hashes or trust a filename."""
    entries = manifest.get("files", manifest.get("archives", manifest))
    result = {}
    if isinstance(entries, dict):
        for name, value in entries.items():
            if name in ARCHIVES:
                result[name] = value if isinstance(value, str) else value.get("sha256")
    elif isinstance(entries, list):
        for row in entries:
            name = row.get("name", row.get("file", row.get("filename")))
            if name in ARCHIVES:
                if name in result:
                    raise ValueError("duplicate archive in manifest")
                result[name] = row.get("sha256")
    if set(result) != set(ARCHIVES):
        raise ValueError("manifest does not bind the three exact archive names")
    import re
    if any(not isinstance(h, str) or not re.fullmatch("[0-9a-fA-F]{64}", h) for h in result.values()):
        raise ValueError("manifest contains a malformed SHA-256")
    return {k: v.lower() for k, v in result.items()}


def safe_unpack(archive, destination):
    """No links, traversal, alternate streams, overwrites, or unbounded expansion."""
    count, size = 0, 0
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            name = member.name.removeprefix("./")
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                    or member.issym() or member.islnk() or not (member.isfile() or member.isdir())):
                raise ValueError(f"unsafe archive member: {member.name}")
            target = destination.joinpath(*path.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("archive member escapes destination")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            count += 1
            size += member.size
            if count > 100_000 or size > 30_000_000_000 or member.size > 2_000_000_000:
                raise ValueError("archive exceeds bounded research budget")
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open("xb") as out:
                shutil.copyfileobj(source, out, length=1024*1024)
    return {"files": count, "bytes": size}


def prepare(downloads, output):
    if output.exists():
        raise ValueError("unpack destination must be a new directory")
    manifest_path = downloads / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    entries = manifest_entries(manifest)
    for name, expected in entries.items():
        actual = sha256(downloads / name)
        if actual != expected:
            raise ValueError(f"archive SHA-256 mismatch: {name}")
        print(f"verified {name} {actual}", flush=True)
    output.mkdir(parents=True)
    counts = {}
    for name in ARCHIVES:
        counts[name] = safe_unpack(downloads / name, output)
        print(f"unpacked {name}: {counts[name]}", flush=True)
    write_json(output / "verification.json", {"archives": entries, "manifest_sha256": sha256(manifest_path),
                                             "counts": counts, "manifest": manifest})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["preflight", "prepare", "extract", "analyze", "supplement", "clock", "fetch-guidance", "fetch-guidance-csv"])
    parser.add_argument("--input", type=scratch_path)
    parser.add_argument("--output", type=scratch_path)
    parser.add_argument("--iem", type=scratch_path)
    parser.add_argument("--raw", type=scratch_path)
    parser.add_argument("--baseline", type=scratch_path)
    args = parser.parse_args(argv)
    if os.environ.get("WEATHER_WORKSTATION_WRAPPER_ACTIVE") != "1":
        parser.error("launch through scripts/ops/workstation_heavy.ps1")
    settings = json.loads(SETTINGS.read_text())
    if sha256(PLAN) != settings["plan_sha256"]:
        parser.error("frozen plan bytes changed")
    import weather
    import tools.research.missing_information.methods as methods
    print(f"source={methods.__file__}; weather={weather.__file__}; repo={REPO_ROOT}", flush=True)
    header = {"plan_sha256": sha256(PLAN), "settings_sha256": sha256(SETTINGS),
              "started_at_utc": datetime.now(timezone.utc).isoformat(), "settings": settings,
              "python": sys.version, "stage": args.stage, "module": str(Path(__file__).resolve())}
    header["source_sha256"] = {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    if args.stage == "preflight":
        print(json.dumps(header, indent=2))
        return 0
    if args.input is None or args.output is None:
        parser.error("--input and --output are mandatory")
    if args.stage == "prepare":
        prepare(args.input, args.output)
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    # Header is durable before the first data read or score in this stage.
    write_json(args.output / "run_header.json", header)
    if args.stage == "fetch-guidance":
        from tools.research.missing_information.guidance_archive import fetch
        fetch(args.output)
        return 0
    if args.stage == "fetch-guidance-csv":
        from tools.research.missing_information.guidance_archive import fetch_structured
        fetch_structured(args.output)
        return 0
    if args.stage == "extract":
        verification = json.loads((args.input / "verification.json").read_text())
        info = extract(args.input, args.output)
        write_json(args.output / "extraction_receipt.json", {**info, "verification": verification, **header})
        print(json.dumps(info), flush=True)
        return 0
    receipt = json.loads((args.input / "extraction_receipt.json").read_text())
    table = args.input / "snapshots.jsonl"
    if sha256(table) != receipt["output_sha256"]:
        raise ValueError("extracted snapshot table changed")
    if args.raw is not None:
        verified_raw = json.loads((args.raw / "verification.json").read_text())
        if verified_raw != receipt["verification"]:
            raise ValueError("raw export does not match extraction receipt")
    from tools.research.missing_information.checks import load_frame, check1, check2, check4
    from tools.research.missing_information.regimes import check5, load_observations
    frame = load_frame(table)
    if frame.empty:
        raise ValueError("no admissible snapshots; no inference performed")
    print(f"loaded {len(frame)} snapshots", flush=True)
    if args.stage == "supplement":
        from tools.research.missing_information.supplement import supplement
        if args.raw is None:
            parser.error("--raw required")
        write_json(args.output / "supplement.json", supplement(frame, args.raw, args.input, args.output, args.baseline))
        return 0
    if args.stage == "clock":
        from tools.research.missing_information.clocks import check3
        if args.raw is None or args.iem is None:
            parser.error("--raw and --iem required")
        for row in json.loads((args.iem / "manifest.json").read_text()):
            if Path(row["file"]).name != row["file"] or sha256(args.iem / row["file"]) != row["sha256"]:
                raise ValueError("IEM evidence hash mismatch")
        write_json(args.output / "check3.json", check3(frame, args.raw, load_observations(args.iem), args.output))
        return 0
    one = check1(frame)
    write_json(args.output / "check1.json", one)
    print("check 1 complete", flush=True)
    write_json(args.output / "check2.json", check2(frame))
    print("check 2 complete", flush=True)
    write_json(args.output / "check4.json", check4(frame, args.output))
    print("check 4a complete", flush=True)
    if args.iem is None:
        parser.error("--iem required for check 5")
    manifest = json.loads((args.iem / "manifest.json").read_text())
    for row in manifest:
        if Path(row["file"]).name != row["file"] or sha256(args.iem / row["file"]) != row["sha256"]:
            raise ValueError("IEM evidence hash mismatch")
    observations = load_observations(args.iem)
    write_json(args.output / "check5.json", check5(frame, observations, args.output))
    print("check 5 complete", flush=True)
    write_json(args.output / "completion.json", {"snapshot_sha256": receipt["output_sha256"],
                                                 "iem_manifest_sha256": sha256(args.iem / "manifest.json"),
                                                 "clock_skip_by_stratum": {s: r["frozen_reading"]["clock_skip_rule"] for s, r in one.items()},
                                                 "completed_at_utc": datetime.now(timezone.utc).isoformat()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
