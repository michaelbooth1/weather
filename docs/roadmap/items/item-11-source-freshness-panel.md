# 11. Source Freshness Panel [COMPLETE - TTL POLICY TRACKED IN ITEM 17]

- [x] Show last successful fetch time for each live source.
- [x] Flag stale feeds or failed requests.
- [x] Keep the last good live source value visible with a stale warning.

Codex audit (2026-05-28): mostly passes. `blend_with_last_good()` caches live
sources and the dashboard shows age, stale/failed status, and stale warnings.
Issue found: visible status/warning strings contain mojibake from corrupted
emoji/warning glyphs, which should be cleaned up for users.

Codex update (2026-05-31): source retry/backoff and 90-minute last-good cache
age limits are now in place. Remaining work is presentation cleanup plus
per-source TTL/status policy under item 17.

Implementation status (2026-06-13): the presentation cleanup is complete -- the
mojibake scan of `app.py` + `src/*.py` is clean and `clean_label` scrubs
corrupted degree glyphs defensively. The only remaining freshness work is the
separate per-source TTL/status policy, which is owned by item 17 (the
fast-vs-slow-source staleness distinction), so item 11's panel scope is complete.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - TTL POLICY TRACKED IN ITEM 17`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

