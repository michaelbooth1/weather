"""``python -m maker_core.frontier.cli`` -- the informed-v1 frontier decision pipeline (item 330 build 4).

Two commands. Both are offline and read-only on their inputs, write one new output directory (create-only:
``report.json`` and ``receipt.json``), and grant no authority.

``calibrate``
    A DESCRIPTIVE run of the whole pipeline (runner per capture-day cluster, then ``decision.evaluate``) on the
    v0.2 calibration bundles (``panel.CALIBRATION_DATES``, 2026-09-27..29). Every bundle day passes
    ``embargo.check("fit", ...)`` before its bundle is opened. Its verdict is a rehearsal of the rule, never a
    decision: its output is labelled ``PIPELINE REHEARSAL`` (``REHEARSAL_LABEL``), is not a power estimate, and
    no number from it feeds the margin proposal.

    A band whose descriptor close falls in a refused window (for example a 09-29 band closing on 09-30) is
    dropped. The drop is decided only from schedule metadata: the descriptor stream
    (``universe_v02.descriptors``), never another stream. For a dropped band no settlement, book, trade,
    outcome, terms, coverage or tape row is decoded, indexed or counted by this package: ``restrict`` removes
    its records by condition ID before any decode, and the cf tape adapter filters its rows out on the
    ``condition_id`` column in the Parquet read itself. (The bundle and tape readers' integrity passes
    still hash every byte of each file and check each stream's total record count; those are file checks,
    not band reads.) The receipt lists ``embargoed_bands`` and kept and dropped counts per day and per
    horizon (a band's horizon is the ``horizon_days`` of its first descriptor that day). If any horizon has
    all its bands dropped over the run, calibrate refuses (``calibrate_horizon_fully_embargoed``): an
    empty calibration is never emitted as a pass.

``score``
    The preregistered read. It refuses, in this order:

    1. before ``embargo.SCORED_OPENS_AT`` (2026-11-14T00:00Z) by the real UTC clock (``clock`` is injectable
       for tests only; the command line always uses ``datetime.now(timezone.utc)``);
    2. without ``--toxicity-table``, ``--toxicity-table-digest`` and ``--cf-tape`` (all three required);
    3. while ``SCORED_RULE``'s margin is unsigned (``decision_rule_margin_unsigned``);
    4. unless ``prereg.verify`` accepts the registration for the decay digest (refitted from the same RE-1
       bytes), the fill-v3 binding (``adapters.FILL_V3_BINDING``), the grid hash, ``SCORED_RULE``'s
       decision-rule digest and the toxicity table digest (its ``Toxicity table:`` line); today no
       registration is pinned, so it always refuses here;
    5. any bundle whose day is outside the scored panel 2026-10-17..2026-11-13 (``embargo.SCORED_PANEL``),
       checked before the bundle is opened;
    6. always, today: no ``maker_core.replay.v2.panel.PANELS`` name covers the scored panel (``registered``
       is the reserved 09-30..10-15 window, ``calibration`` is 09-27..29), so there is no sanctioned way to
       declare its windows (``score_has_no_intervals_panel``). Adding a panel is a separate reviewed change.

    What it reads is bound: the fill v3 kernel, the decay model, the decision rule (margin included) and the
    toxicity table are each pinned by a registration line; the panel days and the hazard (the runner's fixed
    default, not a flag) are fixed in code. The bundles, inventory and tape are the data, hashed into the
    receipt; they are not tunable.

Sources: only v0.2 (stream) bundles, opened with ``open_stream_bundle`` and turned into day sources by
``maker_core.replay.v2.intervals.sources`` with the required ``--inventory`` (the weather producer's universe rows,
the rehearsal inventory document): the §4 rule and the owner exclusions declare every window, so a captured
bundle scores only through declared intervals (U1 Defender MF4). A v0.1 bundle is refused
(``v01_bundle_unsupported``).

Clusters: one per UTC **capture day** (the bundle day; ``decision.CLUSTER_UNITS``). The runner already keeps
no state across days, so a capture-day cluster is exactly one bundle run on its kept bands, and the clusters
sum to one run over all of them. A capture day holds bands at horizon 1 (event T) and horizon 2 (event T+1)
quoted on the same day; clustering on the capture day keeps those correlated quotes in one cluster instead of
splitting them across event-day clusters, and every cluster is a fully observed day. The report discloses the
horizon split (kept and dropped bands per day and horizon).

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
from typing import NamedTuple

from maker_core.evidence.journal import canonical_bytes, digest
from maker_core.frontier import adapters, decision, embargo, grid, prereg, runner, seams, share_decay
from maker_core.quoting import fill_cost
from maker_core.replay import fill_v3
from maker_core.replay.bundle import FORMAT as FORMAT_V01, BundleError
from maker_core.replay.bundle_v02 import GroupRecord, open_stream_bundle, read_format
from maker_core.replay.pack_io import read_json
from maker_core.replay.payloads import Descriptor
from maker_core.replay.v2 import intervals, universe_v02
from maker_core.replay.v2.lockstep import DaySource

REPORT_FORMAT = "maker-core.frontier-decision-report.1"
RECEIPT_FORMAT = "maker-core.frontier-decision-receipt.1"
SCORED_RULE = decision.PROPOSED_RULE
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
# The rehearsal inventory document (``tools/research/maker_replay_v2/rehearse_cli.py``, which core cannot import).
INVENTORY_FORMAT = "maker_core.replay.v2.rehearsal_inventory.v0.1"
INVENTORY_BYTES = 4 * 1024**2
CALIBRATION_PANEL = "calibration"
# No ``panel.PANELS`` name covers 2026-10-17..2026-11-13; ``score`` refuses until a reviewed change adds one.
SCORED_INTERVALS_PANEL = None
REHEARSAL_LABEL = "PIPELINE REHEARSAL"
REHEARSAL_NOTE = "pipeline rehearsal only; not a power estimate; no number from it feeds the margin proposal"
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
    """Declared day sources through the sanctioned path, ``intervals.sources``; returns
    (bundles, sources, evaluation), each list in day order."""
    bundles = sorted((open_bundle(d) for d in directories), key=lambda b: b.day)
    sources, evaluation = intervals.sources(bundles, inventory, panel=panel)
    return bundles, sources, evaluation


class Schedule(NamedTuple):
    """One bundle day's band schedule, from its descriptor stream only."""

    event_days: dict  # kept condition_id -> event day
    dropped: dict  # dropped condition_id -> reason (EMBARGOED_CLOSE or CLOSED_BEFORE_DAY)
    horizons: dict  # condition_id -> horizon_days of its first descriptor that day


