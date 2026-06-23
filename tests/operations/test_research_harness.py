import subprocess
import sys
from pathlib import Path

from tools.research import research_harness


REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_ROOT = REPO_ROOT / "tools" / "research"


def test_research_inventory_covers_every_script():
    scripts = set(research_harness.research_scripts(RESEARCH_ROOT))

    assert scripts == set(research_harness.SCRIPT_INVENTORY)
    assert research_harness.validate_inventory(RESEARCH_ROOT) == []


def test_research_scripts_do_not_use_pytest_discovery_names():
    offenders = sorted(path.name for path in RESEARCH_ROOT.glob("test_*.py"))

    assert offenders == []


def test_supported_and_fixture_research_scripts_have_network_free_smokes():
    results = research_harness.smoke_inventory(
        RESEARCH_ROOT,
        statuses=("supported", "fixture-only"),
    )

    assert {row["script"] for row in results} >= {"research_harness.py", "decompose_1314.py"}
    assert all(row["ok"] for row in results)


def test_retired_scripts_expose_help_and_do_not_run_live_diagnostics():
    retired_scripts = sorted(
        name
        for name, meta in research_harness.SCRIPT_INVENTORY.items()
        if meta["status"] == "retired"
    )
    for script in retired_scripts:
        result = subprocess.run(
            [sys.executable, str(RESEARCH_ROOT / script), "--help"],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        text = result.stdout + result.stderr

        assert result.returncode == 0
        assert "Retired" in text or "retired" in text


def test_broken_research_fragments_stay_retired():
    nyc = (RESEARCH_ROOT / "nyc_audit.py").read_text(encoding="utf-8")
    chicago = (RESEARCH_ROOT / "chicago_audit.py").read_text(encoding="utf-8")

    assert "def audit_chicago" not in nyc
    assert "bin_probability(dist" not in chicago
    assert research_harness.SCRIPT_INVENTORY["nyc_audit.py"]["status"] == "retired"
    assert research_harness.SCRIPT_INVENTORY["chicago_audit.py"]["status"] == "retired"


def test_dashboard_and_backfill_entrypoints_import_without_repo_path_mutation():
    code = "\n".join([
        "import py_compile",
        "import weather.collection.historical_backfill_plan",
        "import weather.collection.historical_backfill_runner",
        "import tools.backfill_all",
        "import app.views.history",
        "import app.views.market_making",
        "import app.views.operations",
        "import app.views.overview",
        "py_compile.compile('app/streamlit_app.py', doraise=True)",
    ])
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
