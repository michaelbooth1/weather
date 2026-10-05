# #230 ctrl-break flake: does the real launcher park under load? (2026-10-05)

Verdict: no forced teardown was observed in any run. The flake is the test's
start-up timing precondition, not the launcher.

Runs on DESKTOP-RFCD2GH under 32 CPU-burner processes (32 logical CPUs),
all through workstation_heavy.ps1 -Queue:

- Stock 55ed5c3e (3 s allowance, 0.5 s tail, 3 s grace): 100 reps, 0 failures.
  Before the restart: 1 failure in 30 (marker 2509 ms after the deadline,
  cooperative=True forced=False exit=3).
- Option branch (5 s allowance, 1.5 s tail): 200 reps (ctrl-break test plus
  test_international_live_session_runner_stdin.py), 4 failures.
  - 1 was the marker landing after the deadline (+1202 ms), with
    cooperative=True forced=False exit=3.
  - 3 had no marker at all: PowerShell start-up took longer than 5 s, so the
    break arrived before the script ran.
  - None failed on cooperative, forced or exit-code assertions that were
    reached.
- test_zz_launcher_load_probe.py: the real _default_launcher_runner with its
  production grace (COOPERATIVE_CLEANUP_GRACE_SECONDS = 20 s), 15 reps per
  break point, under load. Forced teardowns: 0 of 60.
  - Break at 0 s: 9 refused before child creation (reserve expired); 6 were
    cooperative with exit 0xC0000142.
  - Break at 0.3 s: 15 cooperative, exit 0xC000013A.
  - Break at 1 s: 15 cooperative, exit 3.
  - Break at 5 s: 15 cooperative, exit 3. Maximum elapsed was 6.7 s.

Why the live launcher cannot hit the start-up path:

- It creates the child only when at least 90 s (capture-colocated) or 180 s
  (portable) remain before the deadline. A timeout break therefore lands
  minutes after start-up.
- PowerShell resumes from the break debugger because stdin is the null
  device (#229).
- Grace is 20 s against observed loaded handling of up to about 6.7 s.
- Even a real park is bounded: after the grace the runner reports forced=True,
  and closing the KILL_ON_JOB_CLOSE job tears down the tree.

Only an operator Ctrl+C within the first seconds can reach the start-up path,
and it still exits cooperatively in these probes.

Evidence (local, not tracked): C:\wt\workstation-chat\l-data\flake\
(v_opt100.*, v_stock100.*, probe_load.jsonl, load32.log, diag.jsonl).