EMBARGOED_CLOSE = "embargoed_close"
CLOSED_BEFORE_DAY = "closed_before_day"


def in_reserved(instant) -> bool:
    """Whether ``instant``'s UTC date is in the reserved window: such a close is never dropped, always refused."""
    return embargo.RESERVED[0] <= instant.astimezone(timezone.utc).date() <= embargo.RESERVED[1]


def schedule(bundle, check, *, drop_embargoed=False, drop_closed_before_day=False) -> Schedule:
    """The day's band schedule from its **descriptor stream only** (``universe_v02.descriptors``).

    With ``drop_closed_before_day`` (scored mode) a band whose close is at or before the start of the bundle's
    UTC day is dropped **before** its close is checked (``closed_before_day``): such a band (for example a
    horizon -1 descriptor captured 10-17T00:00-04:00Z, local 10-16, target 10-15, close 10-16T04:00Z) can earn
    nothing that day, and checking its close would refuse the whole scored run. A close inside the reserved
    window (09-30..10-15) is never dropped: it always reaches ``check`` and refuses (absolute contract). Every other close passes
    ``check``. With ``drop_embargoed`` (calibrate) a band whose close is refused is dropped instead of refusing
    the run (``embargoed_close``). Nothing but descriptors (schedule metadata) is read to decide either."""
    out, dropped, horizons = {}, {}, {}
    day_start = datetime.combine(bundle.day, datetime.min.time(), tzinfo=timezone.utc)
    for record in universe_v02.descriptors(bundle):
        cid = record.condition_id
        if cid in dropped:
            continue
        value = universe_v02.decoded(record)
        if not isinstance(value, Descriptor):
            raise CliRefused("descriptor_stream_holds_other_value")
        horizons.setdefault(cid, value.horizon_days)
        close = value.market.close_at_utc
        if drop_closed_before_day and close <= day_start and not in_reserved(close):
            dropped[cid] = CLOSED_BEFORE_DAY
            out.pop(cid, None)
            continue
        try:
            check(close)
        except embargo.EmbargoRefused:
            if not drop_embargoed:
                raise
            dropped[cid] = EMBARGOED_CLOSE
            out.pop(cid, None)
            continue
        day = decision.event_day(close)
        if out.setdefault(cid, day) != day:
            raise CliRefused("band_changes_event_day")
    return Schedule(out, dict(sorted(dropped.items())), horizons)


