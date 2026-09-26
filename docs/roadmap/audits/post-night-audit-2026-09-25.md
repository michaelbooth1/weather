# Post-night second-opinion audit — 2026-09-25

- **Owns:** the read-only second-opinion audit of the state after the 2026-09-25 overnight landings, its verified findings,
  dispositions and the ranked next moves it proposed.
- **Read when:** planning the 88a→89a adapter, RE-1 sessions 12-30 or two-band quoting, or tonight's landing queue.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)).

Auditor: Fable read-only subagent (no edits, tests, processes or venue calls). The production agent verified the three
load-bearing claims before acting (marked **verified**).

## Verdict

Master matched the claimed night landings; capture healthy; 88a CAPTURING (471 cycles, 0 failed, 120 conditions, ~90 MB/day
sealed on disk, inside its bounds). One substantive gap: **89a cannot consume 88a's output** — the data is right but the path
and shape are not. Live risk: free space ~50 GiB late morning with the Stage-A step, so tonight's bounded suite (needed by 95b)
may trip its 50 GiB floor unless space is reclaimed.

## Findings and dispositions

| Sev | Area | Finding | Evidence | Disposition |
| --- | --- | --- | --- | --- |
| HIGH | 88a→89a | 89a reads reward terms only from the snapshot folder (`reward_records.jsonl`, `rewards.jsonl`, `snapshots.jsonl`); 88a writes gzipped hourly segments under `data/maker_evidence/<UTC-day>/<hh>-<seg>/reward-<hash>.jsonl.gz`, CLOB body as a `body_utf8` string with `payload_ref` dedup rows; `term_rows` only descends `markets`/`bands`. Inner field names already match. | `fill_toxicity_desk_study.py:73`; `fill_toxicity_inputs.py` `term_rows`; `maker_evidence_store.py:248-276` | **verified.** Build a bounded 88a→89a terms adapter plus Clarification 11 (data-inclusion change); no 89a rerun before ~10 UTC dates of 88a data (earliest ~2026-10-05). |
| HIGH | 89a | 0/480 is genuine: no writer on master produces `reward_records.jsonl`/`rewards.jsonl`, the snapshot tape never carried per-minute terms; only the daily `exchange_economics` snapshot holds historical terms. The forward plan's "same-day tape" premise was wrong. | 89a report JSON; `forward-plan-2026-09-23.md` item 5 | **verified** (exclusion reason). A daily-terms fallback would break Clarification 3.3's 60-minute rule: **owner decision**. |
| HIGH | Disk | 50.3 GiB at 10:20 after the Stage-A step, ~0.4 GiB/h slope; 24 h min 45.7. 95b needs the bounded suite. | `data\alerts\disk_free_trail.jsonl` | **verified** (50.23 at 10:32). 17 merged, clean, untasked `C:\tmp\wt-*` worktrees retired 10:35 (+1.31 GiB). Run 95b's suite only if free ≥ 52 GiB at 00:30; otherwise compress closed days first. |
| MED | 88a ops | `data\maker_evidence\extra_conditions.json` absent, so the session band, controls and update windows were not captured for session 11. | `passive-maker-evidence-capture.md`; `Test-Path` False | **verified.** Write it before each RE-1 session (agent, per-session checklist). |
| MED | Canon | OPEN_QUESTIONS Q-01/02/05/06, forward plan item 5, live plan S0, digest "four fills", EF §10m heading are stale. | cited files | Agent canon-repair commit (roll-free). |
| LOW | Canon | STATE_OF_PLAY master hash stale (docs commits after `fcb27f0a8`). | `STATE_OF_PLAY.md:34` | Fixed in this commit. |
| LOW | Retention | `data/maker_evidence` has no family row in the retention policy (~0.1 GB/day, nothing expires). | `data-retention-policy.md` | Agent, canon-repair commit. |
| LOW | Scheduler | `WeatherMakerEvidenceCapture` last result 0x800710E0 every minute is the IgnoreNew refusal by design; `status.ps1` keys on state/age. Staleness sweep handling UNVERIFIED. Pre-night leftovers remain. | `Get-ScheduledTask`; `status.ps1` | Note in the 88a doc; owner reviews leftovers. |

## Ranked next moves (auditor's proposal)

1. **Disk before 00:30** (agent): worktree retirement done; re-read the trail at 00:30; compress closed days under the lease if
   below ~52 GiB; then decide 95b.
2. **RE-1 sessions 12-30** (owner starts; agent preflights and writes `extra_conditions.json`): 12-14 single-band on
   `d90d0a6e6`; two-band quoting is venue-feasible under EF §10n but is a new order shape (two positions, two cancel paths),
   so it needs a dated pre-registration, a minimal two-band mode, an owner preflight and **owner authorization of its
   per-session reserve cap**.
3. **88a→89a adapter** (agent, workstation): unwrap `body_utf8`, resolve `payload_ref`, group by event; unit test on one sealed
   segment; Clarification 11.
4. **Canon repair** (agent, roll-free): the MED/LOW canon rows above.
5. **Multi-domain seed**: build two-band as a domain-neutral order-set abstraction (list of {market, side, size, price}, one
   reserve check, one cancel-all) with weather only in band selection. 90a owner decisions still pending.
6. **91a**: get `roll_verdict.ps1` first; after 95b, bounded run only.

## Sound, leave alone

Capture fleet and execution tape; 88a independence and bounds; night landings and receipts; `status.ps1` UTC parse; the disk
figures in STATE_OF_PLAY; 89a's verdict under its frozen rule.

## Unverified

RE-1 session count and journals (workstation); cause of the +3.7 GiB step at 19:50 09-24; staleness-sweep handling of 88a's
result code; 91a's roll verdict.
