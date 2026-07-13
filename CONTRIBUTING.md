# Contributing

This project is maintained primarily by coding agents. Start with
[AGENTS.md](AGENTS.md), then read the nearest scoped `AGENTS.md` for the files
you plan to change.

## Change workflow

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

Use the repository pull-request template. If a documentation category is not
affected, mark it not applicable instead of creating speculative documentation.
Never include credentials, raw secrets, or local machine paths in a change.
