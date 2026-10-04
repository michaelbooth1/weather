# Proposed STATE_OF_PLAY text: model-parity swarm v2 (DRAFT, pending production review)

> **This is a proposal, not an edit of `docs/operations/STATE_OF_PLAY.md`.** It was drafted on the workstation branch
> `codex/model-parity-swarm-20261004` by the swarm's canon writer (S-CANON), strictly from [SYNTHESIS.md](SYNTHESIS.md).
> Production decides whether and how to fold it into its next STATE_OF_PLAY rewrite (with a DECISION_LOG row for any owner
> decision). Every number is a development read on previously inspected dates. Nothing below has been adopted.

## Proposed bullet for "Current truth"

- **Model-parity swarm v2 (workstation, night 10-03/04; EF §10q, DRAFT):** on the 111h table (1.77x), two serving repairs on
  already-captured data close about half the served-market excess (1.73x → 1.34x, development): the evening late-day
  lock-in is a no-op since WU was disabled (confirmed on one served payload; restoring it closes 85% of 17-23, cosmetic for
  the maker), and a zero-parameter read of captured NBM v2 closes 40-58% of each 00-12 block after the 83a/83b parser
  repair. No external free source adds information; there is no capture case. 00-16 stays at 1.29x; the largest residual is
  15-16 (2.53x). Nothing adopted.

## Proposed replacement for "Ordered critical path" item 4 (Research)

4. **Research:** the NBS/NBH probe is answered by swarm v2 (no increment; capture NBH closed, EF §10q). Owner decisions
   pending: the evening WU-anchor serving fix (proposal; captured-input replay first), landing the 83a/83b parser repair as a
   versioned parity change, METAR fix M0 (`reportTime` → `obsTime`), and signing or rejecting the unsigned drafts (MG-1 or
   RV-1 for 00-16, t3-r3 for 13-16, HG-1 as its own α arm; decline NBH-1), all first eligible after 2026-10-14 and out of
   season, with the reservation collisions resolved. T+1/T+2 NWP-timing pilot unchanged.

## Notes for the production writer

- Keep the STATE_OF_PLAY line and size budget: the bullet above replaces nothing else; trim elsewhere if needed.
- The tail figure on this table (6.075% of rows / 70.38% of excess) is reported beside EF's 4.387% / 64.140%; EF's figure
  is not to be changed.
- Any owner decision taken on these proposals needs a DECISION_LOG row in the same commit.
