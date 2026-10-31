"""Served-vs-market per-block re-base on the released targets 2026-10-01..2026-10-14 (EXHAUSTION_REGISTER §5 order 1).

Research tool (lane L8, 2026-10-31), not a production dependency. It is a wrapper, because the loss atlas pins
its range to 08-01..09-29 and its positive control to those dates, and the B-bound dev scorecard files
(``dev_scorecard``, ``dev_scorecard_data``, ``loss_atlas``) may not be edited before 12-13; it imports them
read-only. Readiness note: ``docs/research/iterate-faster-2026-10-30/atlas-readiness-0930-1014.md`` (branch
``claude/embargo-release-export-manifest-20261031``).

Order of operations; each step refuses on failure and nothing after it runs:

1. Guards: every path is free of ``88a``/``panel``; ``--out`` is new or empty and outside ``C:\\swarm``; the
   candidate is ``served`` or ``market`` (MG-2, MG-1, B or any other candidate is refused by name); the ruling
   reference is given; the dev scorecard's ``DEV_LAST`` is still 2026-09-29.
2. Row 80 first: the row 80 look receipt must exist, be ledger row 80 with a verdict, and name the same
   release layout manifest sha256 that this run reads.
3. EF section 3 floor control (``dev_scorecard.run_floor_control``, fixture sha pinned there): verdict PASS.
4. Atlas positive control (``loss_atlas.positive_control``) on the unchanged development layout, with the
   atlas's own range and folds: served/market R reproduces 1.774 all / 1.526 00-16.
5. Release scope, by LOCAL TARGET DATE (master's ruling, 2026-10-31): a target of 10-15 or later is refused
   whatever its capture time (C5); a target of 10-14 or earlier is released, including a 10-14 label recorded
   on UTC 10-15. Every file of the release layout manifest must declare only targets inside 10-01..10-14;
   then, in process only, ``dev_scorecard_data.DEV_LAST`` is set to 2026-10-14 for the read (restored
   afterwards; no file is edited) and the release layout is loaded. The reader drops Austin 10-03 (C7) and
   records how many snapshots it dropped.
6. Per stratum (``pre`` 10-01..10-09, ``post`` 10-10..10-14; which strata are read is the ruling's
   ``--strata``; master ruled option (a) on 2026-10-31, so ``pre+post``, with 10-10..10-14 excluded from
   order 6), ``dev_scorecard.score_rows`` for the candidate per block and market, crossed date x market
   intervals for all markets and date-clustered for one market; ``powered`` against ``CLUSTER_FLOOR``.
   Strata are never pooled.
7. Content-addressed payload (``<sha>.json``/``<sha>.md``) and ``receipt.json`` under ``--out``. The evidence
   class is "descriptive, not countable".

Run from the repository root (needs ``weather`` importable)::

    python -m tools.research.released_window.served_market_blocks --row80-receipt <out_rep/look/receipt.json> \
        --floor-fixture tests/fixtures/reporting/dev_scorecard/hard_floor_snapshot_deltas.csv.gz \
        --dev-layout <dev v3 layout> --release-layout <r80_layout out>/layout \
        --ruling "<DECISION_LOG ref>" --strata pre|pre+post --out <new empty dir>
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

from weather.reporting.scorecards import dev_scorecard as sc
from weather.reporting.scorecards import dev_scorecard_data as data
from weather.reporting.scorecards import loss_atlas as la

SCHEMA = "released_served_market_blocks/1"
DEV_LAST_EXPECTED = date(2026, 9, 29)
RELEASE_FIRST, RELEASE_LAST = date(2026, 10, 1), date(2026, 10, 14)
EMBARGO_FIRST_TARGET = date(2026, 10, 15)
EXCLUDED_MARKET_DAYS = frozenset({("austin", "2026-10-03")})
STRATA = {"pre": ("2026-10-01", "2026-10-09"), "post": ("2026-10-10", "2026-10-14")}
STRATA_CHOICES = {"pre": ("pre",), "pre+post": ("pre", "post")}
CANDIDATES = ("served", "market")
REFUSED_CANDIDATE = re.compile(r"mg-?2|mg-?1|\bb\b|b_|composite", re.IGNORECASE)
FORBIDDEN_PATH = re.compile(r"88a|panel", re.IGNORECASE)
SWARM_ROOT = Path(r"C:\swarm")
MIN_RULING = 8
EVIDENCE_CLASS = "descriptive, not countable"


class Refused(data.Refused):
    """A guard refused; nothing after it ran."""


# ----------------------------------------------------------------------------- guards

def screen_path(path, label):
    if path is None:
        raise Refused(f"refused: {label} is required")
    if FORBIDDEN_PATH.search(str(path)):
        raise Refused(f"refused: {label} path {path} names 88a or panel data")
    return Path(path)


def _under(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def check_out_dir(out, swarm_root=SWARM_ROOT):
    out = screen_path(out, "--out")
    if _under(out, swarm_root):
        raise Refused(f"refused: --out {out} is under {swarm_root}")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refused(f"refused: --out {out} must be a new or empty directory")
    return out


def check_candidate(name):
    if REFUSED_CANDIDATE.search(str(name)) or name not in CANDIDATES:
        raise Refused(f"refused: candidate {name!r}; only {CANDIDATES} are read here (MG-2 stays excluded)")
    return name


def check_ruling(ruling, strata):
    if not ruling or len(str(ruling).strip()) < MIN_RULING:
        raise Refused("refused: --ruling needs master's DECISION_LOG reference for this read")
    if strata not in STRATA_CHOICES:
        raise Refused(f"refused: --strata must be one of {sorted(STRATA_CHOICES)}")
    return STRATA_CHOICES[strata]


def _sha_bytes(body):
    return hashlib.sha256(body).hexdigest()


def manifest_sha(layout_root):
    return _sha_bytes((Path(layout_root) / data.MANIFEST).read_bytes())


def check_row80_receipt(path, release_layout):
    """Row 80's look is the first read of these cells: its receipt must exist and name this layout."""
    path = screen_path(path, "--row80-receipt")
    if not path.is_file():
        raise Refused(f"refused: row 80 receipt {path} does not exist; the row 80 look runs first")
    body = path.read_bytes()
    receipt = json.loads(body.decode("utf-8"))
    if receipt.get("ledger_row") != 80:
        raise Refused(f"refused: {path} is not a ledger row 80 receipt")
    verdict = (receipt.get("result") or {}).get("verdict")
    if verdict not in ("REPLICATED", "NOT REPLICATED", "UNTESTABLE"):
        raise Refused(f"refused: row 80 receipt carries no verdict ({verdict!r})")
    release_sha = manifest_sha(release_layout)
    if receipt.get("layout_manifest_sha256") != release_sha:
        raise Refused(f"refused: row 80 looked at layout {receipt.get('layout_manifest_sha256')}, "
                      f"not this release layout {release_sha}")
    return {"path": str(path), "sha256": _sha_bytes(body), "verdict": verdict,
            "layout_manifest_sha256": release_sha}


