# Master ruling (b): post-look serial-correlation analysis of B

**Master's ruling, verbatim.** Relayed by WS coordinator from master message 2026-10-31T00:23Z. Committed by lane L8
on 2026-10-31 before any post-look code exists. This is a dated research note, not canonical guidance, and not an
owner decision. B stays as bound.

> (b) Master ruling, recorded after (a): after B's look, master runs a separate post-look analysis of B's forward d
> (lag-1 ρ plus an AR(1)-adjusted interval). If that adjusted bound is ≥ 0, a B PASS goes to the owner as "PASS,
> fragile under serial correlation". The verdict stays B's own; its next step is PT-1 on fresh dates either way. A
> FAIL or INCONCLUSIVE is unaffected, since under-coverage only makes PASS easier.

## Context relayed in the same message

- B's interval is the fixed-market, date-clustered percentile (`docs/operations/B_FORWARD_TEST_DESIGN.md` line 148).
- B's PASS is U < 0 (line 160).
- B's false-PASS rate of 0.025 (line 304) assumes independent dates.

The evidence behind the ruling is ledger rows 83-84 (`docs/research/iterate-faster-2026-10-30/b-pair-serial-rho-dev.md`
on `origin/claude/b-pair-serial-rho-20261031` @ `2eeddedfcc83104eb52998c6cd9c08c9e4a594ad`).

## Parameters (master's final ruling, verbatim)

**Master's parameters, verbatim, 10-31.** Relayed by the WS coordinator. They replace the coordinator's earlier
proposal (which used 1.96 and a ρ floor of 0). "Your version" below refers to that coordinator proposal.

