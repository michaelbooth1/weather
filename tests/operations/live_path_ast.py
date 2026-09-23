"""Static inventory helpers; never import the modules being inspected."""
import ast
from importlib import metadata
import re
import sys
import tomllib


def trees(root):
    for path in sorted((root / "src").rglob("*.py")):
        yield path.relative_to(root).as_posix(), ast.parse(path.read_text(encoding="utf-8-sig"))


def bindings(tree):
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def name_of(node, names):
    if isinstance(node, ast.Name):
        return names.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return name_of(node.value, names) + '.' + node.attr
    return ''


def raw_http_sites(tree):
    names = bindings(tree)
    targets = {'urllib.request.Request', 'urllib.request.urlopen'}
    # Include imported opener aliases used in `(opener or urlopen)(...)` and
    # simple assignments. Count each call once, not every descendant Name.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            resolved = name_of(node.value, names)
            for target in node.targets:
                if isinstance(target, ast.Name) and resolved in targets:
                    names[target.id] = resolved
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        candidates = [name_of(node.func, names)]
        if isinstance(node.func, ast.BoolOp):
            candidates += [name_of(item, names) for item in node.func.values]
        if any(item in targets for item in candidates):
            found.append(node.lineno)
    # `open_request = opener or urlopen` is an existing injectable open site.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.BoolOp):
            if any(name_of(item, names) == 'urllib.request.urlopen' for item in node.value.values):
                found.append(node.lineno)
    return sorted(set(found))


def external_imports(tree):
    for node in ast.walk(tree):
        imports = ([alias.name for alias in node.names] if isinstance(node, ast.Import) else
                   [node.module] if isinstance(node, ast.ImportFrom) and not node.level and node.module else [])
        for name in imports:
            top = name.split('.')[0]
            if top not in sys.stdlib_module_names and top not in {'weather', 'app', '__future__'}:
                yield node.lineno, top


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def declared_distributions(root):
    project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    declarations = project['dependencies'] + [
        item for extra in project.get('optional-dependencies', {}).values() for item in extra
    ] + (root / 'requirements.txt').read_text(encoding='utf-8').splitlines()
    return {normalized(re.split(r'[<>=!~;\[ ]', item.strip())[0]) for item in declarations
            if item.strip() and not item.lstrip().startswith('#')}


def import_misses(root):
    providers = metadata.packages_distributions()
    declared = declared_distributions(root)
    missing = {}
    for path, tree in trees(root):
        if not path.startswith('src/weather/'):
            continue
        for line, top in external_imports(tree):
            distributions = {normalized(item) for item in providers.get(top, [])}
            # Optional distributions need not be installed in architecture-only
            # CI. These distribution-owned top-level names are explicit, not
            # inferred from an unrelated transitive installation.
            known = {'polymarket': 'polymarket-client', 'dotenv': 'python-dotenv',
                     'websocket': 'websocket-client', 'sklearn': 'scikit-learn', 'netCDF4': 'netcdf4'}
            if not distributions:
                distributions = {known.get(top, normalized(top))}
            if not distributions & declared:
                missing[f'{path}:{line}:{top}'] = sorted(distributions)
    return missing


def powershell_commands(tree):
    """Inventory argument vectors, including canonical executable variables.

    Conservative: any argument vector with -Command/-File and a PowerShell
    executable expression is checked, even before it is passed to subprocess.
    """
    assignments = {}
    names = bindings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)

    def is_shell(node, seen=frozenset()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.lower().replace('\\', '/').split('/')[-1] in {'powershell', 'powershell.exe'}
        if isinstance(node, ast.Name) and node.id not in seen:
            return any(is_shell(value, seen | {node.id}) for value in assignments.get(node.id, []))
        if isinstance(node, ast.Call) and name_of(node.func, names).endswith('canonical_windows_powershell'):
            return True
        return any(is_shell(child, seen) for child in ast.iter_child_nodes(node))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
            continue
        words = [item.value.lower() if isinstance(item, ast.Constant) and isinstance(item.value, str) else None
                 for item in node.elts]
        boundaries = [i for i, word in enumerate(words) if word in {'-command', '-file', '-encodedcommand'}]
        literal_shell = words[0] and words[0].replace('\\', '/').split('/')[-1] in {'powershell', 'powershell.exe'}
        if not boundaries and not literal_shell:
            continue
        if not is_shell(node.elts[0]):
            continue
        if not boundaries:
            yield node.lineno, False
            continue
        boundary = min(boundaries)
        valid = any(words[i:i+2] == ['-executionpolicy', 'bypass'] for i in range(1, boundary - 1))
        yield node.lineno, valid
