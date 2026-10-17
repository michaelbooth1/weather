"""``python -m maker_core.frontier.cli`` -- the informed-v1 frontier decision pipeline (item 330 build 4).

Two commands. Both are offline and read-only on their inputs, write one new output directory (create-only:
``report.json`` and ``receipt.json``), and grant no authority.

``calibrate``
    A DESCRIPTIVE run of the whole pipeline (runner per event-day cluster, then ``decision.evaluate``) on the
    v0.2 calibration bundles (``panel.CALIBRATION_DATES``, 2026-09-27..29). Every bundle day passes
    ``embargo.check("fit", ...)`` before its bundle is opened. Its verdict is a rehearsal of the rule, never a
    decision. A band whose descriptor close falls in a refused window (for example a 09-29 band closing on
    09-30) is dropped from the clusters and counted in the report (``embargoed_bands``), not read.

``score``
    The preregistered read. It refuses, in this order:

    1. before ``embargo.SCORED_OPENS_AT`` (2026-11-14T00:00Z) by the real UTC clock (``clock`` is injectable
       for tests only; the command line always uses ``datetime.now(timezone.utc)``);
    2. unless ``prereg.verify`` accepts the registration for the decay digest (refitted from the same RE-1
       bytes), the fill-v3 binding (``adapters.FILL_V3_BINDING``), the grid hash and ``SCORED_RULE``'s
       decision-rule digest; today no registration is pinned, so it always refuses here;
    3. any bundle whose day is outside the scored panel 2026-10-16..2026-11-13 (``embargo.SCORED_PANEL``),
       checked before the bundle is opened;
    4. always, today: no ``maker_core.replay.v2.panel.PANELS`` name covers the scored panel (``registered``
       is the reserved 09-30..10-15 window, ``calibration`` is 09-27..29), so there is no sanctioned way to
       declare its windows (``score_has_no_intervals_panel``). Adding a panel is a separate reviewed change.

    It uses the real fill v3 kernel, the run's hazard default and no free tuning parameter.

Sources: only v0.2 (stream) bundles, opened with ``open_stream_bundle`` and turned into day sources by
``maker_core.replay.v2.intervals.sources`` with the required ``--inventory`` (the weather producer's universe rows,
the rehearsal inventory document): the §4 rule and the owner exclusions declare every window, so a captured
bundle scores only through declared intervals (U1 Defender MF4). A v0.1 bundle is refused
(``v01_bundle_unsupported``).

Clusters: each bundle's descriptors are read first and each band is assigned its event day
(``decision.event_day`` of its close). The runner then runs once per event day on the bundles restricted to
that event day's bands. Grid points do not couple bands, so their cluster totals sum to an unrestricted run's;
the baselines' ``active_other_bands`` count is then per event day rather than per capture day (disclosed).

The receipt carries the SHA-256 of every input (bundle manifests, RE-1 files, toxicity table, registration,
cf-tape receipts), the code commit given on the command line plus the SHA-256 of every module the pipeline
runs, and the grid, decay, fill-binding, decision-rule and report digests.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from types import MappingProxyType

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.frontier import adapters, decision, embargo, grid, prereg, runner, seams, share_decay
from maker_core.quoting import fill_cost
from maker_core.replay import fill_v3
from maker_core.replay.bundle import FORMAT as FORMAT_V01, BundleError
from maker_core.replay.bundle_v02 import GroupRecord, open_stream_bundle, read_format
from maker_core.replay.pack_io import read_json
from maker_core.replay.payloads import Descriptor
from maker_core.replay.v2 import intervals
from maker_core.replay.v2.lockstep import DaySource, items

REPORT_FORMAT = "maker-core.frontier-decision-report.1"
RECEIPT_FORMAT = "maker-core.frontier-decision-receipt.1"
SCORED_RULE = decision.PROPOSED_RULE
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
# The rehearsal inventory document (``tools/research/maker_replay_v2/rehearse_cli.py``, which core cannot import).
INVENTORY_FORMAT = "maker_core.replay.v2.rehearsal_inventory.v0.1"
INVENTORY_BYTES = 4 * 1024**2
CALIBRATION_PANEL = "calibration"
# No ``panel.PANELS`` name covers 2026-10-16..2026-11-13; ``score`` refuses until a reviewed change adds one.
SCORED_INTERVALS_PANEL = None
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
CODE_MODULES = (adapters, decision, embargo, grid, prereg, runner, seams, share_decay, fill_v3, fill_cost,
                sys.modules[__name__])


class CliRefused(ValueError):
    """The command's inputs are outside its contract."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle_day(directory: Path) -> tuple[date, str]:
    """(UTC day, manifest sha256) from ``bundle.json`` under a size cap, before any stream is opened."""
    path = Path(directory) / "bundle.json"
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise CliRefused("bundle_manifest_missing_or_too_large")
    raw = path.read_bytes()
    value = json.loads(raw)
    day = value.get("day") if isinstance(value, dict) else None
    try:
        parsed = date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise CliRefused("bundle_day") from exc
    if parsed.isoformat() != day:
        raise CliRefused("bundle_day")
    return parsed, _sha256(raw)


