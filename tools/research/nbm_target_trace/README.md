# NBM target-period trace (mission 2026-09-82a)

Historical research tool. It owns a serial public-bulletin trace and a diagnostic
census of the pinned 79a export. It never scores, fits, proposes a candidate, or
changes a runtime parser. Read the [handback](../../../docs/roadmap/agent-report-2026-09-82a-workstation-is-the-guidance-read-for-the-right-day.md)
for the verdict and the active-artifact stop condition.

## Method and evidence

1. `run t0`: cache 12 national NOAA NBP files once (three dates, four cycles),
   extract the 11 US settlement-station blocks, preserve every FHR token and its
   UTC validity, and join free IEM daily observations.
2. `run t1`: call the unchanged repository parser for local issue date -1/0/+1.
3. `run t2`: verify the frozen 79a snapshot hash, retain its admission/exclusions,
   join explicit rejection reasons and compare temperatures only.
4. `run artifact_audit`: inspect tracked JSON and trusted repository pickles via
   verified existing LFS objects, without restoring or rewriting artifacts.
5. `run publish`: produce supplementary finite-census evidence; the retained
  source files and aggregates under `evidence/` have a SHA-256 manifest.

Published station blocks normalize line endings and trailing spaces only.
Their national source bytes remain unchanged in the download cache.

Run all stages through `scripts/ops/workstation_heavy.ps1`; the owner approved
only this exact additional module in the wrapper and hook allowlists. No
identity, lease, deadline, or live-stage guard changed. Output stage directories
are create-only; use a fresh scratch root and reuse the existing cache for
reproduction. A partial failed download is preserved and needs review.

The NOAA convention comes from the [NBP key](https://vlab.noaa.gov/web/mdl/nbm-textcard-v5.0):
00Z labels a maximum, 12Z a minimum for these mainland stations. The maximum's
target is the preceding date. The field's physical interval and IEM's daily
summary boundaries are not identical to local-midnight settlement; these
comparisons diagnose period identity, not forecast accuracy or settlement.

Only p25 = p75 - IQR and p10 = p90 - spread are exactly recovered. Missing p50
stays missing. The floor plus floor-gap recovers the recorded representative
high, which the traced code selects as p90 when present and nonzero; it is
explicitly labelled representative, never a recovered median. Signature
agreement with retained bulletins is corroboration, not missing payload
provenance. No finite census interval or forecast population inference is made.

## Reproduce on the workstation

The existing cache and input paths below belong to this mission. No frozen
mirror or production connection is used. The cache hashes/URLs are checked
before reuse; national files are not fetched again.

```powershell
$repo = 'C:/Users/Michael/Documents/github/weather/scratch/w/nbm-target-trace-20260921'
$python = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
$root = 'C:/Users/Michael/Documents/github/weather/scratch/nbm-target-trace-20260921-reproduce-1'
$cache = 'C:/Users/Michael/Documents/github/weather/scratch/nbm-target-trace-20260921/cache'
$input79 = 'C:/Users/Michael/Documents/github/weather/scratch/missing-information-20260921'
function Invoke-NbmTrace([string[]]$Tokens) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
        (ConvertTo-Json -InputObject $Tokens -Compress)))
    & "$repo/scripts/ops/workstation_heavy.ps1" -Kind weather_heavy `
        -PythonPath $python -ArgumentsBase64 $encoded -RepoRoot $repo
    if ($LASTEXITCODE -ne 0) { throw 'Guarded trace failed' }
}
Invoke-NbmTrace @('-m','tools.research.nbm_target_trace.run','t0','--root',$root,'--cache',$cache)
Invoke-NbmTrace @('-m','tools.research.nbm_target_trace.run','t1','--root',$root,'--cache',$cache)
Invoke-NbmTrace @('-m','tools.research.nbm_target_trace.run','t2','--root',$root,'--cache',$cache,
    '--input',"$input79/extracted-1",'--raw',"$input79/unpacked")
Invoke-NbmTrace @('-m','tools.research.nbm_target_trace.run','artifact_audit','--root',$root)
```

Timestamps differ on reproduction. Compare the token/pick/diagnostic rows,
counts, source hashes and artifact selectors with the retained originals.
The `publish` stage is create-only for the checked-in evidence destinations;
do not rerun it over the published bundle.