def drop_counts(schedules) -> dict:
    """{day ISO: {horizon: {"kept": n, "dropped": m}}} plus ``"all"``: the same per horizon over the run."""
    out, total = {}, {}
    for day, plan in sorted(schedules.items()):
        per = out.setdefault(day.isoformat(), {})
        for cid, horizon in sorted(plan.horizons.items()):
            key = "dropped" if cid in plan.dropped else "kept" if cid in plan.event_days else None
            if key is None:
                continue
            for bucket in (per, total):
                bucket.setdefault(str(horizon), {"kept": 0, "dropped": 0})[key] += 1
    out["all"] = total
    return out


def refuse_fully_embargoed_horizons(counts) -> None:
    """An empty calibration is never a pass: a horizon whose bands were all dropped refuses the run."""
    empty = sorted(h for h, c in counts["all"].items() if c["dropped"] and not c["kept"])
    if empty:
        raise CliRefused("calibrate_horizon_fully_embargoed: horizon " + ",".join(empty))


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


def clusters(sources, schedules) -> dict:
    """{capture day ISO: [restricted DaySource]} over all sources, in day order. ``schedules`` maps each
    source's day to its ``Schedule``; only its kept bands enter."""
    out = {}
    for source in sorted(sources, key=lambda s: s.plan.day):
        key = source.plan.day.isoformat()
        if key in out:
            raise CliRefused("duplicate_capture_day")
        out[key] = [restrict(source, schedules[source.plan.day].event_days)]
    return out


def _decay(args):
    projection, selections = Path(args.re1_projection).read_bytes(), Path(args.re1_selections).read_bytes()
    sessions, sources = share_decay.load_re1(projection, selections)
    return share_decay.fit(sessions, sources=sources), sources


def _cost(args, purpose, now, conditions=None):
    if args.toxicity_table is None and args.cf_tape is None:
        return None, None, None
    if args.toxicity_table is None or args.cf_tape is None or args.toxicity_table_digest is None:
        raise CliRefused("toxicity_table_digest_and_cf_tape_go_together")
    raw = Path(args.toxicity_table).read_bytes()
    provider = adapters.RecordingFillCost(fill_cost.TableFillCostProvider(json.loads(raw)),
                                          expected_table_digest=args.toxicity_table_digest)
    contexts = adapters.CfTapeContexts(args.cf_tape, purpose=purpose, now=now, conditions=conditions)
    return provider, contexts, _sha256(raw)


