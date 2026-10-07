"""Gate import ratchets (static, AST-only; nothing is imported).

- D-shadow-gate-spec-v3.1 §6.7 (M-U): the **transitive** import closure of ``maker_core.shadow.gate.*`` and
  ``weather.market.maker_shadow_gate*`` contains no settlement, ledger or scoring reader: no module whose dotted
  name contains ``settlement``, ``fair_value_score`` or ``scor`` under ``weather.model``/``weather.market``, the
  settlement-ledger loaders of ``weather.market.maker_plugin_sources``, or a module on ``DENY``. A denied module
  reached through B0w's plugin imports must be split out, never allowlisted (v3.1 §6.7). Mutant MU3.
- v3 §6.2: the ``maker_core.shadow.gate`` package never imports ``weather.*``; B0w imports only the listed plugin
  modules, ``detect_observation_triggers`` and ``maker_core.contracts`` (plus the gate-infrastructure modules named
  in its docstring) and **never** ``weather.market.maker_shadow``.
"""
import ast
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
DENY = frozenset({
    "weather.market.maker_plugin.settlement",
    "weather.market.maker_plugin.fair_value_score",
    "weather.market.maker_plugin_sources",  # settlement-ledger loaders (v3.1 §6.7); split before use
})
B0W = "weather.market.maker_shadow_gate_b0"
B0W_ALLOWED = frozenset({
    "maker_core.contracts", "maker_core.evidence.journal", "maker_core.shadow.b0w_result", "maker_core.shadow.secrets",
    "weather.market.maker_plugin.universe", "weather.market.maker_plugin.fair_value",
    "weather.market.maker_plugin.clock", "weather.market.maker_plugin.exposure", "weather.market.maker_plugin.inputs",
    "weather.market.maker_plugin.nbp", "weather.operations.observation_trigger",
})
B0W_PARENT_PACKAGES = frozenset({"maker_core", "maker_core.shadow", "maker_core.evidence", "weather",
                                 "weather.market", "weather.market.maker_plugin", "weather.operations"})