def check_release_manifest(layout_root):
    """Before the override: every file of the release layout declares only dates inside the window."""
    manifest = json.loads((Path(layout_root) / data.MANIFEST).read_text(encoding="utf-8"))
    for name in data.LAYOUT_FILES:
        dates = (manifest.get("files", {}).get(name) or {}).get("dates") or []
        if not dates:
            raise Refused(f"refused: release layout {name} declares no dates")
        embargoed = [d for d in dates if data.parse_date(d) >= EMBARGO_FIRST_TARGET]
        if embargoed:
            raise Refused(f"refused: release layout {name} declares embargoed target {embargoed[0]} "
                          "(local target 10-15 or later, whatever its capture time)")
        outside = [d for d in dates if not RELEASE_FIRST <= data.parse_date(d) <= RELEASE_LAST]
        if outside:
            raise Refused(f"refused: release layout {name} declares dates outside 10-01..10-14 "
                          f"(first {outside[0]})")
    return manifest


# ----------------------------------------------------------------------------- controls

def floor_control(fixture):
    payload = sc.run_floor_control(screen_path(fixture, "--floor-fixture"))
    if payload["verdict"] != "PASS":
        raise Refused("refused: EF section 3 floor control did not reproduce; nothing else runs")
    return payload


def atlas_positive_control(dev_layout, expected=None):
    """``loss_atlas.positive_control`` with the atlas's own range and folds (as ``run_atlas`` does)."""
    la.screen_input_path(dev_layout, "dev layout")
    start, end = data.check_range(*la.RANGE)
    layout = data.load_layout(dev_layout, data.DEV_FIRST, end)
    folds = data.make_folds(layout.dates, start, end, *la.FOLDS)
    scored = sorted(d for f in folds if f.scored for d in f.dates)
    if not scored:
        raise Refused("refused: the atlas fold scheme scores no development date")
    control = la.positive_control(sc.Table(layout, scored), expected)   # raises ControlFailed
    control["dev_layout_manifest_sha256"] = layout.manifest_sha256
    return control


