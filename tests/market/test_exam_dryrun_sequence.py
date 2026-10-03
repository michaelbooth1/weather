"""Exam dry run: the W2 production runbook, step for step, as real subprocesses on fixture data.

Every step runs ``python -P -B -m ...`` with the runbook's flags and
``PYTHONPATH=<worktree>\\src`` (docs/roadmap/agent-report-2026-10-111e-followup.md,
"Production runbook"). One test-only ``sitecustomize`` follows src on the path.
It sets the clock to 2026-10-15 01:00 Toronto, because the exam's dates are
hardcoded, and stands in for the enrolment commit (runbook C4) in the look's process
only. It also pins the look's commit-charge reading, which belongs to the host and not to
the tree (the workstation refused at 96.5%; Linux CI can exceed 100% under overcommit). It patches module attributes after import and never changes a source byte, so
module hashes and ``source_hashes()`` stay those of this tree. No production path,
network, credential or Scheduler is touched.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from maker_core.replay.authorization import LOG_HEADER, SIGNED_BINDINGS
from maker_core.replay.bundle import timestamp
from maker_core.replay.pull_efficiency import opportunity_candidates
from tools.research.exam_dryrun_fixture import Shape, build

WORKTREE = Path(__file__).resolve().parents[2]
SRC = WORKTREE / "src"
NOW = datetime(2026, 10, 15, 5, tzinfo=timezone.utc)  # 01:00 Toronto on the scoring date.
V3 = "maker-replay-2026-10-15-v3"
SIGNED_AT = "2026-10-03T12:00:00Z"
RESEARCH = WORKTREE / "docs" / "research"
FROZEN = (("--frozen-protocol", "maker-replay-hurdles-preregistration-2026-09-27.md"),
          ("--execution-addendum", "maker-replay-execution-addendum-2026-09-27.md"),
          ("--clarification", "maker-replay-clarification-1-2026-09-27.md"),
          ("--clarification-2", "maker-replay-clarification-2-2026-09-29.md"),
          ("--clarification-3", "maker-replay-clarification-3-2026-10-01.md"))
EXPORT_LIMITS = ["--max-input-bytes", "17179869184", "--max-seconds", "11000", "--max-output-bytes", "2147483648"]
# The fast run: one city (Toronto). Dense calibration-date prints give the rehearsal enough
# distinct engine events that max_events x15 covers the panel's pull candidates (see dry_run).
FAST = Shape(cities=1, segments=4, minutes=1, calibration_trades_per_minute=320)

SHIM = '''"""Exam dry-run harness shim: fixed clock and fixture enrolment. Test subprocesses only."""
import importlib.abc
import os
import sys
from datetime import datetime

_NOW = datetime.fromisoformat(os.environ["EXAM_DRYRUN_NOW"])
_ENROL = os.environ.get("EXAM_DRYRUN_ENROL", "")
_COMMIT = os.environ.get("EXAM_DRYRUN_COMMIT_PERCENT")


def _patch(name, module):
    if name == "maker_core.replay.pack_cli":
        module._now = lambda: _NOW
    elif name == "maker_core.replay.authorization":
        module._utc_now = lambda: _NOW
    elif name == "maker_core.replay.ceilings" and _COMMIT:
        module.commit_percent = lambda: float(_COMMIT)
    elif name == "maker_core.replay.approved_registrations":
        for pair in filter(None, _ENROL.split(",")):
            key, owner = pair.split(":")
            module.APPROVED_REGISTRATIONS[key] = owner
    elif name == "weather.market.maker_replay_night":
        night, calibration = module.night, module.calibration
        module.night = lambda args, now=None: night(args, now=now or _NOW)
        module.calibration = lambda args, now=None: calibration(args, now=now or _NOW)


class _Finder(importlib.abc.MetaPathFinder):
    names = {"maker_core.replay.pack_cli", "maker_core.replay.authorization", "maker_core.replay.ceilings",
             "maker_core.replay.approved_registrations", "weather.market.maker_replay_night"}

    def find_spec(self, name, path, target=None):
        if name not in self.names:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                break
        else:
            return None
        execute = spec.loader.exec_module

        def exec_module(module):
            execute(module)
            _patch(name, module)
        spec.loader.exec_module = exec_module
        return spec


sys.meta_path.insert(0, _Finder())
'''


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


class Runbook:
    """Runs each step as its own -P -B process; every refusal is kept before the step fails."""

    def __init__(self, root):
        self.root = root
        shim = root / "shim"
        shim.mkdir()
        (shim / "sitecustomize.py").write_text(SHIM, encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "EXAM_DRYRUN_"))}
        self.env.update(PYTHONPATH=os.pathsep.join((str(SRC), str(shim))), EXAM_DRYRUN_NOW=NOW.isoformat(),
                        EXAM_DRYRUN_COMMIT_PERCENT="10.0", PYTHONIOENCODING="utf-8")
        self.refusals, self.seconds = [], {}

    def __call__(self, name, tokens, *, enrol=None, codes=(0,)):
        """Stdout of a step; a non-zero exit is kept as a refusal and fails unless ``codes`` admits it."""
        env = dict(self.env, EXAM_DRYRUN_ENROL=enrol or "")
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-P", "-B", *map(str, tokens)], cwd=self.root, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=4 * 3600)
        self.seconds[name] = round(time.monotonic() - started, 3)
        self.code = done.returncode
        if done.returncode:
            self.refusals.append(dict(step=name, code=done.returncode,
                                      stderr=done.stderr.strip()[-2000:], stdout=done.stdout.strip()[-2000:]))
        if done.returncode not in codes:
            pytest.fail(f"{name} exited {done.returncode}: {done.stderr.strip()[-2000:]}")
        return done.stdout

    def attempt_root(self, kind):
        root = self.root / "exam" / kind
        root.mkdir(parents=True)
        return root


def decision_log(path):
    """REVOKE v1 and APPROVE v3 rows exactly as the runbook's C1 writes them."""
    decision = dict(authorization_id=V3, owner="michaelbooth1",
                    protocol_sha256=SIGNED_BINDINGS[V3]["protocol_sha256"],
                    addendum_sha256=SIGNED_BINDINGS[V3]["addendum_sha256"],
                    clarification_sha256=SIGNED_BINDINGS[V3]["clarification_sha256"],
                    clarification_2_sha256=SIGNED_BINDINGS[V3]["clarification_2_sha256"],
                    clarification_3_sha256=SIGNED_BINDINGS[V3]["clarification_3_sha256"],
                    signed_at=SIGNED_AT, scoring_date="2026-10-15", expires_at="2026-11-01T04:00:00Z")
    source = json.dumps(decision, separators=(",", ":"))
    v1 = json.dumps(dict(authorization_id="maker-replay-2026-10-15-v1"), separators=(",", ":"))
    path.write_text("# FIXTURE decision log (exam dry run)\n\n" + LOG_HEADER + "\n| --- | --- | --- | --- | --- |\n"
                    f"| 2026-10-03 | REVOKE_MAKER_REPLAY | offline replay only | `{v1}` | — |\n"
                    f"| {SIGNED_AT[:10]} | APPROVE_MAKER_REPLAY | offline replay only | `{source}` | — |\n",
                    encoding="utf-8", newline="\n")
    return source


