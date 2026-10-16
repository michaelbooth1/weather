# Mission 83a station fixtures

The 44 top-level blocks are copied from
`origin/codex/nbm-target-fix-handoff-20260921` at
`f80924693ba26f5f6ba7d6ba15a840e7dc74a768`, under
`tools/research/nbm_target_trace/evidence/blocks/20260917T*`.
No outcome or observation files are needed by these controls.

The four `p0/` blocks were extracted from the two additional cached national
00Z/12Z bulletins in 83a. The PGUM blocks demonstrate the unchanged parser's
`available=True` with entirely absent TXN rows; PGUM is deliberately outside
the supported mainland station set. Provider URLs and national hashes are in
[P0 evidence](../../../docs/roadmap/nbm-target-fix-20260921/p0.json).
Top-level copied fixture hashes are in
[the fixture inventory](../../../docs/roadmap/nbm-target-fix-20260921/fixture-hashes.json).

## Parser differential controls for 110c

The same 44 top-level `.txt` files are also byte-identical to those at
`origin/codex/integrate-2-parser-20260921` at
`abd648c7c2de55289e88dc7d023136b981e2cb74`, at these same paths. They are
previously tracked public station bulletin controls (four cycles, eleven stations),
not newly collected data or production account/settlement evidence. Handoff 110c
explicitly requests these fixtures. `sha256.json` pins their bytes.

`test_maker_plugin_110c.py` compares every FHR/TXN pair row against the verbatim
row parser from that commit, then checks selected T+1/T+2 percentiles using the
existing v2 slot oracle. Tied (whole-degree) knots parse as CDF atoms since 111k;
only a decrease fails closed. The plugin
deliberately rejects three-token groups rather than silently dropping a token.
No network, runtime data directory, or external checkout is needed to run tests.