def open_bundle(directory: Path):
    """A v0.2 stream bundle; v0.1 is refused before its records are read."""
    if read_format(Path(directory)) == FORMAT_V01:
        raise CliRefused("v01_bundle_unsupported")
    return open_stream_bundle(Path(directory))


def read_inventory(path, days) -> tuple[list, str]:
    """The rehearsal inventory document's rows (and its SHA-256); its dates must equal the bundle days."""
    value, sha = read_json(Path(path), INVENTORY_BYTES)
    if (not isinstance(value, dict) or value.get("format") != INVENTORY_FORMAT
            or value.get("dates") != [d.isoformat() for d in sorted(days)] or not isinstance(value.get("rows"), list)):
        raise CliRefused("inventory_dates_mismatch")
    return value["rows"], sha


def open_sources(directories, inventory, panel):
    """Declared day sources through the sanctioned path, ``intervals.sources``; returns (sources, evaluation)."""
    return intervals.sources([open_bundle(d) for d in directories], inventory, panel=panel)


def event_days(source: DaySource, check, *, drop_embargoed=False) -> tuple[dict, set]:
    """({condition_id: event day}, dropped) from the source's descriptors; every close passes ``check`` first.

    With ``drop_embargoed`` a band whose close is refused by ``check`` is dropped (returned in ``dropped``)
    instead of refusing the run; its other records are never handed to the runner."""
    descriptors = DaySource(source.plan, lambda: (r for r in source.records() if r.kind == "descriptor"))
    out, dropped = {}, set()
    for _, batch in items(descriptors):
        for item in batch:
            if item.error is None and isinstance(item.value, Descriptor):
                if item.condition_id in dropped:
                    continue
                close = item.value.market.close_at_utc
                try:
                    check(close)
                except embargo.EmbargoRefused:
                    if not drop_embargoed:
                        raise
                    dropped.add(item.condition_id)
                    out.pop(item.condition_id, None)
                    continue
                day = decision.event_day(close)
                if out.setdefault(item.condition_id, day) != day:
                    raise CliRefused("band_changes_event_day")
    return out, dropped


def restrict(source: DaySource, keep) -> DaySource:
    """The source with only the bands in ``keep``; group records are kept for a kept member already seen."""
    keep = frozenset(keep)
    plan = source.plan
    groups = MappingProxyType({g: tuple(c for c in members if c in keep) for g, members in plan.groups.items()
                               if any(c in keep for c in members)})
    plan = replace(plan, conditions=tuple(c for c in plan.conditions if c.condition_id in keep),
                   windows=MappingProxyType({c: w for c, w in plan.windows.items() if c in keep}), groups=groups)

    def records():
        seen = set()
        for record in source.records():
            if isinstance(record, GroupRecord):
                if any(c in seen for c in groups.get(record.group_id, ())):
                    yield record
                continue
            if record.condition_id in keep:
                if record.kind == "descriptor":
                    seen.add(record.condition_id)
                yield record

    return DaySource(plan, records)


