"""Night sequencer: emit the landing commands for one night from its hashed night plan.

Master currently writes each night's landing sequence by hand from the workstation's
``landing_night_plan_v0.1`` JSON: one integration attempt per head
(``new_integration_attempt.ps1`` then ``register_integration_attempt.ps1``), with the
gates between units and the fallback head when a unit fails.  This module turns the
plan into three files:

``sequencer-<night>.ps1``
    One script for the whole night.  Production runs it once per unit
    (``-Unit <label>``).  It checks that unit's preconditions and, only with
    ``-Execute``, creates the immutable attempt.  The checks are: exact tip, ``master``
    equal to ``origin/master``, prerequisites landed, ``master`` an ancestor of the
    tip, no running integration task, lease free, binding ``roll_verdict.ps1``, and
    the suite and merge windows.  Suite and merge times are derived at run time with
    the merge-queue driver's rule.  The script **never** registers a task: it prints
    the registration command, because registration needs explicit operator
    authorisation (INTEGRATION_ATTEMPT_RUNBOOK).  A slot with
    ``"landing_path": "direct_rf"`` (roll-free only) is not an attempt but the direct
    guarded merge (bounded suite under the lease, then ``quiet_window_merge.ps1``):
    it is bounded by the 09:00 heavy-work close, not the 03:40 attempt reserve, and
    the script only prints its commands.
``timetable-<night>.md``
    Execution order, the gates and an estimated serial timetable, with every unit
    that would overflow marked: an attempt unit whose merge trigger or suite end is
    past 03:40 (the consumer stops a suite still running at 03:40), or a direct
    unit that would not land by 09:00.
``queue-<night>.draft.json``
    An unsigned ``weather_exact_tip_merge_queue_v1`` draft for the M6 dry pilot.
    Every entry has ``approved: false``.  Only the owner approves and signs.

It reads only the plan file, touches no repository, task, lease or network, and
does not judge heads: the plan's pre-gate receipts and production's own gates do.
Problems it finds in the plan are reported as findings.  Exit codes: 0 written
with no blocking finding, 2 written with blocking findings, 1 refused (an
unreadable plan or a plan-hash mismatch).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from weather.operations.landing_preflight import landing_slots, load_night_plan

QUEUE_SCHEMA = "weather_exact_tip_merge_queue_v1"
EXIT_OK, EXIT_REFUSED, EXIT_FINDINGS = 0, 1, 2

# INTEGRATION_ATTEMPT_RUNBOOK: suite 00:30-09:00; merge 01:00-03:40, >= 30 minutes after the suite.
SUITE_OPEN = timedelta(minutes=30)  # heavy-work window opens
FIRST_SUITE = timedelta(minutes=35)  # earliest real first suite trigger (lease taken after 00:30)
MERGE_OPEN = timedelta(hours=1)
MERGE_RESERVE = timedelta(hours=3, minutes=40)  # bounds an attempt's merge trigger AND its suite end
MIN_SUITE_TO_MERGE = timedelta(minutes=30)
DIRECT_CLOSE = timedelta(hours=9)  # heavy-work window closes: a direct unit must land by then
LANDING_PATHS = ("attempt", "direct_rf")

_SHA40 = re.compile(r"[0-9a-f]{40}")
_ATTEMPT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
_HEAD_PREFIX = re.compile(r"^(?:origin/)?(?:claude|codex)/(?:integration-)?(?:\d{8}-)?")
_PS_SAFE = re.compile(r"^[A-Za-z0-9._/:\\ -]*$")
ROLL_CLASSES = ("ROLL-FREE", "ROLL-FREE-IF-DORMANT", "ROLL-SENSITIVE")


@dataclass
class Unit:
    """One landing unit: a primary slot or a fallback head."""

    label: str
    head: str
    sha: str
    kind: str
    roll_class: str
    attempt_stem: str
    fallback: bool = False
    requires_landed: list[str] = field(default_factory=list)
    pregate: dict[str, Any] = field(default_factory=dict)
    path: str = "attempt"  # "attempt" (integration attempt) or "direct_rf" (direct guarded merge)


@dataclass
class Finding:
    severity: str  # "BLOCK" or "NOTE"
    unit: str
    message: str


def unit_label(head: str) -> str:
    """``claude/integration-20261014-n9-rs-r2`` -> ``n9-rs-r2``."""

    label = _HEAD_PREFIX.sub("", head.strip())
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")
    return label or "head"


def attempt_stem(night: date, label: str) -> str:
    """The attempt id without its ``-a<n>`` suffix; fits ``new_integration_attempt``'s 48-char id."""

    stem = f"{night:%Y%m%d}-{label}"[:44].rstrip("-.")
    if not _ATTEMPT_ID.match(stem + "-a1"):
        raise ValueError(f"cannot form an attempt id from {label!r}")
    return stem


