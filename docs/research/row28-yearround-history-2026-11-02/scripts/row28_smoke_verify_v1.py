"""Row 28 smoke check v1 (lane L59): runner v6's verify_prev, unchanged, on a smoke receipt.

It does not import runner v6 (its module level sets thread caps and defines everything else). It checks the runner's
sha256, extracts by ast the exact source of the definitions verify_prev needs (Halt, sha256_file, FORBIDDEN_ROOTS,
MAIN_DATA_PIN, _OBSERVED_READS, guard_read, verify_prev) and executes only those. It then calls
verify_prev({"prev": {stage: {"path": walk.json, "sha256": its sha256}}}, stage) and prints PASS or the Halt text.

Usage: python -I -B row28_smoke_verify_v1.py <runner v6 path> <smoke OutDir> <stage>
"""
import ast, hashlib, json, sys
from pathlib import Path

RUNNER_V6_SHA256 = "fd4464744e729cb8ed27eb68aa998d528ac4d2bfe5075d9837b9b02b7e2cae1b"
NEEDED = ("Halt", "sha256_file", "FORBIDDEN_ROOTS", "MAIN_DATA_PIN", "_OBSERVED_READS", "guard_read", "verify_prev")

runner, out_dir, stage = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
src = runner.read_bytes()
if hashlib.sha256(src).hexdigest() != RUNNER_V6_SHA256:
    sys.exit("runner sha256 differs from runner v6")
tree = ast.parse(src.decode("utf-8"))
found = {}
for node in tree.body:
    names = [node.name] if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else \
        [t.id for t in node.targets if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else []
    for n in names:
        if n in NEEDED:
            found[n] = node
if sorted(found) != sorted(NEEDED):
    sys.exit(f"missing definitions: {sorted(set(NEEDED) - set(found))}")
ns = {"__name__": "row28_smoke_verify", "hashlib": hashlib, "json": json, "Path": Path}
exec(compile(ast.Module(body=[found[n] for n in NEEDED], type_ignores=[]), str(runner), "exec"), ns)
walk = out_dir / "walk.json"
cfg = {"prev": {stage: {"path": str(walk), "sha256": ns["sha256_file"](walk)}}}
try:
    report, folder = ns["verify_prev"](cfg, stage)
except ns["Halt"] as e:
    print(f"FAIL verify_prev: {e}")
    sys.exit(1)
print(f"PASS verify_prev accepted {stage} at {folder} (report status {report.get('status')})")