def clusters(sources, check, *, drop_embargoed=False, dropped=None) -> dict:
    """{event day ISO: [restricted DaySource, ...]} over all sources, in day order; ``dropped`` collects
    (day, condition_id) of bands dropped for an embargoed close."""
    out = {}
    for source in sorted(sources, key=lambda s: s.plan.day):
        by_day = {}
        days, gone = event_days(source, check, drop_embargoed=drop_embargoed)
        if dropped is not None:
            dropped.update((source.plan.day.isoformat(), cid) for cid in gone)
        for cid, day in days.items():
            by_day.setdefault(day, set()).add(cid)
        for day, cids in sorted(by_day.items()):
            out.setdefault(day.isoformat(), []).append(restrict(source, cids))
    return out


def _decay(args):
    projection, selections = Path(args.re1_projection).read_bytes(), Path(args.re1_selections).read_bytes()
    sessions, sources = share_decay.load_re1(projection, selections)
    return share_decay.fit(sessions, sources=sources), sources


def _cost(args, purpose, now):
    if args.toxicity_table is None and args.cf_tape is None:
        return None, None, None
    if args.toxicity_table is None or args.cf_tape is None or args.toxicity_table_digest is None:
        raise CliRefused("toxicity_table_digest_and_cf_tape_go_together")
    raw = Path(args.toxicity_table).read_bytes()
    provider = adapters.RecordingFillCost(fill_cost.TableFillCostProvider(json.loads(raw)),
                                          expected_table_digest=args.toxicity_table_digest)
    contexts = adapters.CfTapeContexts(args.cf_tape, purpose=purpose, now=now)
    return provider, contexts, _sha256(raw)


def _write_create_only(out_dir: Path, report: dict, receipt: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=False)
    body = canonical_bytes(report)
    receipt["digests"]["report_sha256"] = _sha256(body)
    with open(out_dir / "report.json", "xb") as handle:
        handle.write(body)
    with open(out_dir / "receipt.json", "xb") as handle:
        handle.write(canonical_bytes(receipt))