def _stacked_sha(slot: dict[str, Any]) -> str | None:
    match = _SHA40.search(str(slot.get("stacked_on") or "").lower())
    return match.group(0) if match else None


def ps_literal(value: str) -> str:
    if not _PS_SAFE.match(value):
        raise ValueError(f"refusing to emit an unexpected character in {value!r}")
    return "'" + value.replace("'", "''") + "'"


def build_units(plan: dict[str, Any]) -> tuple[list[Unit], list[Finding]]:
    """Primary units in execution order, then fallback heads, plus plan findings."""

    night = date.fromisoformat(str(plan["night"]))
    master_sha = str(plan.get("master_sha") or "").lower()
    findings: list[Finding] = []
    slots = landing_slots(plan)
    order = sorted(range(len(slots)), key=lambda i: (slots[i].get("exec", slots[i].get("priority", i + 1)), i))
    units: list[Unit] = []
    shas: dict[str, str] = {}
    labels: set[str] = set()

    def make(slot: dict[str, Any], fallback: bool) -> Unit:
        head = str(slot.get("head") or slot.get("label"))
        label = unit_label(head)
        if label in labels:
            raise ValueError(f"two units share the label {label!r}")
        labels.add(label)
        roll_class = str(slot.get("expected_roll_class") or "").upper()
        unit = Unit(
            label=label,
            head=head,
            sha=str(slot["sha"]).lower(),
            kind=str(slot.get("kind") or ("fallback" if fallback else "")),
            roll_class=roll_class,
            attempt_stem=attempt_stem(night, label),
            fallback=fallback,
            pregate=dict(slot.get("pregate") or {}),
            path=str(slot.get("landing_path") or "attempt"),
        )
        if roll_class not in ROLL_CLASSES:
            findings.append(Finding("BLOCK", label, f"expected_roll_class {roll_class or 'missing'!r} is not a roll class"))
        if unit.path not in LANDING_PATHS:
            findings.append(Finding("BLOCK", label, f"landing_path {unit.path!r} is not one of {', '.join(LANDING_PATHS)}"))
        elif unit.path == "direct_rf" and roll_class != "ROLL-FREE":
            findings.append(Finding("BLOCK", label, f"landing_path direct_rf needs expected_roll_class ROLL-FREE, not {roll_class or 'missing'!r}"))
        stacked = _stacked_sha(slot)
        if stacked and stacked != master_sha:
            if stacked in shas:
                unit.requires_landed.append(stacked)
            else:
                findings.append(Finding("BLOCK", label, f"stacked on {stacked[:12]}, which is neither master_sha nor an earlier unit"))
        _audit_pregate(unit, master_sha, findings)
        return unit

    for index in order:
        unit = make(slots[index], fallback=False)
        units.append(unit)
        shas[unit.sha] = unit.label
    for entry in plan.get("fallback_heads") or []:
        if not isinstance(entry, dict) or not _SHA40.fullmatch(str(entry.get("sha") or "").lower()):
            raise ValueError(f"fallback head without a 40-hex sha: {entry!r}")
        units.append(make(entry, fallback=True))

    seen_rf = False
    for unit in units:
        if unit.fallback:
            continue
        if unit.roll_class == "ROLL-SENSITIVE" and seen_rf and not unit.requires_landed:
            findings.append(Finding("NOTE", unit.label, "a roll-sensitive unit runs after a roll-free one; the plan's order stands"))
        seen_rf = seen_rf or unit.roll_class.startswith("ROLL-FREE")
    return units, findings


