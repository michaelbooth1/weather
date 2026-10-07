"""C3 step 8 stub wrapper (v3): runs the tree's own _prompt_until, extracted at run time from BOTH
templates, bound by SHA-256. Nothing else from the templates is executed."""
import __future__
import ast, hashlib, json, msvcrt, sys, time
from datetime import datetime, timedelta
from pathlib import Path

TEMPLATES = ("stage0.py.tmpl", "stage1_cancel_all.py.tmpl")
EXPECTED = "C3_REHEARSAL_TYPED_INPUT_ACCEPTED"
PROMPT_WINDOW_S, RESERVE_S = 90, 30


def extract(tree: Path) -> dict:
    found = {}
    for name in TEMPLATES:
        path = tree / "scripts" / "ops" / "international_live_templates" / name
        source = path.read_text(encoding="utf-8")
        functions = [node for node in ast.parse(source).body
                     if isinstance(node, ast.FunctionDef) and node.name == "_prompt_until"]
        if len(functions) != 1:
            sys.exit(f"{name}: expected exactly one top-level _prompt_until, found {len(functions)}")
        segment = ast.get_source_segment(source, functions[0])
        found[name] = {"source": segment,
                       "prompt_until_sha256": hashlib.sha256(segment.encode("utf-8")).hexdigest(),
                       "template_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return found


tree, mode = Path(sys.argv[1]), sys.argv[2]
extracted = extract(tree)
hashes = {name: {k: v for k, v in item.items() if k != "source"} for name, item in extracted.items()}
sources = {item["source"] for item in extracted.values()}
if mode == "--hash-only":
    print(json.dumps(hashes, indent=1))
    if len(sources) != 1:
        sys.exit("C3 PROMPT EXTRACTION FAIL: Stage 0 and Stage 1 _prompt_until differ")
    print("C3 PROMPT EXTRACTION OK")
    sys.exit(0)

pinned = mode.strip().lower()
bound = len(sources) == 1 and all(h["prompt_until_sha256"] == pinned for h in hashes.values())


def stdin_state():
    # M5: information only. This wrapper is created with bInheritHandles=false, so its stdin may be
    # None or unusable; that must never crash the evidence line. The #229 proof is at the stub launcher.
    if sys.stdin is None:
        return None
    try:
        return sys.stdin.isatty()
    except (ValueError, OSError):
        return "unusable"


print(json.dumps({"stdin": stdin_state(), "sitecustomize": "sitecustomize" in sys.modules,
                  "prompt_bound": bound,
                  "prompt_until_sha256": {n: h["prompt_until_sha256"] for n, h in hashes.items()}}), flush=True)
if not bound:
    sys.exit(8)

# The extracted function's globals: exactly what the templates provide, with a stub scope and reserve.
# A minimal builtins table makes any unexpected reference fail closed (NameError).
namespace = {
    "__name__": "c3_extracted_prompt",
    "__builtins__": {"str": str, "int": int, "list": list, "RuntimeError": RuntimeError,
                     "KeyboardInterrupt": KeyboardInterrupt, "TimeoutError": TimeoutError},
    "sys": sys, "time": time, "msvcrt": msvcrt, "datetime": datetime, "timedelta": timedelta,
    "PRE_CREDENTIAL_RESERVE_SECONDS": RESERVE_S,
    "SCOPE": {"run_not_after_local":
              (datetime.now().astimezone() + timedelta(seconds=PROMPT_WINDOW_S + RESERVE_S)).isoformat()},
}
code = compile(next(iter(sources)), "<_prompt_until extracted from stage0 and stage1 templates>", "exec",
               flags=__future__.annotations.compiler_flag, dont_inherit=True)   # the templates use the future import
exec(code, namespace)
try:
    typed = namespace["_prompt_until"](EXPECTED).strip()    # production: _prompt_until(...).strip() != confirmation
except TimeoutError:
    print(json.dumps({"typed_matches": None, "reason": "timeout"}), flush=True)
    sys.exit(5)
except KeyboardInterrupt:
    print(json.dumps({"typed_matches": None, "reason": "interrupt"}), flush=True)
    sys.exit(6)
print(json.dumps({"typed_matches": typed == EXPECTED, "length": len(typed)}), flush=True)
sys.exit(0 if typed == EXPECTED else 4)
