# Capture host Wi-Fi outage and cold-snapshot block (2026-10-28)

**Status: CLOSED — incident record.** Facts as reported by master from the capture host. Live health comes from
`status.ps1`; current state is in [STATE_OF_PLAY](STATE_OF_PLAY.md). Times are America/Toronto.

## Wi-Fi outage in the graded window

- **11:47:33** the AX201 Wi-Fi driver dropped the link. The profile was set to "Connect manually", so Windows never
  reconnected.
- **12:15:37** the owner hard-reset the PC. Pending update KB5127648 then did 3 servicing restarts, 12:21-12:25.
- **12:54** Wi-Fi was back.
- **Impact:** capture was offline about 67 minutes inside the 12:00-18:00 graded window. The capture processes stayed
  up throughout, so the process-count health check read 10/10 while no data arrived.
- **Lesson:** a process-count check cannot see a network outage. Liveness needs a network signal (gateway ping) and a
  data signal (snapshot age).

Fixes:

- The Wi-Fi profile now connects automatically.
- The master tick checks the gateway ping and the newest snapshot's age, not only the process count.
- Windows Update is paused to 2026-12-02T12:00Z.
- The owner will plug in an Ethernet cable.
- Proposed, not registered: a workstation-side ping watchdog for the capture host (every 5 minutes, alert after 2
  misses). Registering it needs the owner's yes.

## Cold-snapshot nightly blocked 10-27..10-28

- The 10-26 nightly attempt of `WeatherColdSnapshotNightly` refused at start (available memory below 4 GiB) and wrote
  0 files. An unresolved failed attempt blocks every later night
  ([cold snapshot compression](cold-snapshot-compression.md)), so the 10-27 and 10-28 nights did not run.
- Resolved 2026-10-28 ~18:0x.
- The nightly policy was renewed as a new create-only policy file (sha256 prefix `eca4064a`, expires 2026-11-27).
  Re-registration of the scheduled action follows on 2026-10-29 after its dry run.
