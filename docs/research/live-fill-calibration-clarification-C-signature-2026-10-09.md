# Live fill-calibration — owner signature record for clarification C (2026-10-09)

The owner signed, in the production-agent conversation at **2026-10-09 20:28 America/Toronto (2026-10-10T00:28Z)**, verbatim:
"approve all recommendations I sign clarification C at 4d6ae37a4f2cb6a098ef709dd0148b9babba6e465c3d202dff2ab4242d369054"

Signed bytes: `docs/research/live-fill-calibration-clarification-C-2026-10-09.md` at commit
`ab4968afe7b805b727fb3b45b5b85a0450918e60`, SHA-256 (LF, `git show <commit>:<path>`)
`4d6ae37a4f2cb6a098ef709dd0148b9babba6e465c3d202dff2ab4242d369054`, recomputed by the production agent before recording.
The superseded draft `d8a280c1…7a41` was never signed and is void.

"Approve all recommendations" in the same message settled, as recommended:
- Q-C2: if the venue never cancels in run 0g, the campaign halts permanently (as drafted in C); re-opening needs a reviewed fix
  and a new owner-signed clarification.
- N-10: session-0 S0-2 on run 0c is backed by recorded timestamps (`--s0-2-helper-zero-utc`, code
  `claude/live-fill-calibration-code-n10-20261009` @ `6c45aaa14`); the flag is to be documented in a later clarification D.
- The workstation may copy the wallet-reader client configuration into the pinned LFC deploy worktree (owner yes).
- Unrelated items settled in the same message: tzdata download on hosts and CI; v0.2 tape backs off only after a late refresh.

Code basis for session 0 and attestation: one pinned detached worktree at `6c45aaa14` on the workstation (Fable delta-2 PASS
at `468607b13`; N-10 diff reviewed by the production agent). The four 10-09 18:09Z signed files are unchanged.
Still open with the owner: at least three off-panel candidate events for session 0.