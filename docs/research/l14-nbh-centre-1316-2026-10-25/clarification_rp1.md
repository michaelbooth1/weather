# R-P Clarification RP-1: the code base, and L2's import ratchet

Written 2026-10-25, before any NBH row has been read. It applies to `rule_rp.md` (sha256
`ed3236fa40cfc4cec35d2bcf1da129799716f399a3cb97199d3aa7fb632bbaa2`) and changes no gate, threshold, feature, arm
or kill.

1. **Code base.**
   - The rule names `origin/claude/rung0712-20261025` @ bdc1ef0f8 as the base. That tip cannot score: its
     `r0_ols_floor_challenger` lacks the `_candidate_frame` / `_vector` / `MG1_CONTROL_0712_EXCESS` helpers that
     L2's `rung_j_score` calls. Its wrapper also predates the W2 slots commit 1a16c6ed3.
   - L2 produced R-H's dev files and R-J's LOYO and score from its local run tree `C:\wt\l2run` @ 32d0a09d4. That
     commit merges bdc1ef0f8 onto a base that holds L3's scorer helpers, L7's dev scorecard and loss atlas, L8's
     v2 L6/MG-1 modules, and W2.
   - R-P's branch `claude/nbh-centre-1316-20261026` is therefore cut from 32d0a09d4: the exact code behind the
     incumbent files that R-P must reproduce.
   - Pushing the branch publishes those run-tree commits. Their content comes from already-pushed branches.
2. **Ratchet.** L2's `test_pooled_residual_model_admission.py` forbids any src module from importing
   `pooled_residual_model`. R-P must import it, to re-use the R-A arms unchanged. The test gains one named exception,
   `nbh_centre_shift.py`, itself an allowlisted offline research module. R-P's own admission test forbids any src
   import of `nbh_centre_shift`.
3. **Parser.** `parse_header_line` and `parse_block` are copied verbatim into `nbh_centre_shift` from L12's fetcher
   @ 186c42ad4, because the fetcher is not on this base.
