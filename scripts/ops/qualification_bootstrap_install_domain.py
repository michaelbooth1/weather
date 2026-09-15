"""Fixed recovery/documentation code from B, retained through the whole roll.

The native parent has already locked every B source blob and the complete
qualified runtime. No module from K or the temporary adapter is imported here.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate domain input key")
        result[key] = value
    return result


def pinned(path, sha256, size=None):
    raw = path.read_bytes()
    if not 0 < len(raw) <= 2 * 1024**2 or (size is not None and len(raw) != size) or hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("domain input bytes changed")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("constant")))


if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode or len(sys.argv) != 4:
    raise RuntimeError("fixed isolated bootstrap domain arguments required")
request, sha256, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
value = pinned(request, sha256)
if value["schema"] != "qualification_bootstrap_install_envelope_v1" or mode not in {"capture", "execution-status", "documentation"}:
    raise ValueError("not a fixed bootstrap domain request")
profile_ref = value["environment"]
profile = pinned(request.parent / profile_ref["path"], profile_ref["sha256"], profile_ref["size"])
adopted = Path(value["baseline_control"]["root"])
trusted = Path(__file__).absolute().parents[2]
if trusted != Path(value["control"]["root"]) or adopted == trusted or adopted == Path(value["candidate"]):
    raise ValueError("domain root is not the separately retained baseline")
# Avoid site processing and any package already imported by A/K. This process
# has imported only the stdlib and starts with exactly B's package directory.
sys.path[:] = [str(adopted / "src"), *(entry for entry in sys.path if entry and Path(entry).is_absolute()),
               *profile["bindings"]["site_roots"]]
from weather import paths

production = Path(value["repo_root"])
paths.REPO_ROOT = production
for name, directory in (("DATA_ROOT", "data"), ("ARTIFACTS_ROOT", "artifacts"), ("CONFIG_ROOT", "config"),
                        ("DOCS_ROOT", "docs"), ("TOOLS_ROOT", "tools")):
    setattr(paths, name, production / directory)
if mode == "capture":
    from weather.operations.capture_recovery_check import check_capture_recovery
    result = check_capture_recovery(production)
elif mode == "execution-status":
    from weather.operations.execution_tape_supervisor import read_status, execution_tape_health
    status = read_status()
    result = {"status": status, "health": execution_tape_health(status, stale_after_seconds=180)}
else:
    from weather.operations.documentation_transaction import begin_transaction
    tool = profile["tools"]["git"]
    git = Path(tool["root"]) / tool["path"]
    head = subprocess.run([str(git), "--no-replace-objects", "-C", str(production), "rev-parse", "HEAD"],
                          stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=10).stdout.decode().strip()
    result = begin_transaction(production, integration_tip=head, branch=value["branch_ref"],
                               expected_tip=value["source"]["commit"])
print(json.dumps(result, sort_keys=True, default=str))