> 1. ρ: sample lag-1 autocorrelation in date order, pairing only consecutive calendar dates (agreed), computed on the per-date LINEARISED residual, not the raw date mean. Because B is a mean over equal cells and dates can have unequal cell counts, use e_t = (S_t − Δ·n_t)/n̄, where:
> - S_t = the sum of cell differences on date t;
> - n_t = that date's cell count;
> - n̄ = the mean cell count;
> - Δ = B's own printed point estimate.
>
> This reduces to your version when every date has equal cells. VAR(1) is descriptive only (agreed).
> 2. CHANGE: ρ_used = min(0.9, max(ρ̂, 0.22)). The floor is the dev-measured B-shaped ρ (row 83, 0.219), not 0. A 45-date ρ̂ is biased low (T+1's null sim showed it), and T+1 uses the same floor-at-plan logic.
> 3. CHANGE: U_adj = Δ + t(0.975, n−1) · SD(e)/√n · √VIF, where:
> - VIF = max(1, (1+ρ_used)/(1−ρ_used), block-3 ratio²), with the block-3 ratio computed on e_t and re-centred (row 84's fix);
> - the centre is B's printed Δ;
> - t replaces 1.96 (one-sided 0.025, small-n).
> 4. Agreed, plus one label:
> - "PASS, fragile under serial correlation" iff B PASS AND U_adj ≥ 0;
> - "NOT-WORSE, fragile" iff B's INCONCLUSIVE carries NOT-WORSE AND U_adj ≥ +0.0027;
> - FAIL and other INCONCLUSIVE pass through untouched;
> - B's verdict itself is never altered.
>
> Tests: synthetic iid, AR(1) at 0.22 and 0.5, the row 84 VAR(1) case, and unequal cells per date.

B's NOT-WORSE label is defined at `docs/operations/B_FORWARD_TEST_DESIGN.md` line 162: INCONCLUSIVE "labelled
**NOT-WORSE** when U < +0.0027 (owner Q4)". In `src/weather/calibration/b_scorer.py` (origin/master
`1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`), `decide()` emits it as `verdict == "INCONCLUSIVE"` with
`label == "NOT-WORSE"`, and `MARGIN = 0.0027`.

## Freeze status

**FROZEN 2026-10-31 at commit `fa380db09980692f6afe50eb48b949b6c21aa88a`.** The pins:

- `src/weather/calibration/b_post_look_serial.py` sha256
  `0c485d6e347dc11c95a7cf756e760e292db12536e663c61c1eda5d9650d80bed`;
- `tests/calibration/test_b_post_look_serial.py` sha256
  `7ceb952c1b40f9911ac2260f72428c8d24c96a302c4731cad4321359f137414f`.

Any later change to either file is a new revision and needs a new ruling.

**Master's OK on the implementation choices (a)-(f), verbatim, relayed by the coordinator 2026-10-31:** "(a)-(f) are
all OK as written. (b) is correct: 3·var(block means)/var(e) is MBB variance over iid variance, and the re-centring
follows row 84."

The choices (a)-(f) are:
- (a) ρ̂ is the mean over consecutive-calendar-date pairs of (e_t−ē)(e_{t+1}−ē), divided by the ddof-0 variance of e.
  A gap breaks a pair.
- (b) block-3 ratio² = 3·var(block means)/var(e), both ddof 0. These are exact moving blocks, re-centred, with no
  resampling. Gaps are ignored for blocks.
- (c) SD(e) uses ddof 1.
- (d) The extra refusals:
  - fewer than 3 dates, or fewer than 2 consecutive pairs;
  - a bad date or cell count, or a non-finite S;
  - zero variance;
  - Δ ≠ ΣS/Σn (to 1e-9);
  - a verdict outside PASS, FAIL and INCONCLUSIVE;
  - an existing `--out`.
- (e) The VAR(1) on the 07-12 and 13-16 tables is descriptive only.
- (f) Input is JSON `{"primary": [...], "splits": {...}}` plus `b_look.json` or its decision object.

## Synthetic test runs (module sha256 `0c485d6e347dc11c95a7cf756e760e292db12536e663c61c1eda5d9650d80bed`)

The coordinator's new-module check passed on 2026-10-31. Both runs below were admitted by the coordinator.

The candidate was at commit `fa380db09980692f6afe50eb48b949b6c21aa88a`, with test file sha256
`7ceb952c1b40f9911ac2260f72428c8d24c96a302c4731cad4321359f137414f`. Synthetic data only, so no ledger row is needed
(coordinator).

Both runs used `workstation_heavy.ps1 -Kind pytest -Queue -MinAvailableMemoryGB 3` and ran
`pytest -q -p no:cacheprovider tests/calibration/test_b_post_look_serial.py` from `C:\wt\blook`.

1. Basetemp `C:\t\l8blook\bt-20261030T230123`: **39 passed, 1 setup error** (WinError 3), exit 1, 4.73 s.
   - The parent `C:\t\l8blook` did not exist, so `test_cli_writes_once_and_refuses_overwrite` (the only tmp_path
     test) could not create its basetemp.
   - This was an environment error, not a code failure.
2. Retry, after creating `C:\t\l8blook`; basetemp `C:\t\l8blook\bt-20261030T230151`: **40 passed**, exit 0, 4.51 s.

After both runs, the basetemp and the then-empty `C:\t\l8blook` were deleted.

## Per-date extractor (ruling (i)): synthetic test run — NOT frozen

Candidate: `src/weather/calibration/b_look_per_date.py` sha256
`a28d2e65e8ae0ca4239bec7b641ed4d0fcb3758d2e31c6970a2ed29b68762d66` and its tests
`tests/calibration/test_b_look_per_date.py` sha256 `92f738efb732d03f8ecee0453bb0dee131fc5afbde47d297535d343f15c9b23b`,
both at commit `818232cfd8b5b3b06bf6235ac450b2ac49413f38`.

- The coordinator's new-module check passed. One deviation is flagged to master: the module writes beside B's look,
  as "receipted with B's look" requires, rather than only under its own out dir.
- One queued run was admitted. It used `workstation_heavy.ps1 -Kind pytest -Queue -MinAvailableMemoryGB 3` with
  basetemp `C:\t\l8blook\bt-20261030T230640`: **15 passed**, exit 0, 5.61 s. Afterwards the basetemp and
  `C:\t\l8blook` were deleted.

**FROZEN 2026-10-31 at commit `818232cfd8b5b3b06bf6235ac450b2ac49413f38`.** The pins:

- `src/weather/calibration/b_look_per_date.py` sha256
  `a28d2e65e8ae0ca4239bec7b641ed4d0fcb3758d2e31c6970a2ed29b68762d66`;
- `tests/calibration/test_b_look_per_date.py` sha256
  `92f738efb732d03f8ecee0453bb0dee131fc5afbde47d297535d343f15c9b23b`.

Any later change to either file is a new revision.

Conditions met before the freeze:
- Master answered (A)-(C) (`look-chain-clarification-DRAFT.md` §4).
- Allowlist commit `d33921025266c0e96794857640da53e5a3272787` was verified by the coordinator.
- Both queued ratchet runs passed:
  - `tests/operations/test_r0_full_year_admission.py`: 2 passed, basetemp `C:\t\l8blook\bt-20261030T230806`;
  - `tests/operations/test_loss_atlas_admission.py` (the ps1 mirror proof): 2 passed, basetemp
    `C:\t\l8blook\bt-20261030T230837`.
- Each basetemp and `C:\t\l8blook` were deleted afterwards.
