# Claude Code entry point

@AGENTS.md

## Claude-specific notes

- The machine-local auto-memory (`~/.claude/projects/.../memory/`) is a private
  aid, never project truth. Other agents cannot see it, and it can be stale.
  When it disagrees with `docs/operations/STATE_OF_PLAY.md` or the findings
  digest, the repository wins. Anything durable you learn — a decision, a
  measurement, a trap — must be written into the owning repository document in
  the same session, not only into memory.
- On the 16 GB capture host, run pytest only inside 00:30–09:00, serially, never
  as a direct full run, and always with an explicit `--basetemp` that you delete
  afterwards (test temp output has filled the disk before). Check free space
  with the volume's free bytes, not a directory walk.
- Abandoning a tool call does not stop the process it started. Track and
  terminate anything you launch on the capture host.

## Update this file when

Update only when Claude Code harness behavior needs a note that does not apply
to other agents. Everything else belongs in `AGENTS.md`.
