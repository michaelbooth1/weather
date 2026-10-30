# Generic nested-LOYO history screen (lane L3, 2026-10-30)

Status: research tool, master YES via coordinator 2026-10-30. Not a gate, not a
release input, not serve code.

`python -m weather.calibration.loyo_screen run` scores one candidate feature
column against a fixed control arm on the 2021-2025 history archives and writes
`{name}_loyo.json` plus `{name}_loyo_rows.jsonl`:

- input: a parquet or jsonl column keyed on (market, date, local hour); rows
  dated after 2026-09-29, duplicate keys and non-integer hours are refused;
- the fit: nested leave-one-year-out through
  `weather.calibration.spread_information_rung.rs_loyo` (the R-S / R-Q
  machinery), currently only the control arm `P3d_N_fix` with the `scale`
  mechanism;
- the score: per-row Brier and log, candidate minus control (dR), with a
  date-clustered bootstrap interval in exactly the draw order of
  `spread_information_rung.loyo_summary` (seeded, 2,000 draws by default);
- the output: rows, coverage of the column on the training frame, per-hour dR
  and a verdict line under a rule the caller declares (for example
  `upper<0`). Optionally, `--control-rows` refuses the run unless the control
  arm reproduces a published control row set within 1e-9.

`spread_information_rung` is not on master. The harness imports it lazily and
refuses with the branch name (`claude/rq-run-env-20261029`) when it is absent.

## What a screen can kill

A candidate whose pooled history dR interval does not clear the declared rule
under the same nested LOYO that produced the control. If information in the
column does not improve the 2021-2025 out-of-year Brier, no forward test is
needed to drop it.

## What a screen cannot show

- **History only.** The archives are reconstructed features, not captured
  serve-time inputs. A pass says nothing about dev or forward dates and is not
  edge over market prices.
- **No serve parity.** The column is joined by key. Nothing checks that the
  same value is available, with the same definition, at serve time.
- **No forward cutoff effects.** Effective WU print cutoffs, publication
  latency and late or missing feeds are not exercised. A column that leaks
  post-cutoff information passes easily.
- **Multiplicity.** Every screen spends a look at the same history. Across
  many screens, some will pass the rule by chance. A pass is a reason to
  pre-register a confirmation, not a finding. Record each screen and its rule
  before running it.
- **One mechanism.** Only the `scale` mechanism on `P3d_N_fix` exists. A
  failure here does not rule out a column that would help through another
  mechanism or another control.