def day_metrics(receipt):
    bundle = receipt["bundle"]
    return dict(runtime_seconds=round(receipt["runtime_seconds"], 3), peak_memory_bytes=receipt["peak_memory_bytes"],
                bytes=bundle["bytes"], records=bundle["records"], input_bytes=receipt["input_bytes"],
                restart_events=len(receipt["restart_events"]), trade_clock_skew=bundle["trade_clock_skew"])


def check_receipt(receipt, module):
    assert receipt["status"] == "SEALED", receipt.get("reason")
    assert receipt["module_sha256"] == module
    skew = receipt["bundle"]["trade_clock_skew"]
    assert skew["leading_capture"] >= 1 and 0 < skew["max_us"] <= skew["bound_us"]
    return receipt.get("events_trimmed")


def dry_run(tmp_path, shape, summary, *, strict=True):
    """The runbook in order, filling ``summary`` as it goes.

    ``strict=False`` measures past a terminal refusal (a binding host limit or a refused look)
    instead of failing, so a production-scale run still reports every export; each such
    refusal stays in ``summary["refusals"]``.
    """
    started = time.monotonic()
    fixture = build(tmp_path / "fixture", shape)
    data, releases = fixture["data_root"], fixture["release_root"]
    step = Runbook(tmp_path)
    metrics = dict(calibration={}, rehearsal_panel={}, panel={})
    summary.update(fixture=dict(shape=fixture["shape"], cities=fixture["cities"],
                                build_seconds=round(time.monotonic() - started, 3)),
                   metrics=metrics, events_trimmed={}, step_seconds=step.seconds, refusals=step.refusals)
    trimmed = summary["events_trimmed"]
    cal_days, panel_days = fixture["calibration_days"], fixture["panel_days"]
    (tmp_path / "exam").mkdir()
    exam = tmp_path / "exam"
    log = tmp_path / "DECISION_LOG.md"
    owner = decision_log(log)
    docs = ["--decision-log", log] + [token for flag, name in FROZEN for token in (flag, RESEARCH / name)]

    # Session setup: the module-path probe, then the pinned exporter hash.
    probe = step("probe", ["-c", "import weather.market.maker_replay_night as n, maker_core.replay.ceilings as c, "
                           "maker_core.replay.approved_registrations as a; print(n.__file__); print(c.__file__); "
                           "print(a.__file__)"]).splitlines()
    assert len(probe) == 3 and all(Path(p).resolve().is_relative_to(SRC.resolve()) for p in probe), probe
    module = json.loads(step("module_hash", ["-m", "weather.market.maker_plugin.replay_export", "module-hash"]))
    module = summary["module_sha256"] = module["module_sha256"]

    # A. Calibration and rehearsal-panel export.
    cal_root, reh_root = step.attempt_root("calibration"), step.attempt_root("rehearsal-panel")
    for day in cal_days:
        step("calibration_" + day, ["-m", "weather.market.maker_plugin.replay_export", "calibration", "--day", day,
             "--data-root", data, "--out", cal_root, "--expected-module-sha256", module, *EXPORT_LIMITS])
    for day in cal_days:
        step("rehearsal_panel_" + day, ["-m", "weather.market.maker_plugin.replay_export", "night", "--day", day,
             "--data-root", data, "--release-root", releases, "--out", reh_root,
             "--expected-module-sha256", module, *EXPORT_LIMITS])
    for kind, root in (("calibration", cal_root), ("rehearsal_panel", reh_root)):
        for day in cal_days:
            receipt = read(root / day / "receipt.json")
            trimmed[f"{kind}/{day}"] = check_receipt(receipt, module)
            metrics[kind][day] = day_metrics(receipt)

    # B. Quote markets, hazard calibration, ceiling rehearsal; limits sized from the calibration receipts.
    sized = [read(cal_root / day / "receipt.json")["bundle"] for day in cal_days]
    limits = ["--max-input-bytes", sum(b["bytes"] for b in sized), "--max-records", sum(b["records"] for b in sized),
              "--max-seconds", "2700", "--max-output-bytes", "8388608"]
    cal_bundles = [token for day in cal_days for token in ("--calibration-bundle", cal_root / day / "bundle")]
    step("quote_markets", ["-m", "maker_core.replay", "quote_markets", *cal_bundles,
                           "--out", exam / "quote-markets.json", *limits])
    step("calibrate", ["-m", "maker_core.replay", "calibrate_hazard",
                       *[t for day in cal_days for t in ("--bundle", cal_root / day / "bundle")],
                       "--quote-markets", exam / "quote-markets.json", "--out", exam / "calibration.json", *limits])
    calibration = read(exam / "calibration.json")
    assert calibration["global_fallback"] is None
    assert "binding_status" not in calibration
    for day in cal_days:  # One fresh process per date.
        step("rehearse_" + day, ["-m", "maker_core.replay", "rehearse", "--bundle", reh_root / day / "bundle",
                                 "--calibration", exam / "calibration.json", "--out", exam / f"rehearsal-{day}.json"])
    derived = step("derive_ceilings", ["-m", "maker_core.replay", "derive_ceilings",
                   *[t for day in cal_days for t in ("--rehearsal", exam / f"rehearsal-{day}.json")],
                   "--out", exam / "ceiling-measurement.json"], codes=(0,) if strict else (0, 3))
    measurement = read(exam / "ceiling-measurement.json")
    assert measurement["calibration_sha256"] == sha256(exam / "calibration.json")
    summary.update(rehearsal=measurement["per_date"], derived=measurement["derived"])
    executable = "executable_on_host=True" in derived

    # C1. Authorization: the exact Source JSON of the APPROVE row, UTF-8 without BOM.
    (exam / "owner-decision.json").write_bytes(owner.encode("utf-8"))
    # C2. Panel completeness: fifteen days into one new attempt root.
    panel_root = step.attempt_root("panel")
    for day in panel_days:
        step("panel_" + day, ["-m", "weather.market.maker_plugin.replay_export", "night", "--day", day,
             "--data-root", data, "--release-root", releases, "--out", panel_root,
             "--expected-module-sha256", module, *EXPORT_LIMITS])
    for day in panel_days:
        receipt = read(panel_root / day / "receipt.json")
        trimmed[f"panel/{day}"] = check_receipt(receipt, module)
        metrics["panel"][day] = day_metrics(receipt)
    summary["bound_inputs"] = dict(
        input_bytes=sum(m["bytes"] for m in metrics["panel"].values()) + sum(b["bytes"] for b in sized),
        records=sum(m["records"] for m in metrics["panel"].values()) + sum(b["records"] for b in sized))

    # C3. Universe, build, verify.
    panel = [t for day in panel_days for t in ("--bundle", panel_root / day / "bundle")]
    bind = [*cal_bundles, "--calibration", exam / "calibration.json", "--universe", exam / "universe.json",
            "--quote-markets", exam / "quote-markets.json", "--ceiling-measurement", exam / "ceiling-measurement.json",
            *docs]
    (exam / "manifest").mkdir()
    step("universe", ["-m", "weather.market.maker_plugin.replay_export", "universe", *panel,
                      "--out", exam / "universe.json"])
    built = step("manifest_build", ["-m", "maker_core.replay", "manifest", "build", *panel, *bind,
                                    "--owner-decision", exam / "owner-decision.json",
                                    "--out", exam / "manifest" / "manifest.json"], codes=(0,) if executable else (2,))
    if not executable:
        return summary  # Build refuses not_executable_on_host as signed; the exam line ends here.
    key = summary["manifest_sha256"] = sha256(exam / "manifest" / "manifest.json")
    assert f"manifest_sha256={key}; VERIFIED_PREFLIGHT_ONLY" in built
    verified = step("manifest_verify", ["-m", "maker_core.replay", "manifest", "verify", *panel, *bind,
                                        "--manifest", exam / "manifest" / "manifest.json", "--manifest-sha256", key])
    assert "VERIFIED_PREFLIGHT_ONLY" in verified

    # The look's engine_preflight refuses pull_opportunity_cap unless the panel's pull candidates
    # (minute starts in each condition's active windows) fit replay_config.max_events, which the
    # rule derives from rehearsed engine events. Recorded here so production can check it from
    # its own manifest before the look.
    manifest = read(exam / "manifest" / "manifest.json")
    windows = {}
    for w in manifest["active_intervals"]:
        windows.setdefault(w["condition_id"], []).append((timestamp(w["start"]), timestamp(w["end"])))
    summary.update(ceilings=manifest["ceilings"], pull=dict(
        candidates=opportunity_candidates(windows), max_events=manifest["replay_config"]["max_events"],
        rehearsed_engine_events={d: m["engine_events"] for d, m in measurement["per_date"].items()}))

    # C6. The look, enrolled for this process only (runbook C4 is a reviewed commit in production).
    look = exam / "look"
    step("look", ["-m", "maker_core.replay", "run", "--compare", "--pre-registration", exam / "manifest" / "manifest.json",
                  "--pre-registration-sha256", key, "--out", look, *panel, *bind], enrol=f"{key}:michaelbooth1",
         codes=(0,) if strict else (0, 2))
    attempts = exam / "manifest" / "attempts"
    summary["attempts"] = sorted(p.name for p in attempts.glob("*.json"))
    if step.code:
        return summary  # A refusal before reservation: recorded, not consumed.
    assert not list(attempts.glob("*.refusal-*.json"))
    completed = read(attempts / f"{V3}.completed.json")
    assert completed["status"] == "COMPLETED" and completed["manifest_sha256"] == key
    assert completed["registered_decision"]["status"]
    summary.update(registered_decision=completed["registered_decision"], look_seconds=step.seconds["look"],
                   total_seconds=round(time.monotonic() - started, 3))
    return summary


