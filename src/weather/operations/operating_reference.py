"""Generate the operating reference: the numbers and windows that govern this host.

**Why this is generated and not written by hand.** The facts an operator needs at
3am — when does the streak window open, what counts as a complete day, what is
already scheduled at 05:00 — live in three different places: Python constants,
PowerShell guards, and the live Windows scheduler. Nothing joined them, so the
question got answered by grepping source, and the one document that did carry a
24-hour map drifted until its disk figure was three times wrong.

A stale operations document is worse than a missing one because it gets believed.
So this projects the live values instead of copying them: constants are **imported**,
never scraped, and the schedule is read from the scheduler at render time. If a
constant is renamed or deleted this fails loudly rather than printing a stale number.

Run it with::

    python -m weather.operations.operating_reference --out docs/operations/OPERATING_REFERENCE.md

Add a row to ``GOVERNING_CONSTANTS`` when a constant starts governing an operator
decision. The bar is: *would someone have to read source to answer a 3am question?*
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import platform
import re
import subprocess
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path


ConstantSpec = namedtuple("ConstantSpec", "module attribute meaning matters_because")

#: Constants an operator or agent needs to answer a question without reading source.
GOVERNING_CONSTANTS = (
    ConstantSpec(
        "weather.collection.collection_health",
        "AFTERNOON_START_HOUR",
        "Local hour the graded capture window opens.",
        "A Toronto day's CLEAN/PARTIAL verdict is computed only over this window, so "
        "capture gaps outside it cannot cost a streak day — and anything heavy inside it can.",
    ),
    ConstantSpec(
        "weather.collection.collection_health",
        "AFTERNOON_END_HOUR",
        "Local hour the graded capture window closes.",
        "Once it closes the day's streak verdict is banked and cannot be changed by a later gap.",
    ),
    ConstantSpec(
        "weather.collection.collection_health",
        "EARLY_HOUR_START_HOUR",
        "Local hour the early-hour evaluation window opens.",
        "Early-hour model performance is scored over this window; it does not gate the streak.",
    ),
    ConstantSpec(
        "weather.collection.collection_health",
        "EARLY_HOUR_END_HOUR",
        "Local hour the early-hour evaluation window closes.",
        "Bounds the early-hour Brier comparison that blocks promotion.",
    ),
    ConstantSpec(
        "weather.collection.collection_health",
        "FREE_REPLACEMENT_MIN_HEALTHY_FAMILIES",
        "Minimum healthy free source families required.",
        "Paid weather providers are unsupported, so free-source health is the only path.",
    ),
    ConstantSpec(
        "weather.backtesting.settlement_ledger",
        "COMPLETE_DAY_MIN_ROWS",
        "Minimum hourly rows for a settlement day to count as complete.",
        "This is NOT a knob: it decides both whether settlement trusts the daily summary "
        "and whether a day counts toward the streak. Lowering it to unblock a retrain "
        "silently changes settlement truth.",
    ),
    ConstantSpec(
        "weather.backtesting.settlement_ledger",
        "MATERIAL_COVERAGE_WINDOW",
        "Human-readable coverage window for material capture.",
        "Should agree with the afternoon window above; disagreement is a defect.",
    ),
)

#: Windows that are protected by policy rather than by a single constant.
PROTECTED_WINDOWS = (
    (
        "12:00-18:00 local",
        "Graded capture window",
        "The streak verdict is computed here (see AFTERNOON_START/END_HOUR). "
        "Never merge a roll-sensitive branch, run the chain, backfill, or reboot inside it.",
        "weather.collection.collection_health",
    ),
    (
        "01:00-04:00 local",
        "Quiet merge window",
        "The only window a ROLL-SENSITIVE branch may be merged, because landing one makes "
        "the capture supervisors readopt code. Roll-free branches do not need it.",
        "scripts/ops/quiet_window_merge.ps1",
    ),
    (
        "18:00-00:05 local",
        "Near-close capture",
        "Near-close fast CLOB capture, MM quoting, and settlement watch. Policy says nothing "
        "heavy, ever. Weigh any exception against what is actually live at the time.",
        "docs/operations/HOST_LOAD_POLICY.md",
    ),
)


def _module_and_line(spec):
    """Import the module and locate the constant's assignment line. Fails loudly."""
    module = importlib.import_module(spec.module)
    if not hasattr(module, spec.attribute):
        raise AttributeError(
            f"{spec.module}.{spec.attribute} no longer exists. "
            "The operating reference lists it as governing an operator decision — "
            "either restore it or remove its row from GOVERNING_CONSTANTS."
        )
    value = getattr(module, spec.attribute)
    source_file = inspect.getsourcefile(module)
    line = None
    if source_file:
        pattern = re.compile(rf"^{re.escape(spec.attribute)}\s*=")
        try:
            for index, text in enumerate(Path(source_file).read_text(encoding="utf-8").splitlines(), 1):
                if pattern.match(text):
                    line = index
                    break
        except OSError:
            line = None
    return value, source_file, line


