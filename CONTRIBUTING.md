# Contributing

This project is maintained primarily by coding agents. Start with
[AGENTS.md](AGENTS.md), then read the nearest scoped `AGENTS.md` for the files
you plan to change.

## Change workflow

Use the [Git workflow SOP](docs/git-workflow.md) for topic branches, linked
worktrees, intentional staging, commits, pull requests, integration, and safe
cleanup.

1. Inspect the worktree and preserve unrelated user changes.
2. Identify the owning package and its canonical documentation.
3. Make the smallest coherent change through canonical `weather.*` modules.
4. Run focused tests, then the checks appropriate to the risk of the change.
5. Update documentation, schemas, fixtures, manifests, or runbooks owned by the
   behavior you changed.
6. Review the final diff for generated files, secrets, machine-specific paths,
   compatibility-shim edits, and accidental local `data/` assumptions.

The complete verification matrix and definition of done are in
[docs/development.md](docs/development.md). Documentation ownership and update
triggers are in
[docs/documentation-maintenance.md](docs/documentation-maintenance.md).

## Pull requests

Open a draft pull request from the topic branch and use the repository template.
If a documentation category is not affected, mark it not applicable instead of
creating speculative documentation.

Never include credentials or raw secret values in any change. Never put
machine-specific absolute paths, account names, or host names in code, config,
tests, or fixtures; build paths with `weather.paths`. The one exception is an
operations runbook whose procedure only works on a named host: it may state a
host-local path, task name, or the *location and type* of a credential store,
clearly marked as host-specific, and never the value.

On the 16 GB capture host, verification is time-gated and serial; see the host
rules in [AGENTS.md](AGENTS.md) before running any test or heavy command.

## Update this file when

Update when the change workflow, pull-request expectations, or the secrets and
machine-path rule changes.
