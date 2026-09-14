"""Fixed audit controller child of the adopted native host envelope.

Run only as -I -S -B with a hash-pinned request from that parent. This controller
does not grant host acceptance; the parent must independently prove its whole
process tree terminated, enforce resources and bind the actual S4U invocation.
"""

from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys


MODULES = ("__init__", "contracts", "records", "inputs", "settlement_inputs", "host_audit", "host", "offline_guard")
PACKAGE = "_weather_qualification_pipeline_authority"


class Authority(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, root, pins):
        if set(pins) != set(MODULES):
            raise ValueError("complete fixed controller import closure required")
        self.sources = {}
        for name in MODULES:
            path = root / (name + ".py")
            info = path.lstat()
            raw = path.read_bytes()
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400 or info.st_nlink != 1:
                raise ValueError("redirected controller source")
            if len(raw) > 2 * 1024**2 or hashlib.sha256(raw).hexdigest() != pins[name]:
                raise ValueError("controller import bytes differ")
            self.sources[PACKAGE if name == "__init__" else PACKAGE + "." + name] = (path, raw)

    def find_spec(self, fullname, path=None, target=None):
        if fullname == PACKAGE or fullname.startswith(PACKAGE + "."):
            if fullname not in self.sources:
                raise ImportError("undeclared controller import")
            return importlib.util.spec_from_loader(fullname, self, is_package=fullname == PACKAGE)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, raw = self.sources[module.__name__]
        module.__file__ = str(path)
        exec(compile(raw, str(path), "exec"), module.__dict__)


def main():
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 3:
        raise ValueError("fixed isolated host controller bootstrap required")
    raw = Path(sys.argv[1]).read_bytes()
    if len(raw) > 2 * 1024**2 or hashlib.sha256(raw).hexdigest() != sys.argv[2]:
        raise ValueError("host controller request bytes differ")
    import json
    request = json.loads(raw)
    if set(request) != {"plan", "controller_modules", "scratch"}:
        raise ValueError("unsupported host controller request")
    trusted = Path(request["plan"]["trusted_root"]) / "src/weather/operations/qualification"
    sys.meta_path.insert(0, Authority(trusted, request["controller_modules"]))
    from _weather_qualification_pipeline_authority import host, offline_guard, records

    # Reparse with the strict duplicate-key/number/path codec after the fixed
    # bootstrap closure is authenticated. No candidate package is on sys.path.
    request = records.decode(raw)
    plan = host.audit_plan(request["plan"])
    scratch = records.checked_root(Path(request["scratch"]))
    for protected in (plan["candidate"], plan["trusted_root"], plan["authority_root"], *plan["roots"]["roots"].values()):
        protected = records.checked_root(Path(protected))
        records.require(not scratch.is_relative_to(protected) and not protected.is_relative_to(scratch),
                        "controller scratch overlaps protected inputs")
    offline_guard.install(writable_roots=[str(scratch), plan["inputs_root"], plan["output"]],
                          forbidden_roots=[], executable_paths=[sys.executable])
    host.run_audit(plan, scratch=scratch)


if __name__ == "__main__":
    main()
