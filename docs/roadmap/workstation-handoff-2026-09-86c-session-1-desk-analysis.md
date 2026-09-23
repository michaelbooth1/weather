# Workstation handoff 2026-09-86c — RE-1 session 1 desk analysis

Written 2026-09-23 by the production agent. **Offline, read-only analysis** of the first real reward session. No network,
no workstation lock needed (no pytest, no heavy command); it can run beside 84g and the overnight suite/sampler.

## 1. Inputs

Copy (never move or edit) `%USERPROFILE%\.weather-re1m-20260921\session-1\{journal.jsonl,prediction.json,selection.json,
user-stream.jsonl}` into your worktree's ignored `data/re1_session1/`, record each file's SHA-256 before and after the
copy, and work only on the copies. Session facts: quoted 01:47-02:30Z 2026-09-23, 42 two-sided minutes, `P_many` 0.105,
`P_single` 0.125, venue site showed 0.12 earned, reward rate 54 -> 53, partial fill 5.6 NO at 0.48 at ~02:30:07, the
user stream failed on that trade message (84g fixes it). **Redact** `owner`, API-key-like and any credential-named field
from everything you print or commit.

## 2. Questions (each answered with numbers from the journal; say "not identifiable" where it is)

1. **Book mirror (audit D4-08).** Competition is computed from the YES book only, assuming the NO book mirrors it.
   Using the per-minute snapshots (both tokens are in `market_snapshot` / `minute` rows if present; say so if not),
   test the mirror minute by minute and recompute competing Q from both books. How much would `share_many` change?
2. **Venue share vs ours (D4-09).** `accrual` samples include `get_reward_percentages()` (every 30 min). Compare the
   venue-stated percentage with our `share_many`/`share_single` at the same minutes; compute `k_share`.
3. **Which competition model fits.** 0.12 earned against `P_many` 0.105 and `P_single` 0.125: with its uncertainty
   (one session, rounding of the site figure), which is closer, and what would distinguish them next session?
4. **Why the share fell** from about 0.62 to 0.17 cents/minute: decompose into rate change, competitor size added
   inside the spread, and midpoint moves. Was it a single competitor arriving (timestamp) or gradual?
5. **Self-referential midpoint (D4-16).** Was our 20-share order the best qualifying level at any minute? Effect on the
   adjusted midpoint and on our distance/score. How many `rewards_config` entries were active (rate double count)?
6. **The fill.** Price path of both books in the 5 minutes before 02:30:07; did the NO best bid/ask move through 0.48;
   was it a complementary (YES-buy) or same-token match per `terminal_trades`; mark-to-market of the 5.6 NO shares at
   +1, +5, +30 minutes using the last snapshots available (settlement value comes later).
7. **Requotes and legs.** Zero requotes: was the quote ever near the requote bounds? Minutes with one leg not visible?
8. **T+2 population (D4-06).** The band was event date 09-24 while local ET was 09-22 evening. Note how the book and
   competition for T+2 bands differ from T+1 in `selection.json` (all rows are there).

## 3. Output

`docs/roadmap/agent-report-2026-09-86c-session-1-desk-analysis.md` on a new branch `codex/re1-session1-analysis-20260923`
from `origin/master`, plus the analysis script under `tools/` (pure stdlib or the project's pinned packages). Verdict
first in bold: the one-paragraph answer to "does the reward-share model hold on session 1, and what must session 2
record that session 1 did not". Then each question with numbers; then a list of **concrete design inputs for session 2**
(for example: per-minute venue percentage, both-token competition, 30-minute pre/post control windows, continue after
fill). Everything is one session: no significance claims, no model scoring, no α. No `.env`, no credentials, nothing
written under the campaign root, no network.
