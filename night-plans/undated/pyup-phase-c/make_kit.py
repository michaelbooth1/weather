"""Generate (or --check) the undated Phase C kit from HOST_PYTHON_UPGRADE_RUNBOOK.md.

Stdlib only; reads the runbook and writes nothing outside this folder. Run from the repository root:

    .\\venv\\Scripts\\python.exe -I night-plans\\undated\\pyup-phase-c\\make_kit.py           # write the kit
    .\\venv\\Scripts\\python.exe -I night-plans\\undated\\pyup-phase-c\\make_kit.py --check   # verify, write nothing

raw/<step>.ps1 is the runbook fence for that step, byte for byte (Build-Venv and Test-Venv are the function
definitions only, as C5 prescribes). phase-c-<step>.ps1 is the wrapper: a generated preamble, then the raw body
with only the four session-header placeholders replaced (PLACEHOLDERS below). --check regenerates in memory and
fails on any difference, on a raw/wrapper mismatch, on a disable verified through State, and on a SHA256SUMS
mismatch. Every .ps1 is UTF-8 with a BOM (Windows PowerShell 5.1 reads a BOM-less script as ANSI) and LF.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

KIT = pathlib.Path(__file__).resolve().parent
REPO = KIT.parents[2]
RUNBOOK = REPO / "docs" / "operations" / "HOST_PYTHON_UPGRADE_RUNBOOK.md"
BOM = b"\xef\xbb\xbf"
BEGIN = "# ---- BEGIN RAW {name} (sha256 {sha}) ----"
END = "# ---- END RAW {name} ----"

# (step, anchor line prefix in the runbook, how to cut the fence, required session state)
STEPS = [
    ("00-session-header", "## 6. Session header", "fence", []),
    ("01-build-venv-function", "**B1c. Stage worktree", "function:Build-Venv", ["fn:NoGo"]),
    ("02-test-venv-function", "**B1d. Test-Venv", "drop:Test-Venv $StagePy $Stage 'stage'", ["fn:NoGo"]),
    ("10-c0", "**C0. GO checks.**", "fence", ["fn:Build-Venv", "fn:Test-Venv"]),
    ("11-c1", "**C1. Lease and fresh receipts.**", "fence", ["var:GapChoice", "var:q"]),
    ("12-c2", "**C2. Quiesce the auxiliary tasks", "fence", ["var:N", "var:FamilyTasks", "var:ShadowStop"]),
    ("13-c3", "**C3. Stop the capture workers.**", "fence", ["fn:Quiesce-Aux", "fn:Undo-Aux"]),
    ("14-c4", "**C4. Sweep and rename", "fence", ["fn:Stop-Capture", "fn:Undo-Stop"]),
    ("15-c5", "**C5. Build the new venv offline.**", "fence", ["var:GapStart", "fn:Build-Venv"]),
    ("16-c6", "**C6. Quick verify.**", "fence", ["fn:Test-Venv"]),
    ("17-c7", "**C7. Restore the capture workers", "fence", ["fn:Wait-Restore", "var:GapStart"]),
    ("18-c8", "**C8. Core verify.**", "fence", ["var:GapEnd", "var:ra0"]),
    ("19-c9", "**C9. Core decision", "fence", ["var:GapEnd", "var:GapChoice"]),
    ("20-c9b", "**C9b. Restore the auxiliary tasks.**", "fence", ["fn:Undo-Aux", "fn:Start-AuxHolders"]),
    ("21-c9c", "**C9c. Aux verify", "fence", ["var:AuxRestart", "fn:Test-PrestateEnabled"]),
    ("22-c10", "**C10. Close-out.**", "fence", ["var:GapEnd", "var:Head"]),
    ("30-rollback", "### §R. Rollback", "fence", ["fn:Quiesce-Aux", "fn:Stop-Capture", "fn:Rename-WithSweep", "var:N"]),
]

# Session-header placeholders -> wrapper parameters. Nothing else in a raw body is changed.
PLACEHOLDERS = {
    "$P       = '<production checkout>'": "$P       = $ProductionRoot",
    "$R       = '<cutover record root, outside data\\ and outside the checkout>'": "$R       = $RecordRoot",
    "$NewHome = '<new 3.11.9 home, e.g. C:\\Program Files\\Python311-cp3119>'": "$NewHome = $KitNewHome",
    "$Stage   = '<stage worktree next to the checkout>'": "$Stage   = $KitStage",
}

HEADER_PREAMBLE = r"""param(
  [Parameter(Mandatory = $true)][string]$ProductionRoot,
  [Parameter(Mandatory = $true)][string]$RecordRoot,
  [Parameter(Mandatory = $true)][string]$KitNewHome,
  [Parameter(Mandatory = $true)][string]$KitStage,
  [Parameter(Mandatory = $true)][string]$NightDate
)
if ($MyInvocation.InvocationName -ne '.') { throw 'dot-source this file in the elevated session: . .\phase-c-00-session-header.ps1 -ProductionRoot ... (see PHASE-C.md)' }
if ($NightDate -notmatch '^\d{4}-\d{2}-\d{2}$') { throw 'NightDate must be yyyy-MM-dd, the morning date of the C night' }
if ($NightDate -eq '2026-11-01') { throw 'G11: no phase runs on the DST night' }
foreach ($kitValue in $ProductionRoot, $RecordRoot, $KitNewHome, $KitStage) { if ($kitValue -match '[<>]') { throw "kit parameter still holds a placeholder: $kitValue" } }
# Kit integrity: every file listed in SHA256SUMS must match before anything runs.
$KitRoot = $PSScriptRoot
$kitSums = Join-Path $KitRoot 'SHA256SUMS'
if (-not (Test-Path -LiteralPath $kitSums)) { throw 'SHA256SUMS is missing next to the kit' }
foreach ($kitLine in @(Get-Content -LiteralPath $kitSums | Where-Object { $_.Trim() })) {
  if ($kitLine -notmatch '^([0-9a-f]{64}) \*(.+)$') { throw "bad SHA256SUMS line: $kitLine" }
  $kitWant = $Matches[1]; $kitName = $Matches[2]
  $kitHave = (Get-FileHash -LiteralPath (Join-Path $KitRoot $kitName) -Algorithm SHA256).Hash.ToLower()
  if ($kitHave -ne $kitWant) { throw "kit file $kitName does not match SHA256SUMS" } }
