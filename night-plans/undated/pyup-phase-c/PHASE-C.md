# Phase C kit (undated): host Python cutover, generated from the runbook

The source is `docs/operations/HOST_PYTHON_UPGRADE_RUNBOOK.md`, section 7 "Phase C" and its 2026-10-22 revision note
(the C2 disable check). **If the runbook differs from this kit, the runbook wins: regenerate the kit.** The kit has no
date. The owner names the night (G0), and the state of play holds it; pass it as `-NightDate`.

The 10-21/22 attempt stopped at C2 at 01:02:11 on a false NO-GO ("disable WeatherMakerEvidenceCapture"): the disable
was verified through `State`, which stays `Running` while the 88a worker runs. Nothing was swapped. This kit is built
from the corrected text, where both post-disable checks read `Settings.Enabled`. A kit built from the earlier text must
not be used.

## Files

| File | Role |
| --- | --- |
| `raw/<step>.ps1` | The runbook fence for that step, byte for byte. `01` and `02` are the `Build-Venv` and `Test-Venv` definitions only, as C5 prescribes. |
| `phase-c-<step>.ps1` | The wrapper you dot-source. It has a generated preamble, then the raw body between `BEGIN RAW` and `END RAW` markers. Only the session header changes the raw text, and only its four placeholders (`$P`, `$R`, `$NewHome`, `$Stage`), which become parameters. |
| `make_kit.py` | Stdlib generator. `--check` regenerates in memory and fails on a stale kit, on a raw/wrapper difference beyond the four placeholders, on a disable verified through `State`, or on a `SHA256SUMS` mismatch. |
| `SHA256SUMS` | sha256 of every other file in the kit. The session header verifies all of them before it runs anything. |
| `.gitattributes` | Keeps the files byte-exact (`* -text`). |

Every `.ps1` is UTF-8 with a BOM and LF line endings: Windows PowerShell 5.1 reads a BOM-less script as ANSI, and the
runbook text holds `§`.

## What the wrappers add

- **Session header (`00`):** the parameters below; a refusal unless dot-sourced; `-NightDate` must be `yyyy-MM-dd` and
  not the DST night (G11); no parameter may still hold `<` or `>`; every file in `SHA256SUMS` must match.
- **Every later step:** a refusal unless dot-sourced into the session that loaded `00`; a `NoGo` when the functions
  or variables of an earlier step are missing (so a NoGo after C1 still releases the lease); one `night.log` line
  naming the step and its raw sha256.
- **C0 (`10`):** a `NoGo` unless the local date equals `-NightDate`.

Nothing else is added, and no step is reordered. The gates, the GO pause after C0, the deadlines and §R are the
runbook's own.

## Inputs (all placeholders; read them on the host)

| Parameter | Value |
| --- | --- |
| `-ProductionRoot` | the production checkout, the `WeatherSnapshotLoopSupervisor` working directory |
| `-RecordRoot` | the cutover record root `$R` used since Phase A |
| `-KitNewHome` | the 3.11.9 home from Phase A |
| `-KitStage` | the qualified stage worktree named in `$R\qualification.json` |
| `-NightDate` | `<yyyy-MM-dd>`, the morning date of the owner-named C night |

## Order (one elevated Windows PowerShell 5.1 window; nothing may tail `night.log`)

1. Before the night, on the workstation: `make_kit.py --check` exits 0, and the copy on the host matches `SHA256SUMS`.
2. Load the session, then the two function definitions, then C0, and stop for the owner's GO:

```powershell
Set-Location -LiteralPath '<kit folder on the host>'
. .\phase-c-00-session-header.ps1 -ProductionRoot '<production checkout>' -RecordRoot '<record root>' -KitNewHome '<3.11.9 home>' -KitStage '<stage worktree>' -NightDate '<yyyy-MM-dd>'
. .\phase-c-01-build-venv-function.ps1
. .\phase-c-02-test-venv-function.ps1
. .\phase-c-10-c0.ps1
```

3. After GO, one step at a time, reading `night.log` between steps:

```powershell
. .\phase-c-11-c1.ps1
. .\phase-c-12-c2.ps1
. .\phase-c-13-c3.ps1
. .\phase-c-14-c4.ps1
. .\phase-c-15-c5.ps1
. .\phase-c-16-c6.ps1
. .\phase-c-17-c7.ps1
. .\phase-c-18-c8.ps1
. .\phase-c-19-c9.ps1
. .\phase-c-20-c9b.ps1
. .\phase-c-21-c9c.ps1
. .\phase-c-22-c10.ps1
```

4. A failure after the C4 rename runs `. .\phase-c-30-rollback.ps1` in the same session, started by 02:45 (§R).

## Checks before a kit is handed over

```text
.\venv\Scripts\python.exe -I night-plans\undated\pyup-phase-c\make_kit.py --check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\check_markdown_powershell_fences.ps1 -Path 'docs\operations\HOST_PYTHON_UPGRADE_RUNBOOK.md;night-plans\undated\pyup-phase-c'
```

Also parse every `phase-c-*.ps1` and `raw/*.ps1` with the 5.1 parser (`[System.Management.Automation.Language.Parser]::ParseFile`);
each must report zero errors. Parsing runs nothing.