def _audit_pregate(unit: Unit, master_sha: str, findings: list[Finding]) -> None:
    pregate = unit.pregate
    if not pregate:
        findings.append(Finding("BLOCK", unit.label, "no workstation pre-gate in the plan"))
        return
    if pregate.get("verdict") != "PASS":
        findings.append(Finding("BLOCK", unit.label, f"pre-gate verdict is {pregate.get('verdict')!r}, not PASS"))
    if not re.fullmatch(r"[0-9a-f]{64}", str(pregate.get("receipt_sha256") or "")):
        findings.append(Finding("BLOCK", unit.label, "pre-gate receipt_sha256 missing or not 64 hex"))
    if pregate.get("base_is_ancestor") is not True:
        findings.append(Finding("BLOCK", unit.label, "pre-gate base is not recorded as an ancestor of the head"))
    base = str(pregate.get("base") or "").lower()
    if master_sha and base and base != master_sha:
        findings.append(Finding("NOTE", unit.label, f"pre-gate base {base[:12]} differs from plan master_sha {master_sha[:12]} (OD35: re-pregate if master moved)"))


def estimate_timetable(units: Sequence[Unit], night: date, *, suite_minutes: int, land_minutes: int,
                       start: datetime | None = None) -> list[dict[str, Any]]:
    """Serial estimate for the primary units, using the merge-queue driver's rule.

    A unit's attempt can be created only after the previous unit has pushed, because the
    attempt freezes the production baseline.  So the units are strictly serial: the
    first suite at 00:35 (the real first trigger once the lease is taken after 00:30),
    each later suite at the previous landing + 2 minutes.

    Attempt unit: merge at max(suite + 30 minutes, 01:00), landing at
    max(merge, suite end) + land_minutes.  It overflows when the merge trigger is past
    the 03:40 reserve or when its suite would still be running at 03:40 (the consumer
    stops such a suite, so the attempt cannot pass).

    Direct unit (``direct_rf``): bounded suite, then ``quiet_window_merge.ps1`` right
    after it, so merge at the suite end and landing land_minutes later.  03:40 does not
    bind it; it overflows only if it would not land by the 09:00 heavy-work close.
    """

    midnight = datetime.combine(night, datetime.min.time())
    cursor = start or midnight + FIRST_SUITE
    rows = []
    for unit in units:
        if unit.fallback:
            continue
        suite_at = max(cursor, midnight + SUITE_OPEN)
        suite_end = suite_at + timedelta(minutes=suite_minutes)
        reasons: list[str] = []
        if unit.path == "direct_rf":
            merge_at = suite_end
            landed_at = suite_end + timedelta(minutes=land_minutes)
            if landed_at > midnight + DIRECT_CLOSE:
                reasons.append(f"direct landing {landed_at:%H:%M} is past the 09:00 heavy-work close")
        else:
            merge_at = max(suite_at + MIN_SUITE_TO_MERGE, midnight + MERGE_OPEN)
            landed_at = max(merge_at, suite_end) + timedelta(minutes=land_minutes)
            if merge_at > midnight + MERGE_RESERVE:
                reasons.append(f"merge trigger {merge_at:%H:%M} is past the 03:40 reserve")
            if suite_end > midnight + MERGE_RESERVE:
                reasons.append(f"suite end {suite_end:%H:%M} is past 03:40, where the consumer stops it")
        rows.append({
            "label": unit.label,
            "path": unit.path,
            "suite_at": suite_at,
            "suite_end": suite_end,
            "merge_at": merge_at,
            "landed_at": landed_at,
            "overflow": bool(reasons),
            "overflow_reason": "; ".join(reasons),
        })
        cursor = landed_at + timedelta(minutes=2)
    return rows


# --------------------------------------------------------------------------- PowerShell emission