def publish(summary):
    report = os.environ.get("EXAM_DRYRUN_REPORT")
    if report:
        Path(report).write_text(json.dumps(summary, indent=1, sort_keys=True, default=str), encoding="utf-8")
    print("EXAM_DRYRUN_SUMMARY", json.dumps(summary, sort_keys=True, default=str))


def test_w2_runbook_sequence_passes_end_to_end(tmp_path):
    summary = {}
    try:
        dry_run(tmp_path, FAST, summary)
    finally:
        publish(summary)
    assert summary["registered_decision"]["status"] and not summary["refusals"]
    # Every quote-panel day carries the fixture's restart and stays inside the venue-clock bound.
    assert all(m["restart_events"] == 1 for m in summary["metrics"]["panel"].values())
    ceilings = summary["ceilings"]
    assert summary["bound_inputs"]["input_bytes"] <= ceilings["max_input_bytes"]
    assert summary["bound_inputs"]["records"] <= ceilings["max_records"]
    assert summary["pull"]["candidates"] <= summary["pull"]["max_events"]


@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("EXAM_DRYRUN_SLOW") != "1", reason="production-scale run; set EXAM_DRYRUN_SLOW=1")
def test_w2_runbook_sequence_at_twelve_cities_and_150k_reward_rows(tmp_path):
    """Generator defaults with ~150k reward rows a day.

    Calibration dates carry enough prints that rehearsed events x15 cover the panel's pull
    candidates; whether the rule then fits the host is the measurement, so a binding limit
    or a refused look is reported rather than failed.
    """
    summary = {}
    try:
        dry_run(tmp_path, Shape(reward_rows=150_000, calibration_trades_per_minute=125), summary, strict=False)
    finally:
        publish(summary)
    assert len(summary["metrics"]["panel"]) == 15
