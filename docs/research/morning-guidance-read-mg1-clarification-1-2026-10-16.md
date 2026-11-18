# MG-1 pre-registration — Clarification 1 (2026-10-16): D0 fixed by the owner

Status: **owner decision record.** This is the separate dated amendment file that
[the MG-1 pre-registration](morning-guidance-read-mg1-preregistration-2026-10-04.md) §9 requires; that file's bytes are
unchanged. Source: [DECISION_LOG](../operations/DECISION_LOG.md) row 2026-10-16 "MG-1 window = Option 2, BOUND"
(owner 2026-10-16 ~09:22 EDT, relayed by master-agent; this clarification is master-agent's ruling within that
approval).

## Clarification 1

1. **D0 = 2026-10-15, fixed by the owner.** It replaces the derivation in pre-registration §3, which defined D0 as the
   first date satisfying conditions (a)-(e). It sets aside §3 (b), the condition that parser v2 be landed and verified
   in production before the first T+0 snapshot of D0, and §3 (c), the condition that the MG-1 shadow stage and the
   unfiltered v2 diagnostics be captured. §3 (a) holds by construction, and §3 (d) is satisfied anyway, since
   2026-10-15 is after the 2026-10-04 signature.
2. **Parser v2 verification and shadow-stage capture stay reporting caveats.** The read reports, per counted date,
   whether parser v2 was landed and verified (the §3 (b) definition: all three capture workers recovered, and a full
   prior day of manifests with `parser_version = 2` and v2 provenance on every US NBM row) before that date's first
   T+0 snapshot, and whether the MG-1 shadow stage and the unfiltered v2 diagnostics were captured for it (§3 (c)).
   Both are disclosed beside the result and are not pass, void or exclusion conditions.
3. **The count is unchanged.** From D0 the evaluation counts each promotion-countable date, with no skipping and no
   choice, until 45 are counted (§3).
4. **The reserved window follows from D0.** `MG1_D0 = 2026-10-15` and a provisional `MG1_LAST = 2026-11-28`
   (D0 + 44 days) in `weather.mg1_reserved_window`; LAST may only move later, and it is extended whenever a date in the
   window proves not promotion-countable ([reserved confirmation window](../operations/reserved-confirmation-window.md)).
   Master-agent owns the countability check and any extension before 2026-11-29.

Nothing else in the pre-registration changes.