_PS_BODY = r"""
$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0
$inv = [Globalization.CultureInfo]::InvariantCulture
$midnight = [datetime]::ParseExact($Night, "yyyy-MM-dd", $inv)

function Out-Verdict([string]$Verdict, [string]$Reason, [int]$Code) {
    Write-Output ("SEQUENCER night={0} unit={1} VERDICT={2} {3}" -f $Night, $Unit, $Verdict, $Reason)
    exit $Code
}
function Invoke-Git {
    # Windows PowerShell 5.1 turns native stderr into terminating errors under "Stop".
    $ErrorActionPreference = "Continue"
    $out = & $GitExecutablePath -C $RepoRoot @args 2>$null
    return @{ Code = $LASTEXITCODE; Out = ([string](@($out) -join "`n")).Trim() }
}
function Test-Ancestor([string]$Ancestor, [string]$Descendant) {
    return (Invoke-Git merge-base --is-ancestor $Ancestor $Descendant).Code -eq 0
}

$u = @($Units | Where-Object { $_.label -eq $Unit })
if ($u.Count -ne 1) { throw ("Unknown unit '{0}'. Units: {1}" -f $Unit, (($Units | ForEach-Object { $_.label }) -join ", ")) }
$u = $u[0]
if (-not [System.IO.Path]::IsPathRooted($GitExecutablePath) -or -not (Test-Path -LiteralPath $GitExecutablePath -PathType Leaf)) {
    throw "GitExecutablePath must be the absolute reviewed git.exe"
}
$RepoRoot = (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "scripts\ops\new_integration_attempt.ps1"))) {
    throw "Run from the production repository root."
}
if ((Invoke-Git symbolic-ref --quiet --short HEAD).Out -ne "master") { Out-Verdict "STOP" "production is not on master" 4 }

# 1. Exact tip, master == origin/master.
if ((Invoke-Git fetch --quiet --no-auto-maintenance origin).Code -ne 0) { Out-Verdict "WAIT" "git fetch origin failed" 3 }
$tip = (Invoke-Git rev-parse ("origin/" + $u.head)).Out.ToLowerInvariant()
if ($tip -ne $u.sha) { Out-Verdict "STOP" ("origin/{0} is {1}, plan says {2}; the head moved" -f $u.head, $tip, $u.sha) 4 }
$master = (Invoke-Git rev-parse master).Out.ToLowerInvariant()
$originMaster = (Invoke-Git rev-parse origin/master).Out.ToLowerInvariant()
if ($master -ne $originMaster) { Out-Verdict "STOP" "local master $master != origin/master $originMaster" 4 }

# 2. Already landed, prerequisites landed, tree identity.
if (Test-Ancestor $u.sha $master) { Out-Verdict "DONE" ("{0} is already contained in master {1}" -f $u.sha, $master) 0 }
foreach ($need in @($u.requires_landed)) {
    if (-not (Test-Ancestor $need $master)) { Out-Verdict "WAIT" "prerequisite $need has not landed on master" 3 }
}
# Tree identity: master must add nothing the tip has not been tested with. Either master is an
# ancestor of the tip, or every master commit outside the tip is a no-content merge (tree equal to
# its merged parent's) of a head the tip contains -- the guarded merge of an earlier stacked unit.
if (-not (Test-Ancestor $master $u.sha)) {
    $extra = @(((Invoke-Git rev-list $master ("^" + $u.sha)).Out -split "`n") | Where-Object { $_ })
    foreach ($c in $extra) {
        $parents = @(((Invoke-Git rev-list --parents -n 1 $c).Out -split " ") | Select-Object -Skip 1)
        $ok = $parents.Count -eq 2 -and (Test-Ancestor $parents[1] $u.sha) -and
            ((Invoke-Git rev-parse ($c + "^{tree}")).Out -eq (Invoke-Git rev-parse ($parents[1] + "^{tree}")).Out)
        if (-not $ok) {
            Out-Verdict "STOP" "master $master carries $c, which the tip was not tested with: rebuild and re-pregate the head (OD35), or use a fallback unit" 4
        }
    }
    Write-Output ("NOTE: master is not an ancestor of the tip, but its {0} extra commit(s) are no-content merges of heads the tip contains." -f $extra.Count)
}
if ($master -ne $PregateBase -and @($u.requires_landed).Count -eq 0) {
    Write-Output "NOTE: master $master differs from the plan's pre-gate base $PregateBase (ancestry still holds)."
}

# 3. Nothing running: no integration task, no lease.
$running = @(Get-ScheduledTask -TaskName "WeatherIntegration*" -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Running" })
if ($running.Count -gt 0) { Out-Verdict "WAIT" ("integration task running: " + (($running | ForEach-Object { $_.TaskName }) -join ",")) 3 }
. (Join-Path $RepoRoot "scripts\ops\workload_admission.ps1")
$lease = Get-WeatherHeavyWorkloadLeaseState -RepoRoot $RepoRoot
if ($lease.Active) { Out-Verdict "WAIT" "heavy-work lease is held" 3 }

# 4. Binding roll verdict (never derived by hand).
& (Join-Path $RepoRoot "scripts\ops\roll_verdict.ps1") -Branch ("origin/" + $u.head) | Out-Host
$rollCode = $LASTEXITCODE
$rollClass = @{ 0 = "ROLL-FREE"; 2 = "ROLL-FREE-IF-DORMANT"; 3 = "ROLL-SENSITIVE" }[$rollCode]
if (-not $rollClass) { Out-Verdict "STOP" "roll_verdict.ps1 failed (exit $rollCode)" 4 }
if ($rollClass -ne $u.roll_class) {
    if ($u.roll_class -eq "ROLL-SENSITIVE") { Write-Output "NOTE: plan expected ROLL-SENSITIVE; binding verdict is $rollClass." }
    else { Out-Verdict "STOP" ("plan expected {0}; binding verdict is {1}: re-plan the unit" -f $u.roll_class, $rollClass) 4 }
}

# 5. Windows (merge-queue driver rule).
$asOf = $Now.AddMinutes(3)
$suiteAt = $asOf.Date.AddHours($asOf.Hour).AddMinutes($asOf.Minute + 1)
if ($suiteAt -lt $midnight.AddMinutes(35)) { $suiteAt = $midnight.AddMinutes(35) }
$suiteEnd = $suiteAt.AddMinutes($SuiteMinutes)
if ($u.path -eq "direct_rf") {
    # Direct roll-free guarded merge: not an attempt, so the 03:40 reserve does not apply.
    # Its bounded suite holds the heavy-work lease and must land before the 09:00 close.
    $landBy = $suiteEnd.AddMinutes($LandMinutes)
    if ($landBy -gt $midnight.AddHours(9)) {
        Out-Verdict "STOP_FOR_NIGHT" ("direct landing {0:HH:mm} would pass the 09:00 heavy-work close; drop per overflow_drop_order" -f $landBy) 4
    }
    $worktree = Join-Path $WorktreeParent ("{0}-direct" -f $u.attempt_stem)
    $logPath = Join-Path $WorktreeParent ("{0}-direct-suite.log" -f $u.attempt_stem)
    Write-Output ("READY unit={0} head={1} sha={2} roll={3} path=direct_rf suite_from={4} land_by={5}" -f $u.label, $u.head, $u.sha, $rollClass, $suiteAt.ToString("yyyy-MM-ddTHH:mm:ss", $inv), $landBy.ToString("yyyy-MM-ddTHH:mm:ss", $inv))
    Write-Output "Commands (direct roll-free path; this script runs none of them, even with -Execute):"
    Write-Output ("  a) git worktree add --detach `"{0}`" {1}" -f $worktree, $u.sha)
    Write-Output ("  b) .\scripts\ops\bounded_worktree_test_suite.ps1 -RepoRoot `"{0}`" -WorktreeRoot `"{1}`" -ExpectedTip {2} -BranchRef origin/{3} -LogPath `"{4}`"   (takes the heavy-work lease)" -f $RepoRoot, $worktree, $u.sha, $u.head, $logPath)
    Write-Output ("  c) .\scripts\ops\quiet_window_merge.ps1 -Branch origin/{0} -ExpectedTip {1}   (only after b passes)" -f $u.head, $u.sha)
    Out-Verdict "READY" "direct path; nothing created" 0
}
$mergeAt = $suiteAt.AddMinutes(30)
if ($mergeAt -lt $midnight.AddHours(1)) { $mergeAt = $midnight.AddHours(1) }
if ($mergeAt -gt $midnight.AddHours(3).AddMinutes(40)) {
    Out-Verdict "STOP_FOR_NIGHT" ("merge trigger {0:HH:mm} would pass the 03:40 reserve; drop per overflow_drop_order" -f $mergeAt) 4
}
if ($suiteEnd -gt $midnight.AddHours(3).AddMinutes(40)) {
    Out-Verdict "STOP_FOR_NIGHT" ("suite would end {0:HH:mm} ({1} min), past 03:40 where the consumer stops it; drop per overflow_drop_order" -f $suiteEnd, $SuiteMinutes) 4
}

# 6. Attempt identity and paths.
$attemptId = "{0}-a{1}" -f $u.attempt_stem, $Attempt
$attemptParent = Join-Path $RepoRoot ("data\integration_attempts\" + $Night)
$attemptRoot = Join-Path $attemptParent $attemptId
if (Test-Path -LiteralPath $attemptRoot) { Out-Verdict "STOP" "attempt root exists: $attemptRoot (use -Attempt <n+1> after review)" 4 }
$worktree = Join-Path $WorktreeParent $attemptId
$suiteText = $suiteAt.ToString("yyyy-MM-ddTHH:mm:ss", $inv)
$mergeText = $mergeAt.ToString("yyyy-MM-ddTHH:mm:ss", $inv)
$review = "night plan {0} sha256 {1}; pre-gate receipt {2}" -f $Night, $PlanSha256, $u.pregate_receipt_sha256

Write-Output ("READY unit={0} head={1} sha={2} roll={3} attempt={4} suite={5} merge={6}" -f $u.label, $u.head, $u.sha, $rollClass, $attemptId, $suiteText, $mergeText)
if (-not $Execute) {
    Write-Output "Commands (-Execute runs steps a-b; c is never run by this script):"
    Write-Output ("  a) git worktree add --detach `"{0}`" {1}" -f $worktree, $u.sha)
    Write-Output ("  b) .\scripts\ops\new_integration_attempt.ps1 -AttemptRoot `"{0}`" -AttemptId {1} -BranchRef origin/{2} -WorktreeRoot `"{3}`" -ExpectedTip {4} -GitExecutablePath `"{5}`" -SuiteAtLocal {6} -MergeAtLocal {7} -ReviewReference `"{8}`"" -f $attemptRoot, $attemptId, $u.head, $worktree, $u.sha, $GitExecutablePath, $suiteText, $mergeText, $review)
    Write-Output ("  c) .\scripts\ops\register_integration_attempt.ps1 -ManifestPath `"{0}\manifest.json`" -ExpectedManifestSha256 <printed by b>   (operator-authorised Scheduler change)" -f $attemptRoot)
    Out-Verdict "READY" "dry; nothing created" 0
}

if (-not (Test-Path -LiteralPath $worktree)) {
    if ((Invoke-Git worktree add --quiet --detach $worktree $u.sha).Code -ne 0) { Out-Verdict "STOP" "git worktree add failed" 4 }
}
New-Item -ItemType Directory -Path $attemptParent -Force | Out-Null
$created = & (Join-Path $RepoRoot "scripts\ops\new_integration_attempt.ps1") -AttemptRoot $attemptRoot -AttemptId $attemptId `
    -BranchRef ("origin/" + $u.head) -WorktreeRoot $worktree -ExpectedTip $u.sha -GitExecutablePath $GitExecutablePath `
    -SuiteAtLocal $suiteAt -MergeAtLocal $mergeAt -ReviewReference $review 6>&1 | ForEach-Object { [string]$_ }
$created | Out-Host
$shaLine = @($created | Where-Object { $_ -like "Manifest SHA256: *" })
if ($shaLine.Count -ne 1) { Out-Verdict "STOP" "attempt creation printed no manifest SHA256" 4 }
$manifestSha = $shaLine[0].Substring("Manifest SHA256: ".Length).Trim()
Write-Output "Register only with operator authorisation:"
Write-Output ("  .\scripts\ops\register_integration_attempt.ps1 -ManifestPath `"{0}\manifest.json`" -ExpectedManifestSha256 {1}" -f $attemptRoot, $manifestSha)
Out-Verdict "CREATED" "attempt $attemptId frozen; registration not performed" 0
"""