def collect_constants():
    """Resolve every governing constant to its live value and source location."""
    rows = []
    for spec in GOVERNING_CONSTANTS:
        value, source_file, line = _module_and_line(spec)
        rows.append(
            {
                "module": spec.module,
                "attribute": spec.attribute,
                "value": value,
                "source_file": source_file,
                "line": line,
                "meaning": spec.meaning,
                "matters_because": spec.matters_because,
            }
        )
    return rows


def collect_schedule():
    """Read daily-triggered scheduled tasks from the live host.

    Returns ``[]`` off Windows or when the scheduler is unreadable — this report is
    useful without it, and a research host must not fail to render.
    """
    if platform.system() != "Windows":
        return []
    script = (
        "Get-ScheduledTask | Where-Object { $_.TaskName -match 'Weather' } | "
        "ForEach-Object { $n = $_.TaskName; foreach ($t in $_.Triggers) { "
        "if ($t.StartBoundary) { [pscustomobject]@{ name = $n; "
        "at = ([datetime]$t.StartBoundary).ToString('HH:mm') } } } } | "
        "ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = [payload]
    rows = [
        {"name": str(row.get("name")), "at": str(row.get("at"))}
        for row in payload
        if isinstance(row, dict) and row.get("name") and row.get("at")
    ]
    return sorted(rows, key=lambda row: (row["at"], row["name"]))


def render_markdown(constants, schedule, generated_at=None):
    """Render the operating reference."""
    generated_at = generated_at or datetime.now(timezone.utc)
    lines = [
        "# Operating reference",
        "",
        "**Generated — do not hand-edit.** Regenerate with:",
        "",
        "```powershell",
        ".\\venv\\Scripts\\python.exe -m weather.operations.operating_reference \\",
        "    --out docs/operations/OPERATING_REFERENCE.md",
        "```",
        "",
        f"Generated `{generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')}`.",
        "",
        "This exists because the facts needed to answer an operational question live in three",
        "places — Python constants, PowerShell guards, and the live scheduler — and nothing",
        "joined them. Constants below are **imported at render time**, never copied, so they",
        "cannot drift. A renamed or deleted constant fails this generator loudly.",
        "",
        "## Protected windows",
        "",
        "| Window | Name | Why | Owner |",
        "| --- | --- | --- | --- |",
    ]
    for window, name, why, owner in PROTECTED_WINDOWS:
        lines.append(f"| **{window}** | {name} | {why} | `{owner}` |")

    lines += [
        "",
        "## Governing constants",
        "",
        "| Constant | Value | Meaning | Why it matters |",
        "| --- | ---: | --- | --- |",
    ]
    for row in constants:
        location = f"`{row['module']}`"
        if row["line"]:
            location += f" line {row['line']}"
        lines.append(
            f"| **`{row['attribute']}`**<br/>{location} | `{row['value']}` | "
            f"{row['meaning']} | {row['matters_because']} |"
        )

    lines += ["", "## Daily timetable", ""]
    if schedule:
        lines += [
            "Every `Weather*` scheduled task with a time trigger, read from the live host.",
            "**One-shot tasks with past dates appear here but will not fire again** — check",
            "`Get-ScheduledTaskInfo` before assuming a slot is occupied.",
            "",
            "| Local time | Task |",
            "| --- | --- |",
        ]
        for row in schedule:
            lines.append(f"| `{row['at']}` | `{row['name']}` |")
    else:
        lines += [
            "_Not available: the scheduler was unreadable, or this was generated off the",
            "production host. Regenerate on the capture host to populate it._",
        ]

    lines += [
        "",
        "## Update this file when",
        "",
        "Never by hand. Add a row to `GOVERNING_CONSTANTS` in",
        "`src/weather/operations/operating_reference.py` when a constant starts governing an",
        "operator decision, then regenerate. The bar for inclusion is: *would someone have to",
        "read source to answer a 3am question?*",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the operating reference.")
    parser.add_argument("--out", default=None, help="write Markdown here; otherwise print")
    parser.add_argument(
        "--no-schedule",
        action="store_true",
        help="skip reading the live scheduler",
    )
    args = parser.parse_args(argv)

    constants = collect_constants()
    schedule = [] if args.no_schedule else collect_schedule()
    markdown = render_markdown(constants, schedule)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Explicit LF: this file is committed, and platform-native CRLF would make every
        # regeneration look like a diff even when nothing changed.
        out.write_text(markdown, encoding="utf-8", newline="\n")
        print(f"wrote {out} ({len(constants)} constants, {len(schedule)} scheduled triggers)")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
