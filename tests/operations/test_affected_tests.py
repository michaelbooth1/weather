import json
import subprocess

import pytest

from weather.operations import affected_tests as at


def select(files, changed):
    return at.select(at.build_graph(at.dict_tree(files)), changed)


BASE = {
    "src/weather/__init__.py": "",
    "src/weather/core/__init__.py": "",
    "src/weather/core/leaf.py": "VALUE = 1\n",
    "src/weather/core/middle.py": "from weather.core.leaf import VALUE\n",
    "src/weather/core/relative.py": "from .leaf import VALUE\n",
    "src/weather/other.py": "X = 2\n",
    "tests/__init__.py": "",
    "tests/core/test_leaf.py": "from weather.core.leaf import VALUE\n",
    "tests/core/test_middle.py": "from weather.core.middle import VALUE\n",
    "tests/core/test_relative.py": "import weather.core.relative\n",
    "tests/test_other.py": "from weather.other import X\n",
}


def test_direct_transitive_and_relative_importers_are_selected_with_a_reason():
    selection = select(BASE, ["src/weather/core/leaf.py"])

    assert set(selection.tests) == {"tests/core/test_leaf.py", "tests/core/test_middle.py", "tests/core/test_relative.py"}
    assert "imports weather.core.leaf" in selection.tests["tests/core/test_leaf.py"]
    assert "src/weather/core/middle.py imports weather.core.leaf" in selection.tests["tests/core/test_middle.py"]
    assert selection.full_suite is False


def test_a_package_init_change_reaches_every_importer_of_the_package():
    selection = select(BASE, ["src/weather/core/__init__.py"])

    assert {"tests/core/test_leaf.py", "tests/core/test_middle.py", "tests/core/test_relative.py"} <= set(selection.tests)
    assert "tests/test_other.py" not in selection.tests


def test_a_changed_test_is_selected_and_an_unrelated_test_is_not():
    selection = select(BASE, ["tests/core/test_leaf.py"])

    assert selection.tests == {"tests/core/test_leaf.py": "changed test file"}


@pytest.mark.parametrize("trigger", ["pytest.ini", "tests/maker/conftest.py", "requirements.txt", "pyproject.toml", "weather/__init__.py"])
def test_collection_and_environment_files_select_the_full_suite(trigger):
    selection = select(BASE, [trigger])

    assert selection.full_suite is True
    assert set(selection.tests) == {p for p in BASE if at.is_test_file(p)}


def test_present_ratchets_are_always_selected_and_absent_ones_are_skipped():
    files = dict(BASE, **{"tests/operations/test_import_architecture.py": "X = 1\n"})

    selection = select(files, ["docs/unrelated.md"])

    assert selection.tests == {"tests/operations/test_import_architecture.py": "always run: repository ratchet"}
    assert selection.unreferenced_changes == ["docs/unrelated.md"]
    assert "python -m weather.operations.agent_docs_audit" in selection.commands


def test_script_paths_built_from_path_chains_and_call_arguments_link_tests_to_scripts():
    files = dict(
        BASE,
        **{
            "scripts/ops/status.ps1": "& $python -m weather.core.leaf\n",
            "scripts/ops/admission.ps1": "$allow = @(\n    'weather.other'\n)\n",
            "tests/ops/test_status_script.py": 'from pathlib import Path\nSCRIPT = Path(__file__).parents[2] / "scripts" / "ops" / "status.ps1"\n',
            "tests/ops/test_admission_script.py": 'from weather.paths import repo_path\nSCRIPT = repo_path("scripts", "ops", "admission.ps1")\n',
        },
    )

    assert "tests/ops/test_status_script.py" in select(files, ["scripts/ops/status.ps1"]).tests
    assert "tests/ops/test_admission_script.py" in select(files, ["scripts/ops/admission.ps1"]).tests
    # The script runs the module, so a module change reaches the test that executes the script.
    reason = select(files, ["src/weather/core/leaf.py"]).tests["tests/ops/test_status_script.py"]
    assert "runs weather.core.leaf" in reason
    # An allowlist entry is a mention, and two data hops are not followed.
    assert "tests/ops/test_admission_script.py" not in select(files, ["src/weather/other.py"]).tests


def test_a_config_file_read_by_product_code_reaches_only_nearby_importers():
    files = {
        "config/markets.json": "{}",
        "src/weather/__init__.py": "",
        "src/weather/loader.py": 'from weather.paths import config_path\nPATH = config_path("markets.json")\n',
        "src/weather/hop1.py": "import weather.loader\n",
        "src/weather/hop2.py": "import weather.hop1\n",
        "tests/test_loader.py": "import weather.loader\n",
        "tests/test_hop1.py": "import weather.hop1\n",
        "tests/test_hop2.py": "import weather.hop2\n",
        "tests/test_reads_config.py": 'PATH = "config/markets.json"\n',
    }

    selection = select(files, ["config/markets.json"])

    assert {"tests/test_loader.py", "tests/test_hop1.py", "tests/test_reads_config.py"} <= set(selection.tests)
    assert "tests/test_hop2.py" not in selection.tests
    assert "references markets.json" in selection.tests["tests/test_loader.py"]