def render_powershell(plan: dict[str, Any], plan_sha: str, units: Sequence[Unit], *, suite_minutes: int = 52,
                      land_minutes: int = 8) -> str:
    night = str(plan["night"])
    base = str((units[0].pregate.get("base") if units else "") or plan.get("master_sha") or "").lower()
    lines = [
        f"# Generated by python -m weather.operations.night_sequencer from landing_night_plan {night}.",
        f"# plan_sha256 {plan_sha}. Regenerate from the plan; do not hand-edit.",
        "# Run from the production repository root, once per unit, in the order of $Units.",
        "# Without -Execute it is read-only apart from 'git fetch origin'. With -Execute it creates",
        "# the worktree and the immutable attempt. It never registers, starts or stops a task.",
        "[CmdletBinding()]",
        "param(",
        "    [Parameter(Mandatory = $true)][string]$Unit,",
        "    [Parameter(Mandatory = $true)][string]$WorktreeParent,",
        "    [Parameter(Mandatory = $true)][string]$GitExecutablePath,",
        "    [ValidateRange(1, 9)][int]$Attempt = 1,",
        "    [switch]$Execute,",
        "    [datetime]$Now = (Get-Date),",
        f"    [ValidateRange(1, 240)][int]$SuiteMinutes = {int(suite_minutes)},",
        f"    [ValidateRange(0, 120)][int]$LandMinutes = {int(land_minutes)}",
        ")",
        f"$Night = {ps_literal(night)}",
        f"$PlanSha256 = {ps_literal(plan_sha)}",
        f"$PregateBase = {ps_literal(base)}",
        "$Units = @(",
    ]
    for unit in units:
        requires = ", ".join(ps_literal(sha) for sha in unit.requires_landed)
        fields = [
            f"label = {ps_literal(unit.label)}",
            f"head = {ps_literal(unit.head)}",
            f"sha = {ps_literal(unit.sha)}",
            f"roll_class = {ps_literal(unit.roll_class)}",
            f"path = {ps_literal(unit.path)}",
            f"attempt_stem = {ps_literal(unit.attempt_stem)}",
            f"fallback = ${'true' if unit.fallback else 'false'}",
            f"requires_landed = @({requires})",
            f"pregate_receipt_sha256 = {ps_literal(str(unit.pregate.get('receipt_sha256') or 'missing'))}",
        ]
        lines.append("    [PSCustomObject]@{ " + "; ".join(fields) + " }")
    lines.append(")")
    return "\r\n".join(lines) + _PS_BODY.replace("\n", "\r\n")


