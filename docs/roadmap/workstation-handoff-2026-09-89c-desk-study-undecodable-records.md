# Workstation handoff 2026-09-89c — desk-study tool: undecodable records (Clarification 9)

Written 2026-09-24 by the production agent. The first production run of the 89a tool (`947d96935`) refused on one
undecodable record; a full scan found 13 in 77.7 GiB (see Clarification 9 in
`docs/research/fill-toxicity-desk-study-preregistration-2026-09-23.md` on `origin/codex/reward-test-attended-handoff-20260921`).

Implement **Clarification 9 exactly** on `codex/fill-toxicity-desk-study-20260923`: skip and count undecodable records,
turn the surrounding interval into a coverage gap under Clarifications 3/4, keep the three refusal conditions (over 1% of
a file, any settlement-ledger row, unlocatable record), and add the per-record exclusion rows to the outputs. Refusal
messages must name the file and line. Tests: synthetic NUL block inside a gzip JSONL, a truncated line, an invalid control
character, the 1% refusal, a ledger-row refusal, and gap-minute accounting. Change nothing else; stop and report on any
ambiguity. No real tape on the workstation. Report as a dated section appended to
`docs/roadmap/agent-report-2026-09-89a-fill-toxicity-desk-study-tool.md` with the tip; push is authorized.
