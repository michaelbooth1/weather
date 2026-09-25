# Workstation handoff 2026-09-89a — build the fill-toxicity desk-study tool

Written 2026-09-23 by the production agent. Forward-plan item 5. **Build and test only on the workstation; the production
agent runs it on the production host inside 00:30-09:00 under the lease**, because the execution tape, book tape,
observation triggers and settlement ledger it reads live only there (the workstation mirror stopped 2026-08-12).

## 1. What is frozen

Read first, from `origin/codex/reward-test-attended-handoff-20260921`:
`docs/research/fill-toxicity-desk-study-preregistration-2026-09-23.md` (the design, estimands, exclusions, thresholds and
kill rule) and `docs/research/fill-toxicity-R-rule-2026-09-23.md` (`R`). **Implement them exactly; change nothing.** If
something is ambiguous or impossible, stop and report it — do not choose.

## 2. Build (branch `codex/fill-toxicity-desk-study-20260923`)

Base: the existing markout tool on `origin/codex/execution-tape-markout-20260919` (`execution_tape_markout.py`, its
date-clustered bootstrap, duplicate-collapse rule and `MIN_DATE_CLUSTERS = 10`), merged onto current `origin/master`.

1. The simulated slow quote (d = 1.5 c, sensitivity 2.5 c; repriced only at each book sample; conservative and optimistic
   fill rules) and its markouts at +1/+5/+30 minutes and settlement.
2. Event windows E1-E5 and the placebo exactly as frozen, with per-station routine METAR minutes **measured from our own
   snapshots** (never a fixed :52).
3. The latency sub-study (fraction of the 30-minute move done by our detection time).
4. Estimands, exclusions, inference and the `PULL_SUPPORTED` / `PULL_NOT_THE_LEVER` / `INCONCLUSIVE` /
   `UNDERPOWERED` verdicts, plus `R` and net pull value per band-day with the frozen `R` rule.
5. **Resource bounds for the capture host:** streaming reads one date at a time, bounded memory (report peak), no directory
   walks outside the named per-event paths, `--max-dates`, `--dry-run` that lists inputs and sizes without reading tape
   content, and output only to a named directory outside `data/`.

## 3. Tests

Synthetic tapes covering: fills through/at price, repricing only at samples, each event class and placebo assignment,
exclusions, settlement fallback flagging, bootstrap determinism with the fixed seed, the under-10-cluster rule, the `R`
rule including zero-reward minutes, and memory bounds on a large synthetic date. **No real tape is read on the workstation.**

## 4. Report and boundaries

`docs/roadmap/agent-report-2026-09-89a-fill-toxicity-desk-study-tool.md`: verdict first; the exact CLI the production agent
will run (with `--dry-run` first); test counts; memory profile; the tip. No `.env`, no credentials, no RE-1 worktree or
campaign root, nothing heavy after 19:00 ET on 2026-09-23 (session 2 runs from 20:00). Pushing the branch is authorized.