def render_timetable(plan: dict[str, Any], plan_sha: str, units: Sequence[Unit], rows: Sequence[dict[str, Any]],
                     findings: Sequence[Finding], suite_minutes: int, land_minutes: int) -> str:
    night = str(plan["night"])
    out = [
        f"# Night sequence {night}",
        "",
        f"Generated from `{plan.get('label') or night}`, plan_sha256 `{plan_sha}`.",
        "This is an estimate and binds nothing. The binding gates are the sequencer's run-time checks and production's own.",
        "",
        "| Exec | Unit | Head | Tip | Expected class | Path | Requires landed | Pre-gate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, unit in enumerate(units, 1):
        exec_cell = "fallback" if unit.fallback else str(index)
        requires = ", ".join(f"`{s[:9]}`" for s in unit.requires_landed) or "-"
        pregate = f"{unit.pregate.get('verdict', 'missing')} `{str(unit.pregate.get('receipt_sha256') or '')[:12]}`"
        out.append(f"| {exec_cell} | {unit.label} | `{unit.head}` | `{unit.sha[:9]}` | {unit.roll_class} | {unit.path} | {requires} | {pregate} |")
    out += ["", f"Estimated serial timetable (suite {suite_minutes} min, merge-to-pushed {land_minutes} min):", "",
            "| Unit | Path | Suite at | Suite end | Merge at | Landed by | Overflow |",
            "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        out.append(f"| {row['label']} | {row['path']} | {row['suite_at']:%H:%M} | {row['suite_end']:%H:%M} | "
                   f"{row['merge_at']:%H:%M} | {row['landed_at']:%H:%M} | "
                   f"{'YES: ' + row['overflow_reason'] if row['overflow'] else 'no'} |")
    drop = (plan.get("schedule") or {}).get("overflow_drop_order")
    if drop:
        out += ["", "Overflow drop order (plan): " + "; ".join(str(d) for d in drop)]
    fallback_note = (plan.get("schedule") or {}).get("rs_failure_fallback")
    if fallback_note:
        out += ["", f"Fallback (plan): {fallback_note}"]
    light = plan.get("docs_light_path") or []
    if light:
        out += ["", "Docs light path entries (master decides the path; check only):", ""]
        for entry in light:
            out.append(f"- `.\\scripts\\ops\\docs_light_path.ps1 -Branch {entry.get('branch')} -ExpectedTip {entry.get('sha')} -CheckOnly`")
    out += ["", "Per unit, on production (repository root):", "",
            "```powershell",
            f".\\sequencer-{night}.ps1 -Unit <label> -WorktreeParent <host worktree parent> -GitExecutablePath <reviewed git.exe>",
            "# READY -> rerun with -Execute, then register with the printed command (operator authorisation)",
            "```", "", "Findings:", ""]
    out += [f"- {f.severity} {f.unit}: {f.message}" for f in findings] or ["- none"]
    return "\n".join(out) + "\n"


def render_queue(plan: dict[str, Any], plan_sha: str, units: Sequence[Unit], receipts: dict[str, tuple[str, str]]) -> str:
    entries = []
    for order, unit in enumerate((u for u in units if not u.fallback), 1):
        receipt, receipt_sha = receipts.get(unit.label, ("receipts/<landing preflight receipt>", "0" * 64))
        entries.append({
            "order": order,
            "branch": f"origin/{unit.head}",
            "expected_tip": unit.sha,
            "roll_class": unit.roll_class if unit.roll_class in ("ROLL-FREE", "ROLL-SENSITIVE") else "ROLL-SENSITIVE",
            "approved": False,
            "approval_ref": "",
            "preflight_receipt": receipt,
            "preflight_receipt_sha256": receipt_sha,
        })
    queue = {
        "schema_version": QUEUE_SCHEMA,
        "night": str(plan["night"]),
        "base_sha": str(plan.get("master_sha") or "0" * 40).lower(),
        "plan_sha256": plan_sha,
        "on_failure": "stop_night",
        "note": "UNSIGNED DRAFT from night_sequencer. roll_class is the plan's static class; confirm with roll_verdict.ps1. "
                "Only the owner sets approved and signs.",
        "entries": entries,
    }
    return json.dumps(queue, indent=2) + "\n"


def _parse_receipts(values: Sequence[str], queue_dir: Path) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for value in values:
        label, sep, path_text = value.partition("=")
        if not sep:
            raise ValueError(f"--preflight-receipt must be <unit label>=<path>, got {value!r}")
        path = Path(path_text)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            rel = path.resolve().relative_to(queue_dir.resolve()).as_posix()
        except ValueError:
            rel = f"receipts/{path.name}"
        out[label.strip()] = (rel, digest)
    return out


def generate(plan_path: Path, out_dir: Path, *, expect_sha256: str | None = None, suite_minutes: int = 52,
             land_minutes: int = 8, receipts: Sequence[str] = ()) -> dict[str, Any]:
    plan, plan_sha, file_sha = load_night_plan(plan_path, expect_sha256)
    units, findings = build_units(plan)
    night = date.fromisoformat(str(plan["night"]))
    rows = estimate_timetable(units, night, suite_minutes=suite_minutes, land_minutes=land_minutes)
    for row in rows:
        if row["overflow"]:
            findings.append(Finding("NOTE", row["label"], f"estimated overflow: {row['overflow_reason']}"))
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        f"sequencer-{night}.ps1": render_powershell(plan, plan_sha, units, suite_minutes=suite_minutes,
                                                    land_minutes=land_minutes),
        f"timetable-{night}.md": render_timetable(plan, plan_sha, units, rows, findings, suite_minutes, land_minutes),
        f"queue-{night}.draft.json": render_queue(plan, plan_sha, units, _parse_receipts(receipts, out_dir)),
    }
    for name, text in files.items():
        # The .ps1 carries a UTF-8 BOM so Windows PowerShell 5.1 never reads it as ANSI.
        (out_dir / name).write_bytes((b"\xef\xbb\xbf" if name.endswith(".ps1") else b"") + text.encode("utf-8"))
    return {
        "night": str(night),
        "plan_sha256": plan_sha,
        "plan_file_sha256": file_sha,
        "units": [u.label for u in units],
        "files": sorted(str(out_dir / name) for name in files),
        "findings": [f.__dict__ for f in findings],
        "blocking": any(f.severity == "BLOCK" for f in findings),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m weather.operations.night_sequencer", description=__doc__.splitlines()[0])
    parser.add_argument("--plan", required=True, type=Path, help="landing_night_plan_v0.1 JSON")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--expect-plan-sha256", help="content or file sha256 the plan must have")
    parser.add_argument("--suite-minutes", type=int, default=52, help="estimated bounded-suite duration (estimate only)")
    parser.add_argument("--land-minutes", type=int, default=8, help="estimated merge-to-pushed time (estimate only)")
    parser.add_argument("--preflight-receipt", action="append", default=[], metavar="LABEL=PATH",
                        help="landing preflight receipt for the queue draft; repeatable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = generate(args.plan, args.out_dir, expect_sha256=args.expect_plan_sha256, suite_minutes=args.suite_minutes,
                           land_minutes=args.land_minutes, receipts=args.preflight_receipt)
    except (OSError, ValueError, KeyError) as exc:
        print(f"night_sequencer: REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(json.dumps(summary, indent=2))
    return EXIT_FINDINGS if summary["blocking"] else EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
