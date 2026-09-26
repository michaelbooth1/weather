"""Static, tracked-file-only inventory for the repository health ratchets."""
from __future__ import annotations

import ast
from collections import Counter
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

MODULE_LIMIT = 2_000
FILE_LIMIT = 1024 * 1024
ROADMAP_DATA_LIMIT = 250_000
ALLOWANCE_SEED_SHA = "2db5220bc12dc231ef1a42ab2f2ebff11ed5cf69"
BASELINE_PATH = "tests/fixtures/repo_health_baseline.json"
RETIRED = re.compile(r"\b(?:taker_\w+|mm_paper\w*|market_making_\w+|polymarket_us\w*|streak\w*|soak\w*)\b", re.I)
MODULE_TOKEN = re.compile(r"\b(?:weather|maker_core|app|tools)(?:\.[A-Za-z_]\w*)+\b")
DATA_EXTENSIONS = {".json", ".jsonl", ".csv", ".tsv", ".parquet", ".zip", ".gz"}
IMPORT_DISTRIBUTIONS = {
    "sklearn": "scikit-learn", "dotenv": "python-dotenv", "netCDF4": "netcdf4",
    "websocket": "websocket-client", "polymarket": "polymarket-client",
    "PIL": "pillow", "mpl_toolkits": "matplotlib", "yaml": "pyyaml",
    "eth_account": "eth-account",
}


def tracked_paths(root):
    return subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().strip("\0").split("\0")


def module_name(path):
    name = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