@contextlib.contextmanager
def released_dev_last(last=RELEASE_LAST):
    """``dev_scorecard_data.DEV_LAST`` = ``last`` in-process only (as rep.py does); restored on exit."""
    saved = data.DEV_LAST
    data.DEV_LAST = last
    try:
        yield {"dev_scorecard_data.DEV_LAST": [saved.isoformat(), last.isoformat()]}
    finally:
        data.DEV_LAST = saved


def drop_excluded(layout):
    """Drop the excluded market-days (Austin 10-03) from every frame; returns the snapshot count dropped."""
    def keep(frame):
        pairs = list(zip(frame.market.astype(str), frame.date.astype(str)))
        return frame.loc[[p not in EXCLUDED_MARKET_DAYS for p in pairs]].reset_index(drop=True)

    before = len(layout.snaps)
    layout.snaps = keep(layout.snaps)
    kept = set(layout.snaps.row_key)
    layout.bands = layout.bands[layout.bands.row_key.isin(kept)].reset_index(drop=True)
    layout.labels = layout.labels[layout.labels.row_key.isin(kept)].reset_index(drop=True)
    layout.market = layout.market[layout.market.row_key.isin(kept)].reset_index(drop=True)
    layout.dates = sorted(layout.snaps.date.astype(str).unique())
    return before - len(layout.snaps)


# ----------------------------------------------------------------------------- scoring

def stratum_rows(layout, candidate, first, last):
    dates = [d for d in layout.dates if first <= d <= last]
    if not dates:
        return {"dates": [], "rows": [], "note": "no layout dates in this stratum"}
    table = sc.Table(layout, dates)
    p = table.p_served if candidate == "served" else table.p_market
    return {"dates": dates, "rows": sc.score_rows(table, p, candidate == "served")}