def cost_coverage(cost, contexts, rule, *, refuse: bool) -> dict | None:
    """The fill-cost coverage of a run: decisions without a provider markout (which fall back to the 0.0043
    floor) and kept bands queried on a day with no tape row at all. With ``refuse`` (score) a band without
    rows refuses, and so does a share above ``rule.max_cost_unavailable_share``."""
    if cost is None:
        return None
    missing, total = cost.unavailable()
    share = missing / total if total else 0.0
    holes = contexts.bands_without_rows() if contexts is not None else []
    per_day = {}
    for at, _, _, status, *_ in cost.decisions:
        key = at[:10] if isinstance(at, str) else "unattributed"
        counts = per_day.setdefault(key, [0, 0])
        counts[0] += status in adapters.UNAVAILABLE_STATUSES
        counts[1] += 1
    per_cluster = {day: {"decisions": n, "cost_unavailable": m, "cost_unavailable_share": m / n}
                   for day, (m, n) in sorted(per_day.items())}
    worst = max((c["cost_unavailable_share"] for c in per_cluster.values()), default=0.0)
    out = {"decisions": total, "cost_unavailable": missing, "cost_unavailable_share": share,
           "max_cost_unavailable_share": rule.max_cost_unavailable_share,
           "max_cost_unavailable_share_per_cluster": rule.max_cost_unavailable_share_per_cluster,
           "per_cluster": per_cluster,
           "bands_without_tape_rows": [{"day": d, "condition_id": c} for d, c in holes],
           "unavailable_decisions": [{"at": d[0], "condition_id": d[1]} for d in cost.decisions
                                     if d[3] in adapters.UNAVAILABLE_STATUSES]}
    if refuse and holes:
        raise CliRefused("cf_tape_band_without_rows: %s %s" % holes[0])
    if refuse and share > rule.max_cost_unavailable_share:
        raise CliRefused("cost_unavailable_share_above_bound")
    if refuse and worst > rule.max_cost_unavailable_share_per_cluster:
        raise CliRefused("cost_unavailable_share_per_cluster_above_bound")
    return out


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
    if args.command == "score":
        if args.toxicity_table is None or args.toxicity_table_digest is None or args.cf_tape is None:
            raise CliRefused("score_requires_toxicity_table_digest_and_cf_tape")
        if not SCORED_RULE.margin_signed:
            raise CliRefused("decision_rule_margin_unsigned")
    decay, decay_sources = _decay(args)
    if args.command == "score":
        rule, mode, purpose, fill_model = SCORED_RULE, "scored", "scored", adapters.fill_v3_model()
        registration = Path(args.registration).read_bytes()
        registration_sha = prereg.verify(registration, decay_digest=decay.digest(),
                                         fill_model_binding=seams.binding(fill_model),
                                         decision_rule_digest=rule.digest(),
                                         toxicity_table_digest=args.toxicity_table_digest)
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
    opened, sources, evaluation = open_sources(args.bundle, inventory, panel)
    schedules = {b.day: schedule(b, check, drop_embargoed=mode != "scored", drop_closed_before_day=mode == "scored")
                 for b in opened}
    counts = drop_counts(schedules)
    if mode != "scored":
        refuse_fully_embargoed_horizons(counts)
    dropped = sorted((day.isoformat(), cid, reason) for day, plan in schedules.items()
                     for cid, reason in plan.dropped.items())
    kept = frozenset(cid for plan in schedules.values() for cid in plan.event_days)
    cost, contexts, table_sha = _cost(args, purpose, now if mode == "scored" else None, kept)
    if mode == "scored" and cost is None:
        raise CliRefused("score_requires_toxicity_table_digest_and_cf_tape")
    runs = {}
    for key, cluster_sources in clusters(sources, schedules).items():
        runs[key] = runner.run(cluster_sources, decay=decay, mode=mode, registration=registration,
                               fill_model=fill_model, cost_provider=cost,
                               context_builder=contexts if contexts is not None else seams.no_context,
                               now=now if mode == "scored" else None,
                               decision_rule_digest=rule.digest() if mode == "scored" else None)
    if not runs:
        raise CliRefused("no_bands")
    coverage = cost_coverage(cost, contexts, rule, refuse=mode == "scored")
    verdict = decision.evaluate(runs, rule)
    label = "SCORED" if mode == "scored" else REHEARSAL_LABEL
    embargoed = {"embargoed_bands": [{"day": d, "condition_id": c, "reason": r} for d, c, r in dropped],
                 "counts_by_day_and_horizon": counts}
    report = {"format": REPORT_FORMAT, "command": args.command, "label": label,
              "note": None if mode == "scored" else REHEARSAL_NOTE, "authority": "none", "decision": verdict,
              "runs": {key: {"digest": r["digest"], "days": r["days"]} for key, r in sorted(runs.items())},
              "decay": decay.summary(), "fill_cost": cost.summary() if cost is not None else None,
              "intervals": {"panel": panel, "windows": len(evaluation.windows),
                            "exclusions": len(evaluation.exclusions)},
              "embargo": embargoed,
              "clusters": {"unit": rule.cluster_unit, "keys": sorted(runs),
                           "horizon_split": counts,
                           "note": "a capture day holds horizon-1 (event T) and horizon-2 (event T+1) bands"}}
    receipt = {
        "format": RECEIPT_FORMAT, "command": args.command, "label": label, "note": report["note"],
        "clock_utc": now.isoformat(), "embargo": embargoed, "cost_coverage": coverage,
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
    print(json.dumps({"label": receipt["label"], "note": receipt["note"], "verdict": receipt["verdict"],
                      "winner": receipt["winner"], "out_dir": args.out_dir}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