def imported_modules(tree, package):
    result = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                try:
                    name = importlib.util.resolve_name("." * node.level + name, package)
                except (ImportError, ValueError):
                    continue
            result.add(name)
            result.update(name + "." + alias.name for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            if ((isinstance(node.func, ast.Name) and node.func.id in {"__import__", "import_module"})
                    or isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"):
                result.add(node.args[0].value)
    return result


def c_names(tree):
    names = set()
    for node in ast.walk(tree):
        value = (node.id if isinstance(node, ast.Name) else node.arg if isinstance(node, ast.arg)
                 else node.attr if isinstance(node, ast.Attribute)
                 else node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                 else node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else "")
        if re.fullmatch(r"[A-Za-z_]\w*_c", value):
            names.add(value)
    return sorted(names)


def unsigned_band_patterns(tree):
    """Find literal regexes applied in a band/temperature/range-label context."""
    hits = Counter()
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    operations = {"compile", "findall", "finditer", "match", "search", "fullmatch"}
    aliases, direct = {"re"}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(a.asname or a.name for a in node.names if a.name == "re")
        elif isinstance(node, ast.ImportFrom) and node.module == "re":
            direct.update(a.asname or a.name for a in node.names if a.name in operations)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        called = (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                  and node.func.value.id in aliases and node.func.attr in operations
                  or isinstance(node.func, ast.Name) and node.func.id in direct)
        if not called or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            continue
        parent = parents.get(node)
        targets = (parent.targets if isinstance(parent, ast.Assign) else [parent.target]
                   if isinstance(parent, ast.AnnAssign) else [])
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent = parents.get(parent)
        function = parent.name if parent else "<module>"
        context = (" ".join(ast.unparse(target) for target in targets) if parent is None else function)
        context += " " + " ".join(ast.unparse(arg) for arg in node.args[1:])
        if not re.search(r"band|bin_|temperature|range|label", context, re.I):
            continue
        pattern = node.args[0].value
        if (r"\d" in pattern or "[0-9]" in pattern) and not any(
            signed in pattern for signed in ("-?", "[-+]?", "[+-]?", "[+-]", "[-+]", "−?")
        ):
            hits[function + ":" + pattern] += 1
    return dict(sorted(hits.items()))


def consumer_path(path):
    return (path.startswith("src/weather/operations/daily_refresh")
            or path.startswith("src/weather/reporting/promotion/")
            or path.endswith("/market_beating_objective_scoreboard.py")
            or path.endswith("/weather_only_model_proof_packet.py"))


def json_references(tree):
    # Deliberately over-inclusive: output/config literals need an explicit role too.
    return sorted({Path(n.value.replace("\\", "/")).name for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value.endswith(".json") and "\n" not in n.value and " " not in n.value})


def reachable(graph, roots):
    seen, pending = set(), list(roots)
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(graph.get(name, set()) - seen)
    return seen


def inventory(root):
    paths = tracked_paths(root)
    py = {p: (root / p).read_text(encoding="utf-8-sig") for p in paths
          if p.endswith(".py") and p.startswith(("src/", "app/", "tests/", "tools/"))}
    trees = {p: ast.parse(source) for p, source in py.items()}
    modules = {module_name(p): p for p in py if not p.startswith("tests/")}
    graph, entrypoints, imports, references, producers = {}, set(), {}, {}, {}
    for path, tree in trees.items():
        name = module_name(path)
        package = name if path.endswith("/__init__.py") else name.rpartition(".")[0]
        imported = imported_modules(tree, package)
        if path.startswith(("src/", "app/")):
            imports[path] = sorted({n.split(".")[0] for n in imported} - sys.stdlib_module_names -
                                   {"weather", "maker_core", "app", "src", "__future__"})
        if path.startswith("tests/"):
            continue
        strings = set()
        if "schema_registry" not in path:
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    strings.update(MODULE_TOKEN.findall(node.value))
        graph[name] = (imported | strings) & modules.keys()
        refs = json_references(tree)
        for value in refs:
            producers.setdefault(value, []).append(name)
        if consumer_path(path):
            references[path] = refs
    # Operational docs count as maintained manual entrypoints, never schema-owner strings.
    for path in paths:
        if (path.startswith(("scripts/", "docs/operations/", ".github/", ".codex/")) or path == "README.md") and Path(path).suffix in {".py", ".ps1", ".md", ".json", ".yml", ".yaml"}:
            text = (root / path).read_text(encoding="utf-8-sig")
            entrypoints.update(MODULE_TOKEN.findall(text))
            entrypoints.update(module_name(p) for p in py if p in text or p.replace("/", "\\") in text)
    entrypoints.update(n for n, p in modules.items() if p.startswith("app/") or p in {"src/weather/__init__.py"})
    used = reachable(graph, entrypoints & modules.keys())
    orphans = sorted(p for n, p in modules.items() if n not in used and not p.endswith("/__init__.py"))
    # Git object sizes cover the actual tracked bytes and avoid hydrating LFS objects.
    index = subprocess.check_output(["git", "ls-files", "-s", "-z"], cwd=root).decode().strip("\0").split("\0")
    objects = [row.split()[1] for row in index]
    sizes = subprocess.check_output(["git", "cat-file", "--batch-check=%(objectsize)"], cwd=root,
                                    input="\n".join(objects)+"\n", text=True).splitlines()
    byte_sizes = {row.split("\t", 1)[1]: int(size) for row, size in zip(index, sizes)}
    return {
        "module_lines": {p: len(s.splitlines()) for p, s in py.items()},
        "orphans": orphans,
        "retired": {p: dict(sorted(Counter(RETIRED.findall(s)).items())) for p, s in py.items() if RETIRED.search(s)},
        "c_names": {p: names for p, t in trees.items() if (names := c_names(t))},
        "unsigned_band_regex": {p: hits for p, t in trees.items() if p != "src/weather/units.py" and (hits := unsigned_band_patterns(t))},
        "large_files": {p: size for p, size in byte_sizes.items() if size > FILE_LIMIT},
        "roadmap_data": {p: size for p, size in byte_sizes.items() if p.startswith("docs/roadmap/") and Path(p).suffix in DATA_EXTENSIONS and size > ROADMAP_DATA_LIMIT},
        "imports": {p: values for p, values in imports.items() if values},
        "report_references": references,
        "producer_candidates": producers,
        "graph": graph,
    }


def growth(current, allowed, prefix=""):
    """Mappings/counts and set-like lists can shrink; new keys/items or growth fail."""
    errors = []
    if isinstance(current, dict):
        for key, value in current.items():
            path = f"{prefix}/{key}"
            if key not in allowed:
                errors.append(path)
            else:
                errors.extend(growth(value, allowed[key], path))
    elif isinstance(current, list):
        errors.extend(f"{prefix}/{value}" for value in set(current) - set(allowed))
    elif current > allowed:
        errors.append(f"{prefix}: {current} > {allowed}")
    return errors