def run(row80_receipt, floor_fixture, dev_layout, release_layout, ruling, strata, out, candidate="served",
        control_expected=None, swarm_root=SWARM_ROOT):
    """Steps 1-7 of the module docstring; returns the receipt."""
    for path, label in ((dev_layout, "--dev-layout"), (release_layout, "--release-layout")):
        screen_path(path, label)
    out = check_out_dir(out, swarm_root)
    check_candidate(candidate)
    chosen = check_ruling(ruling, strata)
    if Path(dev_layout).resolve() == Path(release_layout).resolve():
        raise Refused("refused: the development and release layouts are the same directory")
    if data.DEV_LAST != DEV_LAST_EXPECTED:
        raise Refused(f"refused: dev scorecard DEV_LAST is {data.DEV_LAST}, not {DEV_LAST_EXPECTED}, "
                      "before the controls")
    row80 = check_row80_receipt(row80_receipt, release_layout)
    floor = floor_control(floor_fixture)
    control = atlas_positive_control(dev_layout, control_expected)
    check_release_manifest(release_layout)
    with released_dev_last() as override:
        layout = data.load_layout(release_layout, RELEASE_FIRST, RELEASE_LAST)
    if layout.manifest_sha256 != row80["layout_manifest_sha256"]:
        raise Refused("refused: the release layout changed after the row 80 receipt check")
    dropped = drop_excluded(layout)
    sections = {name: stratum_rows(layout, candidate, *STRATA[name]) for name in chosen}
    payload = {
        "schema": SCHEMA, "evidence_class": EVIDENCE_CLASS, "register": "EXHAUSTION_REGISTER section 5 order 1",
        "candidate": candidate, "ruling": ruling, "strata": {k: list(STRATA[k]) for k in chosen},
        "pooled": False, "cluster_floor": sc.CLUSTER_FLOOR,
        "release_layout_manifest_sha256": layout.manifest_sha256, "label_source": layout.label_source,
        "sections": sections,
    }
    sha, json_path, md_path = sc.write_outputs(payload, out, payload_markdown)
    receipt = {
        "schema": SCHEMA + "/receipt", "evidence_class": EVIDENCE_CLASS, "ruling": ruling, "candidate": candidate,
        "strata": list(chosen), "module_sha256": _sha_bytes(Path(__file__).read_bytes()),
        "dev_scorecard_code_sha256": sc.code_sha256(), "loss_atlas_code_sha256": la.code_sha256(),
        "row80_receipt": row80,
        "floor_control": {"verdict": floor["verdict"], "fixture_sha256": floor["fixture"]["sha256"],
                          "tracker_method": floor["tracker_method"]},
        "positive_control": control, "override_in_process": override,
        "release_layout_manifest_sha256": layout.manifest_sha256,
        "dates": {k: v["dates"] for k, v in sections.items()},
        "excluded_market_days": sorted(list(k) for k in EXCLUDED_MARKET_DAYS), "snapshots_dropped": dropped,
        "boundary": "local target date: 10-14 or earlier released, 10-15 or later embargoed (C5)",
        "payload": {"sha256": sha, "json": json_path.name, "md": md_path.name},
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="utf-8")
    return receipt


def _interval(entry):
    est, ci = entry.get("estimate"), entry.get("ci95") or [None, None]
    fmt = lambda x: "n/a" if x is None else f"{x:.4f}"   # noqa: E731
    return f"{fmt(est)} [{fmt(ci[0])}, {fmt(ci[1])}]"


def payload_markdown(payload, sha):
    lines = [f"# Served vs market per block, released targets `{sha[:12]}`", "",
             f"Evidence class: **{payload['evidence_class']}**. Candidate `{payload['candidate']}`; ruling "
             f"{payload['ruling']}; strata never pooled; powered needs {payload['cluster_floor']} clusters.", ""]
    for name, section in payload["sections"].items():
        lines += [f"## Stratum {name}: {', '.join(section['dates']) or 'no dates'}", "",
                  "| market | block | dates | served/market R | powered |", "| --- | --- | --- | --- | --- |"]
        for r in section["rows"]:
            lines.append(f"| {r['market']} | {r['block']} | {r['n_dates']} | {_interval(r['served_ratio'])} "
                         f"| {r['powered']} |")
        lines.append("")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(description="Served-vs-market per block on released targets 10-01..10-14.")
    parser.add_argument("--row80-receipt", required=True)
    parser.add_argument("--floor-fixture", required=True)
    parser.add_argument("--dev-layout", required=True)
    parser.add_argument("--release-layout", required=True)
    parser.add_argument("--ruling", required=True, help="master's DECISION_LOG reference for this read")
    parser.add_argument("--strata", required=True, choices=sorted(STRATA_CHOICES))
    parser.add_argument("--candidate", default="served", help="served or market only")
    parser.add_argument("--out", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        receipt = run(args.row80_receipt, args.floor_fixture, args.dev_layout, args.release_layout, args.ruling,
                      args.strata, args.out, args.candidate)
    except data.Refused as exc:            # Refused, ControlFailed and the dev scorecard's own refusals
        print(str(exc), file=sys.stderr)
        return getattr(exc, "exit_code", 2)
    except (data.LayoutError, data.LeakageError) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(json.dumps({"payload_sha256": receipt["payload"]["sha256"], "receipt": str(Path(args.out) / "receipt.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
