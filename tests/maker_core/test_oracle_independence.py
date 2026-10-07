"""Tier I oracle import ratchet over the oracle-reserved paths (D-shadow-gate-spec-v3 §6.3 "Independence (enforced)").

Reserved paths: ``src/maker_core/shadow/gate/oracle.py`` and ``src/maker_core/shadow/gate/oracle/``. The oracle may
import only the standard library (``decimal`` included), ``maker_core.contracts`` and, from
``maker_core.quoting.policy``, only ``decide``, ``DecisionInputs``, ``Portfolio``, ``ExposureLimit``, ``QuoteLeg``
and the profile constants. ``maker_core.replay.*`` (v2 kernel, engine, lockstep, fill model, ``_fill89a``,
payloads), ``maker_core.shadow.{live_kernel,contract,runner,paper,tape}`` and ``weather.*`` are forbidden, as is any
dynamic import. The oracle does not exist yet (it waits for OD18/OD19/OD20); this ratchet is in place first so its
first commit is checked. The cross-validation half of this file (v3 §6.3) is the oracle unit's, not added here.
"""
import ast
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
POLICY_NAMES = frozenset({"decide", "DecisionInputs", "Portfolio", "ExposureLimit", "QuoteLeg",
                          "informed_v0", "blind_re1"})
FORBIDDEN_PREFIXES = ("maker_core.replay", "maker_core.shadow.live_kernel", "maker_core.shadow.contract",
                      "maker_core.shadow.runner", "maker_core.shadow.paper", "maker_core.shadow.tape", "weather")


def reserved_files(src):
    gate = src / "maker_core" / "shadow" / "gate"
    files = [gate / "oracle.py"] if (gate / "oracle.py").is_file() else []
    if (gate / "oracle").is_dir():
        files += sorted((gate / "oracle").rglob("*.py"))
    return files


def violations(path, src):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = path.relative_to(src).with_suffix("").parts
    package = ".".join(rel[:-1]) if rel[-1] != "__init__" else ".".join(rel[:-1])
    found = []

    def check(module, names):
        root = module.split(".")[0]
        if module.startswith(FORBIDDEN_PREFIXES):
            found.append(f"forbidden:{module}")
        elif root in sys.stdlib_module_names or root == "__future__":
            return
        elif module == "maker_core.contracts" or module.startswith("maker_core.contracts."):
            return
        elif module.startswith("maker_core.shadow.gate.oracle"):
            return
        elif module == "maker_core.quoting.policy" and names is not None and set(names) <= POLICY_NAMES:
            return
        else:
            found.append(f"not_allowed:{module}:{','.join(names or ['*module*'])}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check(alias.name, None)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[:len(package.split(".")) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module
            if module in ("maker_core", "maker_core.shadow", "maker_core.quoting", "maker_core.shadow.gate"):
                for alias in node.names:  # ``from maker_core.quoting import policy`` imports the whole module
                    check(f"{module}.{alias.name}", None)
            else:
                check(module, [alias.name for alias in node.names])
        elif isinstance(node, ast.Call):
            label = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if label in {"import_module", "__import__", "exec", "eval"}:
                found.append(f"dynamic:{label}")
    return found


def test_oracle_reserved_paths_import_only_the_allowed_set():
    offenders = {str(p.relative_to(REPO)): violations(p, SRC) for p in reserved_files(SRC)}
    assert {k: v for k, v in offenders.items() if v} == {}


def _oracle(tmp_path, text, *, package=False):
    gate = tmp_path / "maker_core" / "shadow" / "gate"
    path = gate / "oracle" / "core.py" if package else gate / "oracle.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return tmp_path, path


def test_clean_oracle_passes(tmp_path):
    src, path = _oracle(tmp_path, "from decimal import Decimal\nimport hashlib\n"
                                  "from maker_core.contracts import OutcomeView\n"
                                  "from maker_core.quoting.policy import decide, DecisionInputs, informed_v0\n")
    assert reserved_files(src) == [path] and violations(path, src) == []


@pytest.mark.parametrize("line", [
    "from maker_core.replay.v2.kernel import Kernel\n",
    "from maker_core.replay.v2 import kernel\n",
    "import maker_core.replay.payloads\n",
    "from maker_core.replay._fill89a import filled_size\n",
    "from maker_core.shadow.live_kernel import LiveKernel\n",
    "from maker_core.shadow import tape\n",
    "from maker_core.shadow.runner import ShadowRunner\n",
    "from weather.market.maker_plugin import fair_value\n",
    "from maker_core.quoting.policy import compose_book_like_helper\n",
    "from maker_core.quoting import policy\n",
    "import maker_core.quoting.policy\n",
    "import importlib; importlib.import_module('maker_core.replay.v2.kernel')\n",
    "__import__('maker_core.replay')\n",
])
@pytest.mark.parametrize("package", [False, True])
def test_stray_kernel_or_adapter_import_is_caught(tmp_path, line, package):
    src, path = _oracle(tmp_path, line, package=package)
    assert violations(path, src) != []