def execute(args, *, clock=None) -> dict:
    """Run one command; return the receipt. Refusals raise. ``clock`` is for tests only (default ``utc_now``)."""
    if not isinstance(args.code_commit, str) or not _COMMIT.match(args.code_commit):
        raise CliRefused("code_commit_must_be_40_hex")
    out_dir = Path(args.out_dir)
    if out_dir.exists():
        raise CliRefused("out_dir_exists")
    now = (clock or utc_now)()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise CliRefused("clock_must_be_aware")
    registration = registration_sha = None
    if args.command == "score" and not embargo.scored_panel_open(now):
        raise CliRefused("score_refused_before_%s" % embargo.SCORED_OPENS_AT.isoformat())
    decay, decay_sources = _decay(args)
    if args.command == "score":
        rule, mode, purpose, fill_model = SCORED_RULE, "scored", "scored", adapters.fill_v3_model()
        registration = Path(args.registration).read_bytes()
        registration_sha = prereg.verify(registration, decay_digest=decay.digest(),
                                         fill_model_binding=seams.binding(fill_model),
                                         decision_rule_digest=rule.digest())
    else:
        rule = decision.PROPOSED_RULE if args.replicates is None else replace(decision.PROPOSED_RULE,
                                                                              replicates=args.replicates)
        mode, purpose = "descriptive", "descriptive"
        fill_model = adapters.fill_v3_model() if args.fill_model == "v3" else seams.PricePathFillModel()

    def check(*values):
        if mode == "scored":
            embargo.check("scored", *values, now=now)
        else:
            embargo.check("fit", *values)

    bundles = []
    for directory in args.bundle:
        day, manifest_sha = bundle_day(Path(directory))
        if mode == "scored" and not embargo.SCORED_PANEL[0] <= day <= embargo.SCORED_PANEL[1]:
            raise CliRefused("score_reads_only_the_scored_panel")
        check(day)  # before any stream of the bundle is opened
        bundles.append({"path": str(directory), "day": day.isoformat(), "manifest_sha256": manifest_sha})
    if len({b["day"] for b in bundles}) != len(bundles):
        raise CliRefused("duplicate_bundle_day")
    panel = CALIBRATION_PANEL if mode != "scored" else SCORED_INTERVALS_PANEL
    if panel is None:
        raise CliRefused("score_has_no_intervals_panel")
    inventory, inventory_sha = read_inventory(args.inventory, [date.fromisoformat(b["day"]) for b in bundles])
    sources, evaluation = open_sources(args.bundle, inventory, panel)
    cost, contexts, table_sha = _cost(args, purpose, now if mode == "scored" else None)
    dropped = set()
    runs = {}
    for key, cluster_sources in clusters(sources, check, drop_embargoed=mode != "scored", dropped=dropped).items():
        runs[key] = runner.run(cluster_sources, decay=decay, mode=mode, registration=registration,
                               fill_model=fill_model, cost_provider=cost,
                               context_builder=contexts if contexts is not None else seams.no_context,
                               now=now if mode == "scored" else None,
                               decision_rule_digest=rule.digest() if mode == "scored" else None)
    if not runs:
        raise CliRefused("no_bands")
    verdict = decision.evaluate(runs, rule)
    report = {"format": REPORT_FORMAT, "command": args.command, "label": "SCORED" if mode == "scored" else "DESCRIPTIVE",
              "authority": "none", "decision": verdict,
              "runs": {key: {"digest": r["digest"], "days": r["days"]} for key, r in sorted(runs.items())},
              "decay": decay.summary(), "fill_cost": cost.summary() if cost is not None else None,
              "intervals": {"panel": panel, "windows": len(evaluation.windows),
                            "exclusions": len(evaluation.exclusions)},
              "embargoed_bands": [{"day": d, "condition_id": c} for d, c in sorted(dropped)]}
    receipt = {
        "format": RECEIPT_FORMAT, "command": args.command, "label": report["label"], "clock_utc": now.isoformat(),
        "code": {"commit": args.code_commit,
                 "modules": {m.__name__: _sha256(Path(m.__file__).read_bytes()) for m in CODE_MODULES}},
        "inputs": {"bundles": bundles, "re1": decay_sources, "inventory_sha256": inventory_sha,
                   "toxicity_table_sha256": table_sha,
                   "cf_tape_days": dict(sorted(contexts.receipts.items())) if contexts is not None else None,
                   "registration_sha256": registration_sha},
        "digests": {"grid_hash": grid.GRID_HASH, "decay": decay.digest(), "fill_model_binding": seams.binding(fill_model),
                    "decision_rule": rule.digest(), "decision_result": verdict["digest"],
                    "toxicity_table": cost.table_digest if cost is not None else None},
        "verdict": verdict["verdict"], "winner": verdict["winner"],
    }
    _write_create_only(out_dir, report, receipt)
    return receipt


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="python -m maker_core.frontier.cli", description=__doc__.split("\n")[0])
    commands = top.add_subparsers(dest="command", required=True)
    for name in ("calibrate", "score"):
        sub = commands.add_parser(name)
        sub.add_argument("--bundle", action="append", required=True, help="v0.2 replay bundle directory (repeatable)")
        sub.add_argument("--inventory", required=True, help="the rehearsal inventory document for the bundle days")
        sub.add_argument("--re1-projection", required=True)
        sub.add_argument("--re1-selections", required=True)
        sub.add_argument("--out-dir", required=True, help="new directory; must not exist")
        sub.add_argument("--code-commit", required=True, help="40-hex commit of the code being run")
        sub.add_argument("--toxicity-table")
        sub.add_argument("--toxicity-table-digest")
        sub.add_argument("--cf-tape", help="cf tape output directory (strictly_through backlog)")
        if name == "score":
            sub.add_argument("--registration", required=True, help="the signed preregistration document")
        else:
            sub.add_argument("--replicates", type=int)
            sub.add_argument("--fill-model", choices=("v3", "v2-strictly_through"), default="v3")
    return top


def main(argv=None, *, clock=None) -> int:
    """Command entry. ``clock`` is for tests only; without it the real UTC clock (``utc_now``) is read."""
    args = parser().parse_args(argv)
    try:
        receipt = execute(args, clock=clock or utc_now)
    except (CliRefused, embargo.EmbargoRefused, prereg.PreregRefused, runner.FrontierRefused,
            decision.DecisionRefused, adapters.AdapterRefused, seams.FillBindingRefused, BundleError) as exc:
        print(json.dumps({"refused": str(exc), "type": type(exc).__name__}))
        return 2
    print(json.dumps({"verdict": receipt["verdict"], "winner": receipt["winner"], "out_dir": args.out_dir}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
