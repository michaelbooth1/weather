"""One fixed candidate audit, launched by the frozen admitted host parent.

The request hash is an argument from that parent. This is not a user-facing
command dispatcher, acceptance producer, or substitute for native containment.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import sys
import types


TRUSTED_MODULES = ("__init__", "contracts", "records", "inputs", "settlement_inputs", "host_audit", "offline_guard")
PACKAGE = "_weather_qualification_host_authority"


class FrozenModules(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import only the bytes hashed before candidate import; never stale pyc."""

    def __init__(self, root, pins):
        if set(pins) != set(TRUSTED_MODULES):
            raise ValueError("incomplete trusted host child closure")
        self.sources = {}
        for name in TRUSTED_MODULES:
            path = root / (name + ".py")
            info = path.lstat()
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_nlink != 1:
                raise ValueError("redirected trusted host child dependency")
            raw = path.read_bytes()
            if len(raw) > 2 * 1024**2 or hashlib.sha256(raw).hexdigest() != pins[name]:
                raise ValueError("trusted host child dependency changed")
            self.sources[PACKAGE if name == "__init__" else PACKAGE + "." + name] = (path, raw)

    def find_spec(self, fullname, path=None, target=None):
        if fullname == PACKAGE or fullname.startswith(PACKAGE + "."):
            if fullname not in self.sources:
                raise ImportError("undeclared trusted host child import")
            return importlib.util.spec_from_loader(fullname, self, is_package=fullname == PACKAGE)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, raw = self.sources[module.__name__]
        module.__file__ = str(path)
        exec(compile(raw, str(path), "exec"), module.__dict__)


def main():
    if not sys.flags.isolated or not sys.flags.no_site or len(sys.argv) != 3:
        raise ValueError("host child requires the fixed isolated bootstrap")
    path, expected = sys.argv[1:]
    raw = Path(path).read_bytes()
    if len(raw) > 2 * 1024**2 or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("host child request differs")
    request = json.loads(raw)
    # The native parent's strict decoder/hash gate precedes this bootstrap.
    common = {"phase", "candidate", "trusted_root", "trusted_modules", "sites", "authority_root", "source_inventory",
              "inputs_root", "roots", "output", "maximum"}
    if request.get("phase") != "audit" or set(request) != common | {"preparation"}:
        raise ValueError("unsupported host child request")
    candidate = Path(request["candidate"])
    if not candidate.is_absolute() or Path.cwd().resolve() != candidate.resolve():
        raise ValueError("host child candidate directory differs")
    frozen = FrozenModules(Path(request["trusted_root"]), request["trusted_modules"])
    sys.meta_path.insert(0, frozen)
    from _weather_qualification_host_authority import contracts, records, offline_guard, host_audit

    candidate = records.checked_root(candidate)
    output = records.checked_root(Path(request["output"]))
    inputs_root = records.checked_root(Path(request["inputs_root"]))
    authority = contracts.Graph(records.checked_root(Path(request["authority_root"])))
    expected_files = {item["path"]: item for item in contracts.inventory(
        authority.get(request["source_inventory"]), "qualification_source_inventory_v2")["files"]}
    roots = host_audit.source_roots(request["roots"])
    forbidden = list(roots.roots.values())
    records.require(not any(candidate == root or candidate.is_relative_to(root) or inputs_root.is_relative_to(root)
                            or output.is_relative_to(root) for root in forbidden), "audit roots overlap mutable sources")
    sites = [records.checked_root(Path(site)) for site in contracts.sequence(request["sites"], minimum=1, maximum=4)]
    records.require(not any(site.is_relative_to(candidate) for site in sites), "candidate cannot supply dependency sites")
    offline_guard.install(writable_roots=[str(output)], forbidden_roots=[str(root) for root in forbidden], executable_paths=[])
    sys.dont_write_bytecode = True
    sys.path[:] = [str(candidate), str(candidate / "src"), *map(str, sites),
                   *(entry for entry in sys.path if entry and Path(entry).is_absolute())]
    from weather.reporting.source_gates import settlement_source_audit

    def imports():
        result = []
        for name, module in sorted(sys.modules.items()):
            if name != "weather" and not name.startswith("weather."):
                continue
            module_path = records.checked_root(Path(module.__file__).parent) / Path(module.__file__).name
            relative = module_path.relative_to(candidate).as_posix()
            expected_file = expected_files.get(relative)
            raw_module = module_path.read_bytes()
            records.require(expected_file is not None and expected_file["sha256"] == hashlib.sha256(raw_module).hexdigest()
                            and expected_file["size"] == len(raw_module), "candidate import differs from reviewed source")
            result.append({"module": name, "path": relative, "sha256": expected_file["sha256"]})
        records.require(result and any(row["module"] == "weather.reporting.source_gates.settlement_source_audit" for row in result),
                        "actual candidate audit import missing")
        return result

    before = imports()
    result = host_audit.run(input_graph=contracts.Graph(inputs_root), preparation_ref=request["preparation"],
                           roots=request["roots"], output=output, maximum=request["maximum"],
                           candidate_audit=settlement_source_audit)
    after = imports()
    records.require(all(row in after for row in before), "candidate import identity changed during audit")
    records.publish(output, "candidate-audit-imports.json", {"schema": "qualification_audit_imports_v2",
        "source_inventory_sha256": request["source_inventory"]["sha256"], "before": before, "after": after,
        "computation": result})


if __name__ == "__main__":
    main()
