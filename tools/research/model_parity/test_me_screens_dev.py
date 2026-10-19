"""Model-edge week-1 development screens on real dev data (dates <= 2026-09-29). NOT a unit test.

Skipped unless ME_SCREENS_DEV=1. Runs only through the workstation heavy wrapper::

    $env:ME_SCREENS_DEV = "1"; $env:ME_SCREENS_PHASE = "dryrun" | "score"
    scripts\\ops\\workstation_heavy.ps1 -Kind pytest -Queue -RepoRoot <wt> -PythonPath <venv python>
        -ArgumentsBase64 <b64 of ["-m","pytest","-q","-p","no:cacheprovider","--basetemp=C:\\t\\mescr",
                                   "tools/research/model_parity/test_me_screens_dev.py"]>

Phase ``dryrun`` is outcome-free (H2). Phase ``score`` needs the pre-declared blocks committed first
(docs/research/model-edge-screens-2026-10-19.md section 2; ME_SCREENS_DECLARED_SHA must be the commit
holding them) and writes C:\\swarm\\out\\mescr\\score_<stamp>\\.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ME_SCREENS_DEV") != "1",
                                reason="development screens run only under the heavy wrapper")

LAYOUT = Path(os.environ.get("HARNESS_V3_LAYOUT", r"C:\swarm\v3layout"))
OUT = Path(os.environ.get("ME_SCREENS_OUT", r"C:\swarm\out\mescr"))
REPO = Path(__file__).resolve().parents[3]


def _head():
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()


def test_me_screens_phase():
    phase = os.environ.get("ME_SCREENS_PHASE", "dryrun")
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = OUT / f"{phase}_{stamp}"
    out.mkdir(parents=True)
    if phase == "dryrun":
        import sys
        from tools.research.model_parity import me_screens_dryrun
        rec = me_screens_dryrun.run(LAYOUT)
        rec["git_head"] = _head()
        loaded = sorted(m for m in sys.modules if m.startswith("tools.research.model_parity."))
        rec["model_parity_modules_loaded"] = loaded
        (out / "dryrun.json").write_text(json.dumps(rec, indent=1, default=float), encoding="utf-8")
        assert not any(m.endswith(("v3_outcomes", "v3_score", ".harness")) for m in loaded)
        return
    if phase == "score":
        from tools.research.model_parity import me_screens_score
        rec = me_screens_score.run(LAYOUT, out, declared_commit=os.environ["ME_SCREENS_DECLARED_SHA"])
        rec["git_head"] = _head()
        (out / "screens.json").write_text(json.dumps(rec, indent=1, default=float), encoding="utf-8")
        assert not rec["leakage_suspects"]
        return
    raise AssertionError(f"unknown phase {phase!r}")