$KitNightDate = $NightDate"""

STEP_PREAMBLE = r"""if ($MyInvocation.InvocationName -ne '.') { throw 'dot-source this file in the same session as phase-c-00-session-header.ps1' }
if (-not (Get-Command NoGo -CommandType Function -ErrorAction SilentlyContinue) -or -not $KitRoot) { throw 'load phase-c-00-session-header.ps1 first, in this session' }"""

C0_EXTRA = r"""if ((Get-Date).ToString('yyyy-MM-dd') -ne $KitNightDate) { NoGo "C0: the local date is not the kit NightDate $KitNightDate" }"""


def fail(msg: str) -> None:
    sys.exit(f"make_kit: {msg}")


def fence_after(lines: list[str], anchor: str) -> list[str]:
    hits = [i for i, line in enumerate(lines) if line.startswith(anchor)]
    if len(hits) != 1:
        fail(f"anchor {anchor!r} found {len(hits)} times")
    i = hits[0] + 1
    while i < len(lines) and lines[i].strip() != "```powershell":
        if lines[i].startswith("**C") or lines[i].startswith("### "):
            fail(f"no powershell fence under {anchor!r}")
        i += 1
    j = i + 1
    while j < len(lines) and lines[j].strip() != "```":
        j += 1
    if j >= len(lines):
        fail(f"unterminated fence under {anchor!r}")
    return lines[i + 1 : j]


def cut(body: list[str], how: str) -> list[str]:
    if how == "fence":
        return body
    if how.startswith("function:"):
        name = how.split(":", 1)[1]
        start = [i for i, line in enumerate(body) if line.startswith(f"function {name}(")]
        if len(start) != 1:
            fail(f"function {name} found {len(start)} times")
        end = next((k for k in range(start[0] + 1, len(body)) if body[k] == "}"), None)
        if end is None:
            fail(f"function {name} has no closing brace at column 0")
        return body[start[0] : end + 1]
    if how.startswith("drop:"):
        line = how.split(":", 1)[1]
        if body.count(line) != 1:
            fail(f"line to drop {line!r} found {body.count(line)} times")
        return [b for b in body if b != line]
    fail(f"unknown cut {how}")
    return []


def guards(reqs: list[str]) -> list[str]:
    out = []
    for r in reqs:
        kind, name = r.split(":", 1)
        if kind == "fn":
            out.append(f"if (-not (Get-Command {name} -CommandType Function -ErrorAction SilentlyContinue)) {{ NoGo 'kit: function {name} is not defined; run the earlier steps in this session' }}")
        else:
            out.append(f"if (-not (Test-Path -LiteralPath variable:{name})) {{ NoGo 'kit: ${name} is not set; run the earlier steps in this session' }}")
    return out


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(runbook_text: str) -> dict[str, bytes]:
    lines = runbook_text.split("\n")
    rb_sha = sha(runbook_text.encode("utf-8"))
    files: dict[str, bytes] = {}
    for step, anchor, how, reqs in STEPS:
        raw = "\n".join(cut(fence_after(lines, anchor), how)) + "\n"
        raw_sha = sha(raw.encode("utf-8"))
        files[f"raw/{step}.ps1"] = BOM + raw.encode("utf-8")
        body = raw
        if step == "00-session-header":
            for old, new in PLACEHOLDERS.items():
                if body.count(old) != 1:
                    fail(f"placeholder {old!r} found {body.count(old)} times")
                body = body.replace(old, new)
        head = [
            f"# Phase C kit, step {step}. GENERATED by make_kit.py from docs/operations/HOST_PYTHON_UPGRADE_RUNBOOK.md",
            f"# (runbook sha256 {rb_sha}). Do not edit: change the runbook and regenerate. Dot-source it, never run it.",
        ]
        if step == "00-session-header":
            pre = [HEADER_PREAMBLE]
        else:
            pre = [STEP_PREAMBLE] + guards(reqs)
            if step == "10-c0":
                pre.append(C0_EXTRA)
            pre.append(f"Log 'kit step {step} (raw sha256 {raw_sha})'")
        text = "\n".join(head + pre + [BEGIN.format(name=step, sha=raw_sha)]) + "\n" + body + END.format(name=step) + "\n"
        if step == "00-session-header":
            text += f'Log "kit step {step} loaded (raw sha256 {raw_sha}), night $KitNightDate"\n'
        files[f"phase-c-{step}.ps1"] = BOM + text.encode("utf-8")
    return files


def verify_semantics(files: dict[str, bytes]) -> None:
    for name, data in files.items():
        if not name.startswith("raw/"):
            continue
        lines = data[len(BOM):].decode("utf-8").split("\n")
        for i, line in enumerate(lines):
            if "Disable-ScheduledTask" in line:
                window = " ".join(lines[i : i + 3])
                if re.search(r"\.State\s+-ne\s+'Disabled'", window):
                    fail(f"{name}:{i + 1}: a disable is verified through State; use Settings.Enabled")
    for name in ("raw/12-c2.ps1", "raw/13-c3.ps1"):
        if b".Settings.Enabled -ne $false" not in files[name]:
            fail(f"{name} lacks the Settings.Enabled disable check")


def verify_raw_wrapper(files: dict[str, bytes]) -> None:
    for step, *_ in STEPS:
        raw = files[f"raw/{step}.ps1"][len(BOM):].decode("utf-8")
        wrap = files[f"phase-c-{step}.ps1"][len(BOM):].decode("utf-8")
        raw_sha = sha(raw.encode("utf-8"))
        b = BEGIN.format(name=step, sha=raw_sha) + "\n"
        e = END.format(name=step) + "\n"
        if wrap.count(b) != 1 or wrap.count(e) != 1:
            fail(f"phase-c-{step}.ps1: raw markers missing or repeated")
        inner = wrap.split(b, 1)[1].split(e, 1)[0]
        expect = raw
        if step == "00-session-header":
            for old, new in PLACEHOLDERS.items():
                expect = expect.replace(old, new)
        if inner != expect:
            fail(f"phase-c-{step}.ps1 body differs from raw/{step}.ps1 beyond the declared placeholders")


def sums(files: dict[str, bytes]) -> bytes:
    names = sorted(files)
    return "".join(f"{sha(files[n])} *{n}\n" for n in names).encode("ascii")


def main() -> int:
    check = sys.argv[1:] == ["--check"]
    if sys.argv[1:] and not check:
        fail("usage: make_kit.py [--check]")
    text = RUNBOOK.read_bytes().decode("utf-8")
    if "\r" in text:
        fail("the runbook has CR characters; it is LF-only")
    files = build(text)
    verify_semantics(files)
    verify_raw_wrapper(files)
    # PHASE-C.md, make_kit.py and .gitattributes are hand-written and hashed as they are.
    for extra in ("PHASE-C.md", "make_kit.py", ".gitattributes"):
        files[extra] = (KIT / extra).read_bytes()
    files["SHA256SUMS"] = sums(files)
    generated = [n for n in files if n.endswith(".ps1") or n == "SHA256SUMS"]
    if check:
        bad = [n for n in generated if not (KIT / n).exists() or (KIT / n).read_bytes() != files[n]]
        extra = sorted(
            str(p.relative_to(KIT)).replace("\\", "/")
            for p in KIT.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
            and str(p.relative_to(KIT)).replace("\\", "/") not in files
        )
        if bad or extra:
            fail(f"kit is stale: differs {bad}, unexpected {extra}")
        print(f"kit OK: {len(generated)} generated files match the runbook; raw/wrapper consistent; SHA256SUMS current")
        return 0
    for n in generated:
        p = KIT / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(files[n])
    print(f"wrote {len(generated)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
