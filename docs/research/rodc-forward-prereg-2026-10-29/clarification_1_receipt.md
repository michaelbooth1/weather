# Row 72 Clarification 1: pin receipt (2026-10-31)

Code-only. No forward snapshot, WU row, receipt, label or outcome was read.

| Item | Value |
| --- | --- |
| Branch | `claude/row72-clarification-1-20261031`, off `2048c2f496680dd705f47dcc962fdd53dcaaa7d7` |
| Code commit | `ba3b75916d87c48f97f846982d4c2f02a7937027` |
| Clarification | `docs/research/rodc-forward-prereg-2026-10-29/clarification_1.md`, git blob `f8d1f7ebbc9e6090bfb3b68ddd0553859e08b9bc`, sha256 `9738ce8d7debbe4722aec21d3964b1abd4c9db4f6963ac1cdece486317b96464` (pinned in the scorer as `CLARIFICATION_1_SHA256`) |
| Scorer | `src/weather/calibration/rodc_forward_scorer.py`, git blob `a2d4571604be2f04cba918541ce7e474ca323c86`, sha256 `7c5a7e0772119102455be65a23cf3930e7cf87a64c506ea10bb5c3c9ae8e7198`; supersedes blob `a611bb810a59169ca62672f710033e1cc46d317b` (sha256 `a1e85078…`) for P1 |
| Scorer tests | `tests/calibration/test_rodc_forward_scorer.py`, git blob `9973fa44aa235d5f8c57a0a2917f338c960358cd`, sha256 `9430f54230395341764ab9fe3ae3f1743438dd9574aafa90a3c627e516b6594e` |
| Serve module (unchanged) | `src/weather/calibration/odc_metar_features.py`, git blob `1cc4d565468bf4959137a8f6f6cec5b10adfce24`, sha256 `dd53e81ebbf8851673d01f138296fb56a91ce898e53c0541d67226e64dd981d1` |
| Tests run | the scorer and odc test files through `scripts\ops\workstation_heavy.ps1 -Queue` (2026-10-31): 38 passed, exit 0; basetemp `C:\t\l16\pt-r72c1` deleted; log sha256 `eaabb58e997e930fa8dbe51eae6b31d35446741510437d35b090b253ef962526` |
