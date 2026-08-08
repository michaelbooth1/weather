"""Post-mortem: why maker days do not count toward the live-forward gate.

The market-making gate cannot decide until enough maker days are *countable*, and
that counter has been advancing far slower than wall-clock. This module answers
"which gate actually blocked each day, and since when?" from evidence that is
already on disk, so the question does not have to be re-argued from memory.

Every maker run writes ``preflight_remediation.json`` next to its other
artifacts. That file already carries the verdict (``counts_toward_live_forward_gate``)
and the per-incident reasons (``gate``, ``root_cause``, ``market_id``). This reads
those files only — it never opens the large per-run CSV or JSON payloads — so it is
cheap enough to run inside the graded capture window.

**A day counts if ANY of its runs counted.** Runs are retries within the day, so
requiring every run to count would understate the yield.

Run it with::

    python -m weather.reporting.market.mm_countability_postmortem

``first_seen`` / ``last_seen`` per blocker is the point of this report: a blocker
whose ``last_seen`` is old has been fixed, and one whose ``first_seen`` is recent
is a regression with a date attached.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from weather.paths import data_path
from weather.schema_registry import schema_version


DAY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REMEDIATION_NAME = "preflight_remediation.json"
QUARANTINE_DIR_NAME = "_quarantine"
SCHEMA_VERSION = schema_version("mm_countability_postmortem")

UNPARSEABLE = "unparseable_remediation_file"
NO_REMEDIATION = "no_remediation_file_written"


def _runs_root(runs_root=None):
    return Path(runs_root) if runs_root is not None else Path(data_path("mm_runs"))


def iter_day_dirs(runs_root=None):
    """Yield ``(day, path)`` for each dated maker-run directory, oldest first."""
    root = _runs_root(runs_root)
    if not root.is_dir():
        return
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if child.is_dir() and DAY_PATTERN.match(child.name):
            yield child.name, child


def _read_remediation(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None, UNPARSEABLE


def summarise_run(payload):
    """Reduce one remediation payload to (counted, [(gate, root_cause, market), ...])."""
    counted = bool(payload.get("counts_toward_live_forward_gate"))
    blockers = []
    for incident in payload.get("incidents") or ():
        if not isinstance(incident, dict):
            continue
        # An incident that still allows the day to count is noise for this report.
        if incident.get("can_still_count_live_forward_day"):
            continue
        blockers.append(
            (
                str(incident.get("gate") or "unknown_gate"),
                str(incident.get("root_cause") or "unknown_root_cause"),
                str(incident.get("market_id") or "unknown_market"),
            )
        )
    return counted, blockers


def iter_run_dirs(day_dir):
    """Yield canonical run directories, excluding lifecycle scaffolding."""
    for run_dir in sorted(p for p in day_dir.iterdir() if p.is_dir()):
        if run_dir.name == QUARANTINE_DIR_NAME or run_dir.name.startswith("."):
            continue
        yield run_dir


def summarise_day(day_dir):
    """Reduce one maker day. A day counts if ANY run in it counted."""
    runs = 0
    counted_runs = 0
    blockers = Counter()
    markets = Counter()
    for run_dir in iter_run_dirs(day_dir):
        remediation = run_dir / REMEDIATION_NAME
        if not remediation.is_file():
            # A run directory with no remediation file cannot explain itself.
            # Count it so the totals never silently omit a run.
            runs += 1
            blockers[(NO_REMEDIATION, NO_REMEDIATION)] += 1
            continue
        payload, error = _read_remediation(remediation)
        runs += 1
        if error is not None:
            blockers[(UNPARSEABLE, UNPARSEABLE)] += 1
            continue
        counted, run_blockers = summarise_run(payload)
        if counted:
            counted_runs += 1
        for gate, root_cause, market in run_blockers:
            blockers[(gate, root_cause)] += 1
            markets[market] += 1
    return {
        "runs": runs,
        "counted_runs": counted_runs,
        "counted": counted_runs > 0,
        "blockers": blockers,
        "markets": markets,
    }


def summarise_counterfactual_day(day_dir, repaired_gates):
    """Count runs after a hypothetical repair of named blocking gates.

    Missing, unparseable, and unexplained non-countable runs remain non-countable.
    This is therefore a gate-specific ceiling, not permission to bypass a gate.
    """
    repaired_gates = {str(gate) for gate in repaired_gates}
    runs = 0
    counted_runs = 0
    for run_dir in iter_run_dirs(day_dir):
        remediation = run_dir / REMEDIATION_NAME
        if not remediation.is_file():
            runs += 1
            continue
        payload, error = _read_remediation(remediation)
        runs += 1
        if error is not None:
            continue
        counted, blockers = summarise_run(payload)
        repaired = bool(blockers) and all(gate in repaired_gates for gate, _, _ in blockers)
        if counted or repaired:
            counted_runs += 1
    return {
        "runs": runs,
        "counted_runs": counted_runs,
        "counted": counted_runs > 0,
    }


def build_gate_repair_counterfactual(runs_root=None, *, repaired_gates):
    """Return the optimistic yield if named gate failures had all been repaired."""
    repaired_gates = sorted({str(gate) for gate in repaired_gates})
    days = []
    for day, day_dir in iter_day_dirs(runs_root):
        summary = summarise_counterfactual_day(day_dir, repaired_gates)
        days.append({"day": day, **summary})
    counted_days = sum(1 for row in days if row["counted"])
    total_days = len(days)
    return {
        "repaired_gates": repaired_gates,
        "total_days": total_days,
        "counted_days": counted_days,
        "uncounted_days": total_days - counted_days,
        "countable_day_yield": (counted_days / total_days) if total_days else None,
        "assumption": (
            "every non-countable incident at the named gates is eliminated; all other "
            "blockers and missing or unparseable remediation evidence remain"
        ),
        "days": days,
    }


def build_postmortem(runs_root=None):
    """Aggregate every maker day into a countability post-mortem."""
    days = []
    blocker_totals = Counter()
    blocker_days = Counter()
    blocker_first_seen = {}
    blocker_last_seen = {}
    market_totals = Counter()

    for day, day_dir in iter_day_dirs(runs_root):
        summary = summarise_day(day_dir)
        days.append(
            {
                "day": day,
                "runs": summary["runs"],
                "counted_runs": summary["counted_runs"],
                "counted": summary["counted"],
                "blockers": sorted(
                    (
                        {"gate": gate, "root_cause": root_cause, "occurrences": count}
                        for (gate, root_cause), count in summary["blockers"].items()
                    ),
                    key=lambda row: (-row["occurrences"], row["gate"], row["root_cause"]),
                ),
            }
        )
        for key, count in summary["blockers"].items():
            blocker_totals[key] += count
            blocker_days[key] += 1
            blocker_first_seen.setdefault(key, day)
            blocker_last_seen[key] = day
        market_totals.update(summary["markets"])

    counted_days = sum(1 for row in days if row["counted"])
    total_days = len(days)
    blockers = sorted(
        (
            {
                "gate": gate,
                "root_cause": root_cause,
                "occurrences": count,
                "days_affected": blocker_days[(gate, root_cause)],
                "first_seen": blocker_first_seen[(gate, root_cause)],
                "last_seen": blocker_last_seen[(gate, root_cause)],
            }
            for (gate, root_cause), count in blocker_totals.items()
        ),
        key=lambda row: (-row["days_affected"], -row["occurrences"], row["gate"]),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "total_days": total_days,
        "counted_days": counted_days,
        "uncounted_days": total_days - counted_days,
        "countable_day_yield": (counted_days / total_days) if total_days else None,
        "first_day": days[0]["day"] if days else None,
        "last_day": days[-1]["day"] if days else None,
        "blockers": blockers,
        "markets": sorted(
            ({"market_id": market, "occurrences": count} for market, count in market_totals.items()),
            key=lambda row: (-row["occurrences"], row["market_id"]),
        ),
        "days": days,
    }


def _percent(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(report):
    """Render the post-mortem as Markdown."""
    lines = [
        "# Maker countability post-mortem",
        "",
        f"**{report['counted_days']} of {report['total_days']} maker days counted toward the "
        f"live-forward gate — a yield of {_percent(report['countable_day_yield'])}.**",
        "",
        f"Window: `{report['first_day']}` → `{report['last_day']}`.",
        "",
        "The MM gate cannot decide until enough countable days accumulate, so this yield —",
        "not elapsed calendar time — is what sets the date the gate can rule.",
        "",
        "## Blockers, worst first",
        "",
        "`last_seen` is the column that matters: an old `last_seen` is a fixed problem, and a",
        "recent `first_seen` is a regression with a date attached.",
        "",
        "| Gate | Root cause | Days | Occurrences | First seen | Last seen |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in report["blockers"]:
        lines.append(
            f"| `{row['gate']}` | `{row['root_cause']}` | {row['days_affected']} | "
            f"{row['occurrences']} | {row['first_seen']} | {row['last_seen']} |"
        )
    if not report["blockers"]:
        lines.append("| _none recorded_ | | | | | |")

    counterfactual = report.get("gate_repair_counterfactual")
    if counterfactual:
        gates = ", ".join(f"`{gate}`" for gate in counterfactual["repaired_gates"])
        lines += [
            "",
            "## Gate-repair counterfactual",
            "",
            f"If every blocking incident at {gates} had been repaired, "
            f"**{counterfactual['counted_days']} of {counterfactual['total_days']} days** "
            f"would have counted ({_percent(counterfactual['countable_day_yield'])}).",
            "",
            f"Assumption: {counterfactual['assumption']}.",
        ]

    lines += ["", "## Markets", "", "| Market | Blocking incidents |", "| --- | ---: |"]
    for row in report["markets"]:
        lines.append(f"| `{row['market_id']}` | {row['occurrences']} |")
    if not report["markets"]:
        lines.append("| _none recorded_ | |")

    lines += [
        "",
        "## Day by day",
        "",
        "| Day | Runs | Counted runs | Counted | Top blocker |",
        "| --- | ---: | ---: | :---: | --- |",
    ]
    for row in report["days"]:
        top = row["blockers"][0] if row["blockers"] else None
        top_text = f"`{top['gate']}` / `{top['root_cause']}`" if top else "—"
        mark = "**yes**" if row["counted"] else "no"
        lines.append(
            f"| {row['day']} | {row['runs']} | {row['counted_runs']} | {mark} | {top_text} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs-root", default=None, help="defaults to data/mm_runs")
    parser.add_argument("--json-out", default=None, help="write the report as JSON")
    parser.add_argument("--markdown-out", default=None, help="write the report as Markdown")
    parser.add_argument(
        "--counterfactual-repair-gate",
        action="append",
        default=[],
        help="optimistically replay with every blocker at this gate repaired; repeatable",
    )
    args = parser.parse_args(argv)

    report = build_postmortem(args.runs_root)
    if args.counterfactual_repair_gate:
        report["gate_repair_counterfactual"] = build_gate_repair_counterfactual(
            args.runs_root,
            repaired_gates=args.counterfactual_repair_gate,
        )
    markdown = render_markdown(report)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.markdown_out:
        out = Path(args.markdown_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
    if not args.json_out and not args.markdown_out:
        print(markdown)
    else:
        print(
            f"{report['counted_days']}/{report['total_days']} maker days counted "
            f"({_percent(report['countable_day_yield'])})"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
