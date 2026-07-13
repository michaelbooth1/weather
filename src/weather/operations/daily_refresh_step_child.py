"""Internal entry point for one bounded daily-refresh settlement step."""

from __future__ import annotations

import argparse
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from weather.io import write_json_atomic
from weather.operations.daily_refresh_resources import (
    STAGE_A_ISOLATED_STEPS,
    json_safe,
)
from weather.operations.daily_refresh_steps import DEFAULT_RUNNERS
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("daily_refresh_step_child")


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _runner_for_step(step_name):
    runners = dict(DEFAULT_RUNNERS)
    if step_name not in STAGE_A_ISOLATED_STEPS or step_name not in runners:
        raise ValueError(f"step is not an isolated Stage-A owner: {step_name}")
    return runners[step_name]


def run_child(step_name, args_json, result_json):
    started = utc_iso()
    output = {
        "schema_version": SCHEMA_VERSION,
        "step": step_name,
        "pid": os.getpid(),
        "started_at_utc": started,
        "finished_at_utc": None,
        "status": "running",
    }
    result_path = Path(result_json)
    try:
        manifest = json.loads(Path(args_json).read_text(encoding="utf-8"))
        if manifest.get("step") != step_name:
            raise ValueError(
                f"step argument mismatch: expected {step_name}, manifest has {manifest.get('step')}"
            )
        args = SimpleNamespace(**(manifest.get("args") or {}))
        # The parent owns process isolation. A child must never recursively
        # create another daily-refresh step container.
        args.heavy_step_subprocess = False
        result = _runner_for_step(step_name)(args)
        output.update({"status": "ok", "result": json_safe(result)})
        return_code = 0
    except BaseException as exc:  # terminal evidence must survive Ctrl-C/native wrappers
        output.update({
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        return_code = 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        output["finished_at_utc"] = utc_iso()
        write_json_atomic(result_path, output, trailing_newline=True)
    return return_code


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", required=True, choices=sorted(STAGE_A_ISOLATED_STEPS))
    parser.add_argument("--args-json", required=True)
    parser.add_argument("--result-json", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_child(args.step, args.args_json, args.result_json)


if __name__ == "__main__":
    raise SystemExit(main())
