# Workstation handoff 2026-09-83a — read the NBM guidance for the right day

Host: the 32 GB workstation (non-capture). Issued by the production operations agent, 2026-09-21.
Follows mission `2026-09-82a`, whose handback is accepted: **WRONG-PERIOD PICKS**, and its T3 stop was correct.
`2026-09-83a` is a mission label.

## 1. Goal

Build the capture repair that 82a proved is needed, as a train/serve parity change done properly: after 13Z the
collector must stop reading tomorrow morning's minimum as today's maximum, must find today's maximum in the newest
bulletin that actually carries it, and must do so without breaking replay of what was already captured and without
silently changing what an existing model sees. **No forecast candidate is proposed or scored in this mission.**

## 2. Start from this — do not re-derive it

Read `AGENTS.md`, `docs/operations/STATE_OF_PLAY.md`, `docs/operations/FINDINGS_DIGEST.md`, then the 82a report on this
branch (`docs/roadmap/agent-report-2026-09-82a-workstation-is-the-guidance-read-for-the-right-day.md`) and its evidence
directory `tools/research/nbm_target_trace/evidence/` (132 station blocks, `tokens.csv`, `picks.csv`).

Verified on the production host on 2026-09-21, additional to 82a:

- **Production is doing it right now.** The 10:08 local Los Angeles snapshot for target 2026-09-21 recorded
  `cycle_key = nbm-nbp:20260921T13Z` with `provider_update_time = 2026-09-22T12:00:00Z` — the chosen token is valid at
  12Z tomorrow, a minimum. Every event-day store keeps `forecast_payloads.jsonl` / `forecast_payloads_long.csv` with
  `cycle_key`, `provider_update_time`, `payload_hash` and `payload_ref`, and the 35 MB national bulletins are retained in
  the shared payload store (`data/forecast_payload_cas`). The production agent will run the exact census of chosen
  period by cycle and local hour from those files in its own heavy window; you do not need it and must not wait for it.
  The manifest already lists `parser_version` under `provenance_missing_fields` for this source.
- **The NBM-consuming shadow variant is live.** `pooled_f_candidate_miami_current_fallback_v0_1`
  (`artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl`, LFS oid `3b472bd3…` on master) wrote `predicted` rows to
  today's `variant_predictions.jsonl` on production. It is `active_for_headline=false`, `promotion_status=blocked`,
  role `legacy-validation-quarantined`. The served headline model selects no NBM column (EF §10h).
- The research branch is ROLL-FREE by the production tool (193 files, 0 importable).
- Where the code is: the slot choice and parser are `_slot_index_for_target` / `parse_nbp_station_tmax` in
  `src/weather/sources/nbm_probabilistic_tmax.py`; the cycle search is `fetch_nbm_probabilistic_tmax` in
  `src/weather/model/model_sources.py` (walks `nbp_cycle_candidates`, every UTC hour back 24, newest first, skips
  403/404, parses the first bulletin it gets); replay of retained bytes is `replay_nbp_shared_payload` (called from
  `src/weather/operations/forecast_payload_cas_migration.py`) and `replay_nbp_station_archive_row`; the feature block is
  the `nbm_probabilistic_tmax` block of `src/weather/model/model_features.py`.

## 3. Decisions already made by the production agent (do not reopen; say so if you think one is wrong)

- **Repair in place, versioned.** The existing `nbm_prob_tmax_*` columns get the correct period. A wrong-period value in
  a column named "tmax" is a capture defect, not a meaning to preserve. The boundary is made machine-readable instead:
  every new payload and feature row carries a parser version and the chosen token's provenance, and **a row counts as
  guidance for any future training or evaluation only if that provenance is present and says "maximum"**. History
  before the fix therefore excludes itself; nobody has to remember a date.
- **The shadow variant keeps running and crosses an input-regime boundary.** It feeds nothing that is served and cannot
  be promoted. Its rows after the fix are a different input regime and are never pooled with earlier rows. This mission
  records that boundary in the owning documents; it does not retire, refit or re-score the variant.
- **Replay must still reproduce what was captured.** Bytes captured under the old rule replay under the old rule.

## 4. Work, in this order

- **P0 — which cycles carry what.** 82a sampled 01Z/07Z/13Z/19Z only. `nbp_cycle_candidates` tries every hour. From
  NOAA's product description and at most six further cached fetches, state which issue hours publish an NBP bulletin at
  all and which carry complete `TXN` percentile rows. 82a noted the parser can mark a slot available without complete
  rows; confirm or refute with a block.
- **P1 — the slot rule (parser version 2).** Select a token only if NOAA's convention makes it a **maximum** and its
  period belongs to the target's station-local date; require the full row set (`TXNP1/2/5/7/9`, `TXNMN`, `TXNSD`) at
  that token. Derive the date assignment from the published definition of the maximum window and state it for every
  configured US timezone, including the standard-time months; where a station's assignment would be ambiguous, return
  unavailable rather than guess. If the bulletin has no such token, return `available=False` with a specific reason
  (`target_max_not_in_cycle`), never the next token or group. Keep the version-1 rule callable, unchanged, under an
  explicit name.