def test_a_function_level_import_in_product_code_has_a_bounded_reach():
    files = {
        "src/weather/__init__.py": "",
        "src/weather/heavy.py": "Y = 1\n",
        "src/weather/facade.py": "def run():\n    from weather.heavy import Y\n    return Y\n",
        "src/weather/hub1.py": "import weather.facade\n",
        "src/weather/hub2.py": "import weather.hub1\n",
        "tests/test_facade.py": "import weather.facade\n",
        "tests/test_far.py": "import weather.hub2\n",
        "tests/test_lazy_in_test.py": "def test_x():\n    from weather.hub2 import X\n",
    }

    selection = select(files, ["src/weather/heavy.py"])

    assert "tests/test_facade.py" in selection.tests
    assert "inside a function" in selection.tests["tests/test_facade.py"]
    assert "tests/test_far.py" not in selection.tests
    assert "tests/test_lazy_in_test.py" not in selection.tests


def test_module_name_strings_link_from_tests_but_not_from_product_registries():
    files = dict(
        BASE,
        **{
            "src/weather/registry.py": 'MODULES = ["weather.other"]\n',
            "tests/test_registry.py": "import weather.registry\n",
            "tests/test_patch.py": 'def test_x(monkeypatch):\n    monkeypatch.setattr("weather.other.X", 3)\n',
        },
    )

    selection = select(files, ["src/weather/other.py"])

    assert "names module weather.other" in selection.tests["tests/test_patch.py"]
    assert "tests/test_registry.py" not in selection.tests


def test_a_directory_reference_counts_only_when_the_test_names_no_file_inside_it():
    files = {
        "scripts/ops/a.ps1": "",
        "scripts/ops/b.ps1": "",
        "tests/test_inventory.py": 'from pathlib import Path\nOPS = Path("repo") / "scripts" / "ops"\nALL = sorted(OPS.glob("*.ps1"))\n',
        "tests/test_one_script.py": 'from pathlib import Path\nOPS = Path("repo") / "scripts" / "ops"\nA = OPS / "a.ps1"\n',
    }

    selection = select(files, ["scripts/ops/b.ps1"])

    assert "references directory scripts/ops" in selection.tests["tests/test_inventory.py"]
    assert "tests/test_one_script.py" not in selection.tests


def test_a_test_file_is_a_leaf_unless_another_test_imports_it():
    files = {
        "src/weather/__init__.py": "",
        "src/weather/lister.py": 'TESTS = ["tests/test_a.py"]\n',
        "tests/__init__.py": "",
        "tests/test_a.py": "def helper():\n    return 1\n",
        "tests/test_b.py": "from tests.test_a import helper\n",
        "tests/test_lister.py": "import weather.lister\n",
    }

    selection = select(files, ["tests/test_a.py"])

    assert set(selection.tests) == {"tests/test_a.py", "tests/test_b.py"}


def test_a_removed_module_still_selects_the_tests_that_import_it():
    files = {k: v for k, v in BASE.items() if k != "src/weather/core/leaf.py"}
    tree = at.dict_tree(files)
    graph = at.build_graph(tree)

    at.add_deleted_module_edges(graph, tree, ["src/weather/core/leaf.py"])
    selection = at.select(graph, ["src/weather/core/leaf.py"])

    assert "tests/core/test_leaf.py" in selection.tests
    assert "(removed)" in selection.tests["tests/core/test_leaf.py"]


def test_unparsable_files_are_reported_not_silently_dropped():
    files = dict(BASE, **{"tests/test_broken.py": "def oops(:\n"})

    selection = select(files, ["tests/test_broken.py"])

    assert "tests/test_broken.py" in selection.tests
    assert "tests/test_broken.py" in selection.parse_errors


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    for path, text in BASE.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "change")
    (root / "src/weather/core/leaf.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "mv", "src/weather/other.py", "src/weather/renamed.py")
    _git(root, "commit", "-q", "-am", "change")
    return root


def test_git_revisions_drive_the_cli_with_renames_on_both_sides(repo, capsys):
    assert at.changed_files(repo, "master", "change") == ["src/weather/core/leaf.py", "src/weather/other.py", "src/weather/renamed.py"]

    assert at.main(["--repo", str(repo), "--base", "master", "--head", "change", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    selected = {row["file"] for row in payload["tests"]}
    assert {"tests/core/test_leaf.py", "tests/test_other.py"} <= selected
    assert payload["full_suite"] is False

    (repo / "tests/core/test_new.py").write_text("import weather.renamed\n", encoding="utf-8")
    assert at.main(["--repo", str(repo), "--base", "master", "--worktree", "--format", "paths"]) == 0
    assert "tests/core/test_new.py" in capsys.readouterr().out.split()