def module_file(src, name):
    base = src.joinpath(*name.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def module_name(src, path):
    parts = path.relative_to(src).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def direct_imports(src, name, *, names=False):
    """Absolute module names imported by ``name``'s source (relative imports resolved). With ``names=True`` the
    imported attribute names are returned as well, as ``(module, attr)`` pairs. Dynamic imports raise."""
    path = module_file(src, name)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update((alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[:len(package.split(".")) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module
            for alias in node.names:
                found.add((module, alias.name))
        elif isinstance(node, ast.Call):
            func = node.func
            label = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if label in {"import_module", "__import__"}:
                raise AssertionError(f"dynamic import in {name}")
    if names:
        return found
    modules = set()
    for module, attr in found:
        modules.add(module)
        if attr and attr != "*" and module_file(src, f"{module}.{attr}"):
            modules.add(f"{module}.{attr}")
    return modules


def with_parents(name):
    parts = name.split(".")
    return {".".join(parts[:i]) for i in range(1, len(parts) + 1)}


def closure(src, roots):
    seen, todo = set(), list(roots)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        if module_file(src, name) is None:
            continue  # stdlib or third party
        for module in direct_imports(src, name):
            for candidate in with_parents(module):
                if module_file(src, candidate) is not None and candidate not in seen:
                    todo.append(candidate)
    return {name for name in seen if module_file(src, name) is not None}


def gate_roots(src):
    roots = set()
    gate = src / "maker_core" / "shadow" / "gate"
    if gate.is_dir():
        roots.update(module_name(src, p) for p in gate.rglob("*.py"))
    roots.update(module_name(src, p) for p in (src / "weather" / "market").glob("maker_shadow_gate*.py"))
    return roots


def denied(name):
    if name in DENY:
        return True
    if name.startswith(("weather.model.", "weather.market.")):
        return any(word in name for word in ("settlement", "fair_value_score", "scor"))
    return False


def closure_violations(src):
    roots = gate_roots(src)
    reached = closure(src, roots)
    bad = sorted(name for name in reached if denied(name))
    core = closure(src, {r for r in roots if r.startswith("maker_core.")})
    bad += sorted(f"core_gate_imports:{name}" for name in core if name.startswith("weather"))
    return roots, bad


def b0w_violations(src):
    bad = []
    for module, attr in direct_imports(src, B0W, names=True):
        root = module.split(".")[0]
        if root in sys.stdlib_module_names or root == "__future__":
            continue
        if module == "weather.operations.observation_trigger" and attr != "detect_observation_triggers":
            bad.append(f"{module}.{attr}")
        elif module.startswith("weather.market.maker_shadow") and module != B0W:
            bad.append(module)
        elif module not in B0W_ALLOWED and module not in B0W_PARENT_PACKAGES:
            bad.append(module)
        elif module in B0W_PARENT_PACKAGES and attr and f"{module}.{attr}" not in B0W_ALLOWED:
            bad.append(f"{module}.{attr}")
    return sorted(bad)


def test_gate_closure_has_no_settlement_or_scoring_reader():
    roots, bad = closure_violations(SRC)
    assert B0W in roots, "ratchet is vacuous: no gate module found"
    assert bad == []


def test_b0w_direct_imports_are_the_allowed_set():
    assert b0w_violations(SRC) == []


# -- mutants on a synthetic source tree ------------------------------------------------------------------------------
def _tree(tmp_path, files):
    for name, text in files.items():
        path = tmp_path.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for package in ("maker_core", "maker_core/shadow", "maker_core/shadow/gate", "weather", "weather/market",
                    "weather/market/maker_plugin", "weather/model"):
        init = tmp_path.joinpath(*package.split("/"), "__init__.py")
        init.parent.mkdir(parents=True, exist_ok=True)
        init.touch()
    return tmp_path


def test_mu3_transitive_settlement_loader_is_caught(tmp_path):
    """MU3: a gate diagnostic imports a settlement loader transitively (two hops)."""
    src = _tree(tmp_path, {
        "maker_core/shadow/gate/diag.py": "from . import helper\n",
        "maker_core/shadow/gate/helper.py": "import json\n",
        "weather/market/maker_shadow_gate_b0.py": "from weather.market.maker_plugin import fair_value\n",
        "weather/market/maker_plugin/fair_value.py": "from weather.market.maker_plugin.settlement import load\n",
        "weather/market/maker_plugin/settlement.py": "def load(): pass\n",
    })
    _, bad = closure_violations(src)
    assert "weather.market.maker_plugin.settlement" in bad


@pytest.mark.parametrize("module", ["weather.model.settlement_ledger", "weather.market.fair_value_score",
                                    "weather.market.maker_scoring"])
def test_denied_name_rules(module):
    assert denied(module)
    assert not denied("weather.market.maker_plugin.fair_value") and not denied("maker_core.shadow.score")


def test_core_gate_importing_weather_is_caught(tmp_path):
    src = _tree(tmp_path, {"maker_core/shadow/gate/b0.py": "from weather.market import maker_plugin\n",
                           "weather/market/maker_shadow_gate_b0.py": ""})
    assert any(v.startswith("core_gate_imports:weather") for v in closure_violations(src)[1])


@pytest.mark.parametrize("line", ["from weather.market import maker_shadow\n",
                                  "from weather.market.maker_shadow import discover\n",
                                  "from weather.operations.observation_trigger import main\n",
                                  "from maker_core.replay.v2 import kernel\n",
                                  "import importlib; importlib.import_module('weather.market.maker_shadow')\n"])
def test_b0w_forbidden_import_mutants_are_caught(tmp_path, line):
    src = _tree(tmp_path, {"weather/market/maker_shadow_gate_b0.py": line,
                           "weather/market/maker_shadow.py": "", "weather/operations/observation_trigger.py": "",
                           "weather/operations/__init__.py": ""})
    if "importlib" in line:
        with pytest.raises(AssertionError, match="dynamic import"):
            b0w_violations(src)
    else:
        assert b0w_violations(src) != []
