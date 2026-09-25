# Workstation handoff 2026-09-87a — a live-path qualification kit

Written 2026-09-23 by the production agent from the 2026-09-23 read-only audit (`MASTER_AUDIT.md` recommendation 4;
findings D6-01, D6-03, D1-03, D7-07, D6-19). Branch `codex/live-path-qualification-20260923` from `origin/master`.
**Not for RE-1 sessions 2-3:** nothing here changes the session tip `c771cbb42`; it is adopted after the campaign.

## 1. Why

Every RE-1 live defect passed a green full suite and a six-hour fake-venue rehearsal, and each was found only by the
owner's real runs: PowerShell execution policy, an undeclared `python-dotenv`, three separately built HTTP paths without a
`User-Agent` (Cloudflare 403), a reward-universe paginator, and the first real trade message (a complementary match whose
top-level token was the taker's). The rehearsal never loads the modules where they lived; the fakes only produce shapes
we invented. The cure is to test the environment and the real message shapes, not more fakes.

## 2. Build

1. **One outbound HTTP helper** `weather.http` (new module): `json_request(url, *, method, body=None, timeout, max_bytes,
   headers=None)` that always sends a descriptive `User-Agent` (`weather/<component>/<short commit>`), `Accept`, bounded
   read, and raises a typed error carrying status and the first 200 characters of the body. No retries inside (callers
   own policy). Do **not** migrate RE-1 modules on this branch (they are frozen for the campaign); migrate one non-RE-1
   caller as the worked example and list every remaining raw call site in the report.
2. **Three AST ratchets** under `tests/architecture/` (or the existing ratchet location): (a) no `urllib.request.Request(`
   or `urlopen(` outside `weather.http` and an explicit, shrinking allowlist of current call sites (file:line); (b) every
   third-party top-level import anywhere in `src/weather/` resolves to a distribution declared in `requirements.txt` /
   `pyproject.toml` (extend the 84d RE-1-only test repo-wide; allowlist current misses with an issue list, e.g. `pyarrow`);
   (c) every `powershell.exe` spawn in `src/` passes `-ExecutionPolicy Bypass` before `-Command`/`-File`.
3. **A read-only real-endpoint contract probe** `python -m weather.operations.live_contract_probe` that performs, once
   each, the public reads every live path depends on — geoblock GET, Polygon RPC `eth_blockNumber`, CLOB `/book` for one
   configured token, `/rewards/markets/<condition>` for one current reward condition, data-api positions for a public
   address given on the command line — through the same code paths the live modules use, and asserts status 200 and the
   shape each consumer validates. No credentials, no authenticated endpoint, no order path imported. Prints one PASS/FAIL
   row per contract and exits nonzero on any FAIL. It is the thing to run before any owner preflight and daily.
4. **Real-shape fixtures:** a `tests/fixtures/venue_shapes/` directory holding redacted real message shapes (credential-
   named keys removed) — start with the session-1 trade shape 84g confirmed (complementary match, `token_id`/`asset_id`
   aliases) and one order event; a test asserts no fixture contains a credential-named key.
5. **Fresh-environment smoke** (`scripts/ops/fresh_venv_smoke.ps1`, workstation only): create a throwaway venv from
   `requirements.txt` only, import every `src/weather/market/re1_*` and `mm_*` module, delete the venv; report missing
   packages. Runs under `workstation_heavy.ps1`.

## 3. Rules

- Workstation only; `workstation_heavy.ps1` for the smoke and any full suite; full suite at most once, finished before
  19:00 ET on 2026-09-23 (RE-1 session 2 may start from 20:00 ET) and never while a live session runs.
- No `.env`, no credentials, no authenticated endpoint, no RE-1 code change, no session worktree access.
- The probe's network use is a handful of public GETs/one POST per run; never in a loop.

## 4. Report

`docs/roadmap/agent-report-2026-09-87a-live-path-qualification-kit.md`: verdict first; the probe's real output (all rows);
the ratchets' allowlists with counts (raw HTTP sites, undeclared imports, PowerShell spawns); the fresh-venv result; test
counts; the branch tip.
