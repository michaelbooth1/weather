r"""MG-1 confirmation look: the registered entry point and the look receipt it writes (``mg1_look_receipt/1``).

Research only. Rule B-1 (sections 4, 9; VOID 5) reads MG-1's look receipt before anything else, and compares the
transfer instant against the instant the receipt records. This module is the only writer of that receipt, so no
field of it is typed by hand.

How a look uses it (``python -m weather.calibration.mg1_look``, registered by module name and source sha256 in
``weather.mg1_reserved_window.MG1_CONFIRMATION_ENTRY_POINTS``):

* ``Look(rule)`` checks that the MG-1 pre-registration bytes hash to the signed ``MG1_RULE_SHA256`` and that neither
  the start marker nor the receipt for that rule exists under ``data/mg1_look/`` (``weather.paths``).
* ``look.join_outcomes(loader, ...)`` is the only way the look obtains an outcome. Its first call refuses unless the
  running ``__main__`` is the registered entry point at its registered sha, then stamps ``looked_at_utc`` from the
  clock and writes ``started-<rule_sha256>.json`` (mode "x") BEFORE ``loader`` runs. A second look for the rule is
  refused from then on, even if the first one crashes.
* ``look.finish(result=..., dates=...)`` writes ``receipt-<rule_sha256>.json`` (mode "x"): the format accepted by
  master on 2026-10-26 (R3), plus ``body_sha256`` over the canonical JSON of every other field.
* ``receipt_problems(path)`` is what B-1's VOID 5 runs: the schema, the body sha, the signed rule, the entry point
  registered at the recorded sha, and the file's bytes equal to the receipt at the fixed path for its rule.

The fixed path is per checkout (``data/`` is local), so the looks run from the production root and the receipt and
markers are copied into the repository record the same day (B-1 clarification of 2026-10-26).

The MG-1 scoring itself (pre-registration section 4) is not part of this module yet: ``main`` refuses. Adding it
changes this file's sha256, which must then be re-registered in ``MG1_CONFIRMATION_ENTRY_POINTS`` by a reviewed edit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from weather import mg1_reserved_window as window
from weather import paths

MODULE = "weather.calibration.mg1_look"
RECEIPT_SCHEMA = "mg1_look_receipt/1"
STARTED_SCHEMA = "mg1_look_started/1"
# docs/research/morning-guidance-read-mg1-preregistration-2026-10-04.md at 02c410a5, signed 2026-10-04T16:10Z.
MG1_RULE_SHA256 = "b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665"
MG1_FILE = "src/weather/reporting/scorecards/free_source_candidates/mg1.py"
LOOK_ROOT = paths.data_path("mg1_look")
RECEIPT_FIELDS = ("schema", "entry_point", "mg1_rule_sha256", "window", "dates_scored", "looked_at_utc",
                  "completed_at_utc", "result", "mg1_py_sha256", "repo_commit", "host", "body_sha256")


class MG1LookRefused(RuntimeError):
    """The MG-1 look refused before reading anything, or its receipt cannot be written."""


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def module_sha256():
    return sha256_file(__file__)


def receipt_path(rule_sha256):
    return Path(LOOK_ROOT) / f"receipt-{rule_sha256}.json"


def started_path(rule_sha256):
    return Path(LOOK_ROOT) / f"started-{rule_sha256}.json"


def body_sha256(receipt):
    body = {key: value for key, value in receipt.items() if key != "body_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def head_commit(root=None):
    out = subprocess.run(["git", "-C", str(root or paths.REPO_ROOT), "rev-parse", "HEAD"], capture_output=True,
                         text=True, check=True)
    return out.stdout.strip()


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_x(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    except FileExistsError as exc:
        raise MG1LookRefused(f"{path} already exists: MG-1 has exactly one look") from exc


class Look:
    """One MG-1 look. Construct, obtain every outcome through ``join_outcomes``, then ``finish``."""

    def __init__(self, rule):
        self.rule_sha256 = sha256_file(rule)
        if self.rule_sha256 != MG1_RULE_SHA256:
            raise MG1LookRefused(f"the MG-1 rule {rule} hashes to {self.rule_sha256}, not the signed "
                                 f"{MG1_RULE_SHA256}")
        for path in (started_path(self.rule_sha256), receipt_path(self.rule_sha256)):
            if path.exists():
                raise MG1LookRefused(f"{path} already exists: MG-1 has exactly one look")
        self.looked_at_utc = None
        self.receipt = None

    def join_outcomes(self, loader, *args, **kwargs):
        """Return ``loader(*args, **kwargs)``; the first call stamps ``looked_at_utc`` before ``loader`` runs."""
        if self.receipt is not None:
            raise MG1LookRefused("the look has finished; no outcome is read after its receipt")
        if self.looked_at_utc is None:
            entry = window.registered_confirmation_entry()
            if entry != MODULE:
                raise MG1LookRefused(f"the running entry point {entry!r} is not the registered MG-1 look {MODULE}")
            stamped = _utc_now()
            _write_x(started_path(self.rule_sha256), {"schema": STARTED_SCHEMA, "mg1_rule_sha256": self.rule_sha256,
                                                      "looked_at_utc": stamped, "entry_sha256": module_sha256()})
            self.looked_at_utc = stamped
        return loader(*args, **kwargs)

    def finish(self, *, result, dates, root=None):
        """Write the receipt (mode "x") at the fixed path for the rule and return its path."""
        if self.looked_at_utc is None:
            raise MG1LookRefused("no outcome was joined through join_outcomes: there is no look to record")
        if self.receipt is not None:
            raise MG1LookRefused("the look receipt is already written")
        days = sorted({date.fromisoformat(str(d)).isoformat() for d in dates})
        if not days:
            raise MG1LookRefused("the look scored no date")
        start, last = window.window()
        root = Path(root or paths.REPO_ROOT)
        receipt = {"schema": RECEIPT_SCHEMA,
                   "entry_point": {"module": MODULE, "source_sha256": module_sha256()},
                   "mg1_rule_sha256": self.rule_sha256,
                   "window": {"d0": start.isoformat(), "last": last.isoformat() if last else None},
                   "dates_scored": {"count": len(days), "first": days[0], "last": days[-1]},
                   "looked_at_utc": self.looked_at_utc, "completed_at_utc": _utc_now(),
                   "result": {"path": str(Path(result).resolve()), "sha256": sha256_file(result)},
                   "mg1_py_sha256": sha256_file(root / MG1_FILE), "repo_commit": head_commit(root),
                   "host": socket.gethostname()}
        receipt["body_sha256"] = body_sha256(receipt)
        path = receipt_path(self.rule_sha256)
        _write_x(path, receipt)
        self.receipt = receipt
        return path


def receipt_problems(path):
    """What B-1's VOID 5 checks about a receipt before comparing instants; ``[]`` when it is a written receipt."""
    path = Path(path) if path else None
    if path is None or not path.is_file():
        return [f"MG-1 look receipt {path} does not exist"]
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"MG-1 look receipt {path} is unreadable: {exc}"]
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        return [f"MG-1 look receipt schema is not {RECEIPT_SCHEMA}"]
    problems = []
    missing = [key for key in RECEIPT_FIELDS if key not in receipt]
    if missing:
        problems.append(f"MG-1 look receipt lacks {missing}")
    if receipt.get("body_sha256") != body_sha256(receipt):
        problems.append("MG-1 look receipt body_sha256 does not match its fields (edited by hand)")
    if receipt.get("mg1_rule_sha256") != MG1_RULE_SHA256:
        problems.append("MG-1 look receipt does not name the signed MG-1 rule")
    entry = receipt.get("entry_point") or {}
    registered = window.MG1_CONFIRMATION_ENTRY_POINTS.get(entry.get("module"))
    if entry.get("module") != MODULE or not registered or registered != entry.get("source_sha256"):
        problems.append("MG-1 look receipt was not written by the registered entry point at its registered sha")
    fixed = receipt_path(MG1_RULE_SHA256)
    if not fixed.is_file() or sha256_file(fixed) != sha256_file(path):
        problems.append(f"MG-1 look receipt bytes differ from the written receipt at {fixed}")
    return problems


def build_parser():
    parser = argparse.ArgumentParser(prog=f"python -m {MODULE}", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-receipt", help="run B-1 VOID 5's receipt checks on a receipt (reads no outcome)")
    check.add_argument("--receipt", required=True)
    sub.add_parser("run", help="the MG-1 look (refuses: the MG-1 scoring is not built into the entry point yet)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "check-receipt":
        problems = receipt_problems(args.receipt)
        print(json.dumps({"receipt": args.receipt, "problems": problems}, indent=1))
        return 1 if problems else 0
    print("refused: the MG-1 scoring (pre-registration section 4) is not built into this entry point yet",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