- **P2 — the cycle search.** With P1, a 13Z or 19Z bulletin is "unavailable" for today and the existing newest-first
  walk falls through to an older cycle. Make that deliberate: order candidates so the first bulletin fetched is the
  newest one that can contain the target's maximum (use P0), keep tomorrow's target on the newest cycle, and show the
  worst-case and typical number of national fetches per snapshot pass before and after, using the existing fan-out and
  payload store so a bulletin already held is not downloaded again. A bulletin is ~35 MB and the capture host has 16 GB:
  a design that adds more than one extra national download per two-hour cache period needs a stated reason.
- **P3 — provenance and version.** Payload and manifest: `parser_version`, the chosen token's issue time, valid time,
  period kind, group and token index, cycle age, and the raw percentiles, mean, spread and per-value rejection reasons
  beside the filtered values. Features: numeric provenance columns sufficient to apply the rule in section 3 (at least
  parser version, chosen valid hour UTC, cycle age in hours, and a maximum-period flag). Do not change the floor, its
  tolerance, or any existing column's name, unit or dtype.
- **P4 — replay parity.** Replay selects the rule by recorded parser version; a record with none is version 1. Prove
  with fixtures from the 82a blocks: a version-1 record replays to its recorded wrong-period values bit-for-bit, a
  version-2 record to its own, and neither passes under the other rule. Run the repository's train/serve parity gate,
  captured-input replay tests and the forecast-payload migration tests. **If any of them fails, report the failure and
  its cause; do not relax, skip or re-baseline a gate.**
- **P5 — what the shadow variant will see.** On the 82a blocks only, table the 15 `nbm_prob_tmax_*` inputs for that
  variant under version 1 and version 2 for the same station, cycle and target (present / dropped / value). No
  outcomes, no probabilities scored, no Brier. State which of the pickle's sub-models select the columns and at which
  cutoffs, read-only.
- **P6 — documents.** Update the owning documents for every new field and the rule in section 3 (source semantics in
  `docs/operations/AGENT_CONTEXT.md` or the document that owns this source; do not put status in an `AGENTS.md`).

## 5. Boundaries

`docs/operations/DELEGATION_CONTRACT.md` §2 binds this mission in full. In addition:

- 81a's rule still holds: **no new forecast candidate is proposed or scored from these dates.** Whether corrected
  guidance helps is a later pre-registered question on dates captured after the fix lands.
- Owned files: `src/weather/sources/nbm_probabilistic_tmax.py`; the `fetch_nbm_probabilistic_tmax` method and its
  direct helpers in `src/weather/model/model_sources.py`; the `nbm_probabilistic_tmax` block of
  `src/weather/model/model_features.py`; the NBM replay call sites in
  `src/weather/operations/forecast_payload_cas_migration.py` only as far as passing the recorded parser version;
  schema-registry entries (and any feature-name registry the tests require) for exactly the new fields; their tests and small station-block
  fixtures; the owning docs; and, as in 81a and 82a, one exact-module allowlist line in
  `.codex/hooks/pre_tool_use_host_load.py`, `scripts/ops/workload_admission.ps1` and their tests. Nothing under
  `artifacts/`, nothing else under `src/` or `config/`. If the change cannot be made inside this list, finish
  everything that can, then report the exact file and reason.
- Never weaken or bypass the observed-high floor. Never fit, retire, promote or re-score a model.
- Free public sources only; serial, cached requests; never refetch a national file you hold (82a's cache is at the
  paths in its README). No credentials, no exchange calls, never read `.weathersync.cred` or any credential file.
- Heavy commands through `scripts/ops/workstation_heavy.ps1`. The workstation may run the full suite. Commit and push
  freely; never merge to `master`. The branch is roll-sensitive: the production host lands it in a quiet window after
  its own verdict and bounded suite.

## 6. What would stop or change the plan

- NOAA's definition makes the local-date assignment of a maximum token ambiguous for a configured station => implement
  only the unambiguous stations, list the rest, and say what evidence would settle them.
- The parity gate, replay tests or migration tests cannot pass with a versioned parser without a change outside the
  owned files => stop at that point and report; do not widen scope yourself.
- P2 cannot meet the fetch budget => report the measured cost and the options; do not ship a silent cost increase.

## 7. Branch and report

- Fix branch: `codex/nbm-target-fix-20260921`, from `origin/master` (`e28530af6` or later). Copy the fixtures you need
  from this branch; do not merge the research branch into it.
- Report: `docs/roadmap/agent-report-2026-09-83a-workstation-read-the-guidance-for-the-right-day.md` on the fix branch,
  per contract §5 — verdict first in bold (READY FOR HOST QUALIFICATION / PARTIAL and why / BLOCKED and why); the slot
  rule in one paragraph; the P2 fetch table; the P4 parity results with test counts; the P5 table; per-file roll verdict
  (run the tool; the production host re-runs it); what was NOT done; reproduction commands with workstation paths.
