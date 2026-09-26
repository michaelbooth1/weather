# Parser differential controls for 110c

The 44 top-level `.txt` files are copied byte-for-byte from
`origin/codex/integrate-2-parser-20260921` at
`abd648c7c2de55289e88dc7d023136b981e2cb74`, at these same paths. They are
previously tracked public station bulletin controls (four cycles, eleven stations),
not newly collected data or production account/settlement evidence. Handoff 110c
explicitly requests these fixtures. `sha256.json` pins their bytes.

`test_maker_plugin_110c.py` compares every FHR/TXN pair row against the verbatim
row parser from that commit, then checks selected T+1/T+2 percentiles using the
existing v2 slot oracle. Repeated percentile knots still fail closed; the plugin
deliberately rejects three-token groups rather than silently dropping a token.
No network, runtime data directory, or external checkout is needed to run tests.
