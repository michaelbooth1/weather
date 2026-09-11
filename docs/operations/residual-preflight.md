# Frozen residual reproduction and synthetic power preflight

Status: canonical contract for the isolated research lineage. The entry point
is `weather.calibration.residual_preflight`. This is a no-fit reproduction
and planning tool; it creates no candidate, new evaluation, promotion or order.

## Scope and execution

The tool accepts only the reviewed frozen 2024 baseline/challenger pair and
the predeclared first/last 2025 evaluation record in each of the twelve markets.
The source, model, training receipt, terminal report, prediction file and
selection identities are checked before use. The tolerance was fixed at
1e-10 native units, with zero relative tolerance, before prediction values
were examined.

Run through the exact non-capture workstation's
`scripts/ops/workstation_heavy.ps1` with Kind `weather_heavy`, the project
interpreter, and the JSON argument array encoded in ArgumentsBase64:

~~~json
["-m", "weather.calibration.residual_preflight", "--manifest", "<absolute-manifest.json>", "--manifest-sha256", "<sha256>", "--output-root", "<checkout>/scratch/residual_preflight/<new-attempt>"]
~~~

Both the controlling launch hook and the workstation admission list must
declare this exact module through reviewed source adoption first. The wrapper
retains host/principal verification, the shared live/heavy mutex and complete
child-tree containment. Its child flag is a prerequisite, not independent
authority. The controller's production timetable still applies on that host.
Deterministic tests use only synthetic fixtures under admitted pytest.

An output root must be new and inside this checkout's ignored
`scratch/residual_preflight/`. Every attempt retains a start receipt and
terminal JSON/Markdown. Existing attempts cannot be overwritten. A clean
checkout does not contain the frozen corpus, model images or attempt receipts.

## Manifest and byte binding

The registered `residual_preflight_manifest` contains:

- The exact mode, `new_outcome_access: false` and `fitting_authorized: false`.
- Absolute paths, byte counts and SHA-256 values for the fixed selection,
  training receipt, terminal report, prediction file and two named model arms.
- The explicit handed-off corpus root. Its 24 normalized CSV bindings come
  from the already-frozen terminal report, not a new directory search.
- The complete producer-file list and current dependency metadata/RECORD
  bindings, using the corresponding fields in the CLI owner.
- A bounded synthetic configuration: seed, replicates, batch size, fixed
  effect/date grids, planning hurdle and HAC lag setting.

Inputs reject symlinks/reparse points, malformed hashes, size changes,
duplicate JSON keys and nonfinite values. Small inputs are capped at 1 MiB;
each feature CSV at 16 MiB and their total at 384 MiB. Original bytes are
verified before parsing. Both model images are checked before either is
deserialized, and the deserialization boundary rechecks the exact model hash.

The current NumPy, SciPy, pandas and scikit-learn metadata and RECORD files
are bound before scientific imports. Recorded runtime .py/.pyd/.dll files
are checked against RECORD, with a 128 MiB per-file, 1 GiB total and 12,000-file
ceiling. This binds the current environment; it does not reconstruct an
unrecorded original training environment or certify omitted caches,
transitive packages or the OS runtime. Actual imported repository paths and
source hashes are retained separately.

## Frozen reproduction

Only date/market membership is inspected before converting selected feature
values. Excluded precipitation probability and unselected value columns do
not enter feature construction. The selected rows preserve native C/F units,
fixed-lead provenance, leads 1–7, and exact hourly uniqueness. The original
summary and feature-vector functions are reused without changing them;
prediction uses the frozen primary leads 2–7.

The retained prediction reader uses only selected identities, units, anchors
and the two primary predictions. It does not use outcome values. A second
load of the exact baseline must give a bitwise-identical prediction array.
One-byte same-length source, model and feature substitutions must fail.
The output records all 24 differences, feature-vector hashes, maximum
difference, source/input scope and the current process's OS peak memory.

A successful reproduction establishes numerical continuity on previously
evaluated records. Its three date clusters do not establish skill or
confirmatory support.

## Synthetic uncertainty and power

The loss difference is baseline squared error minus challenger squared error
in Celsius-equivalent squared units. Positive means improvement. Every
variance component is an assumption; no prior outcome or residual values
are used to estimate it.

The fixed grid spans 60/120/240 dates and effects 0/0.10/0.25/0.50. It compares
independent dates, persistent date shocks, persistent market differences,
and a fixed eight-market population with larger second-half variability.
The eight-market case omits four markets throughout; it cannot support
a twelve-market conclusion or arbitrary missingness.

Three intervals are compared:

- Intercept-only date plus market minus cell CRV1 with finite-sample factors.
- The same construction with a seven-lag Bartlett HAC date component.
- A Gaussian benchmark using the exact covariance of the artificial process.

The first two use a t critical value with the smaller cluster count minus one.
The HAC combination and finite-cluster choice are candidate methods, not an
adopted prospective test. The [multiway-clustering paper](https://cameron.econ.ucdavis.edu/research/JBESpaper2009version.pdf)
and [two-group covariance reference](https://www.statsmodels.org/dev/generated/statsmodels.stats.sandwich_covariance.cov_cluster_2groups.html)
motivate the additive combination; the
[Bartlett HAC reference](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html)
describes the lag weighting. Their combination here must earn its own
qualification.

Nonpositive variance refuses inference without clipping. Reports include
unconditional false-positive rates, 95% coverage, invalid fractions,
valid-only coverage, Wilson Monte Carlo intervals and power for positive
and above-hurdle lower bounds. The 0.25 hurdle is a planning sensitivity.
A prespecified diagnostic screen requires no invalid variance, a false-positive
Wilson upper bound at most .075 and a coverage Wilson lower bound at least
.925. Passing that screen adopts no method and spends no confirmatory alpha.

The exact-covariance benchmark tests the simulation itself. Persistent market
variation supplies a floor that more dates alone cannot remove. No required
real sample size is inferred from this artificial grid.

## Decision boundary and verification

`PREFLIGHT_COMPLETE_PROTOCOL_NOT_READY` means the bounded work ran and the
numerical control reproduced. It does not qualify unseen support or extend
a May–August model into another season. The prospective blockers remain
`SOURCE_TIMING_UNQUALIFIED` and `SEASON_EXTENSION_UNJUSTIFIED` until a
separately reviewed evidence/protocol package resolves them.
A failed byte, source, prediction or execution contract is
`REPRODUCTION_BLOCKED`, with the failing phase retained.

Tests in `tests/calibration/test_residual_preflight.py` cover fixed artifact
refusal before deserialization, source/input substitutions, native units,
duplicate selected hours, ignored outcome values, dependency-file changes,
independent scalar covariance algebra, invalid variance, the known Gaussian
covariance, power direction, create-new output and actual imported paths.
Run owner, schema, import architecture and module-size checks before publication.

## Update when

Update with changed fixed-pair scope, input/output schemas or bounds,
reproduction tolerance, simulation assumptions, covariance candidates,
execution admission or prospective qualification criteria. Dated progress
belongs in the research lineage's numbered model-BOM owner.
