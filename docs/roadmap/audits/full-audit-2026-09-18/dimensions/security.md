# Audit dimension: Security and secrets

Auditor: security dimension subagent. Date: 2026-09-18 (run on the live 16 GB production host, near-close window).
Mode: read-only. No project file was modified. No secret value was opened or printed. No python, pytest, ps1, scheduler, process, or network command was run.

## 1. Scope covered

- Tracked files under `src/`, `scripts/`, `tools/`, `app/`, `config/`, `.github/`, plus `.env.example`, `.gitattributes`, `.gitignore`, `requirements.txt`, `pyproject.toml`, `sitecustomize.py`, `.codex/hooks/pre_tool_use_host_load.py`.
- The single untracked file `.claude/settings.local.json` (confirmed untracked: `git ls-files .claude` is empty).
- Git history, only through whitelisted `git log` / `git show <rev>:<path>` on named files (no `-S`, no `git grep`).
- Non-recursive `ls` of `C:\Users\micha\ops`, `C:\Users\micha\ops\secure` (names only) and a filtered name-only `ls` of `C:\Users\micha\Desktop` for credential-like file names. One out-of-repo document was read: `C:\Users\micha\ops\CLI_SSH_HANDOVER_2026-08-13.md` (an agent handover note, not a credential file).
- Canonical docs touching secrets: `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`, `PORTABLE_LIVE_EXECUTION_HOST.md`, `verified-cold-archive.md`, `production-cold-archive-staging.md`, `cold-archive-locations.md`, `STATE_OF_PLAY.md`, `docs/development.md`, `docs/roadmap/items/item-325-*.md`, `scripts/ops/AGENTS.md`.

## 2. Method

Pattern greps (always with an explicit path under an allowed root) for: key/secret/token/password/PRIVATE KEY/Bearer literals, provider token shapes (`ghp_`, `github_pat_`, `sk-`, `AKIA`, PEM headers, 32-hex and 0x64-hex literals), `apiKey=` URLs, `pickle.load`, `joblib.load`, `eval/exec`, `yaml.load`, `shell=True`, `os.system`, `Invoke-Expression`, `-EncodedCommand`, `verify=False` and equivalents, `tarfile`/`extractall`, DPAPI, rclone, S4U / RunLevel, SSH, RFC1918 addresses. Every structural claim below was then traced by opening the cited lines. Where a claim rests on a document rather than on code or a live file listing, it is labelled `doc_claimed`.

## 3. Findings (most severe first)

### security-1 (HIGH) - A plaintext wallet-credential source file sits on the production host Desktop

- Live state: `C:\Users\micha\Desktop\.env.txt` exists, 1,376 bytes, mtime 2026-08-13 19:48 (name-only `ls`, file NOT opened).
- `C:\Users\micha\ops\CLI_SSH_HANDOVER_2026-08-13.md:52-54` calls this exact path "the external credential source" and tells agents "do not open, print, import, copy, install, or expose it here", in the same sentence as "Ontario production never receives wallet credentials". The file being on the production disk contradicts the intent of that policy: the credentials are on the host, merely not imported.
- `.env.example:19-22` shows what a populated source contains: `POLYMM_API_KEY`, `POLYMM_API_SECRET`, `POLYMM_API_PASSPHRASE`, `POLYMM_PRIVATE_KEY` (an EVM signer key).
- The project's own runbook requires the source to live in a dedicated directory with inheritance removed and an allow-list of exactly the current user, SYSTEM and Administrators (`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md:676-740`), and the import receipt records `source_deletion_required_after_transfer: True` (`src/weather/market/mm_credential_import_cli.py:785`). A Desktop file satisfies neither.
- Aggravating context on this same host: autonomous agents run with `bypassPermissions` (security-2); an SSH server with password authentication, RDP and IIS are present and C: is not BitLocker-encrypted per the 08-14 handover (security-4).
- Not verified: the contents. Size alone cannot distinguish a populated file from the placeholder template (both are about 1.3 KB). Confidence is therefore medium. The owner can settle this in ten seconds.
- Bounding factor: the pilot design caps an isolated wallet at 100 USDC (`src/weather/market/market_making_run_constants.py:12`, enforced in `mm_credentials.py:311-313`). Whether the real wallet/Safe behind this key holds more is unknown.
- Recommendation: owner confirms contents; if populated, move it off this host to the eligible live host's ACL-restricted directory (or a password manager), securely delete the Desktop copy, and if there is any doubt about exposure (agent transcripts, RDP/SSH sessions) rotate the L2 API credentials and move funds to a fresh signer. Record the disposition in `STATE_OF_PLAY.md`.
- known_status: new (not in any canonical repo doc; only in an out-of-repo handover note).

### security-2 (MEDIUM) - No privilege boundary between autonomous agents and every secret the Windows user owns

- `.claude/settings.local.json:3` sets `"defaultMode": "bypassPermissions"`; the 180-line allow list (lines 4-187, including `Bash(./venv/Scripts/python.exe -c *)` at 19/171 and `Bash(./venv/Scripts/python.exe -m *)` at 176) is therefore moot. No `hooks` key is present in that file.
- The only mechanical launch guard in the repo, `.codex/hooks/pre_tool_use_host_load.py`, is for Codex, returns "allow" for any tool whose name is not exactly `Bash` (`:3082-3083`), and only recognises host-load patterns (pytest, recursive scans, heavy modules: `:3115-3148`). It has no secret-path or credential rule, and on a hook input it cannot parse it exits 0 = allow (`:3151-3161`).
- Everything sensitive is owned by that same interactive user: the Desktop credential file (security-1), the Git Credential Manager entry that `WeatherOneShotPush` uses (`scripts/ops/AGENTS.md:123-126`), the passphrase-less SSH identity `id_ed25519_workstation_codex` that reaches the workstation in BatchMode (`docs/development.md:98-106`; S4U probe in `item-325:120-122`), the machine-scope DPAPI blob that unlocks the rclone/Google-Drive config (`item-325:123-126`; loader `workstation_cold_archive_stage.py:481-504`), and, on whichever PC runs the live pilot, the four `Weather/Polymarket/InternationalPilot/*` Credential Manager targets readable by any process of that user via `CredReadW` (`mm_credentials.py:94-136`, targets at `mm_credential_import_cli.py:68-73`). `PORTABLE_LIVE_EXECUTION_HOST.md:102-107` explicitly allows a Codex session to stay open during live preparation.
- This is a deliberate owner trade-off (agents are granted broad operating authority). What is not recorded anywhere is the consequence: a single bad agent action, or prompt injection through scraped content the agents read (WU page HTML, exchange payloads, third-party docs), executes with full access to wallet, push, Drive and lateral-SSH credentials. The elaborate in-code gates (confirmation tokens, sealed manifests) constrain the sanctioned path only; they do not constrain a process that simply reads the vault.
- Recommendation: run agents under a separate standard Windows account (or at minimum keep wallet material only on a machine/account where no agent session ever runs); add a deny rule for credential paths and `CredRead`-style access to both agent configs; drop `bypassPermissions` on the production checkout in favour of the curated allow list that already exists.
- known_status: new as a recorded risk; the authority grant itself is owner-accepted.

### security-3 (MEDIUM) - 79 GB of deleted originals depend on one Google account and on self-asserted key custody; key and object identifiers are published in Git

- `docs/operations/STATE_OF_PLAY.md:31` and `item-325:56-62`: 79,105,806,336 allocated bytes (1,679 original files, 85 batches) were removed from production after encrypted upload. The ciphertext on Google Drive is now the only copy of that capture evidence (`STATE_OF_PLAY.md:33`: "Earlier encrypted archives still require their preserved recovery keys").
- The recovery keys are "saved privately as `recovery-keys/...json` in the same Drive remote" (`item-325:199-204`). Availability: losing or being locked out of that one Google account loses ciphertext and key backup together. Confidentiality: if that JSON is plaintext, encryption adds nothing against a Drive compromise; if it was written through the crypt remote, it is circular and useless for recovery. The docs do not say which.
- The other key copy is a DPAPI blob bound to a Windows installation/profile (`verified-cold-archive.md:141-166`; machine-tagged variant `production-cold-archive-staging.md:84-86`, loader `workstation_cold_archive_stage.py:457-535`). OS reinstall or disk loss destroys it.
- The reclaim (deletion) gate accepts key custody as a JSON self-assertion: `confirmed is True`, `outside_both_pcs is True`, free-text `approved_by` and `storage_reference` (`cold_archive_recovery_publication.py:28-41`, `cold_archive_reclaim.py:215-220`). Nothing verifies that the referenced copy exists or decrypts anything. `production-cold-archive-staging.md:86-89` states the owner authorised *the agent* to save and verify the key backup, so an agent both handled key material and can author the custody record that unlocks deletion.
- Tracked docs publish the private Drive folder ID and the recovery-key object ID (`item-325:192-203`). Harmless while sharing is "Restricted" and the repo is private; `item-325:81` refers to "public repository prose", so repo visibility should be confirmed.
- Recommendation: owner personally performs one end-to-end restore drill using only the off-PC key copy (no DPAPI blob), places a second key copy outside the Google account (paper/password manager), verifies Drive sharing is Restricted, and records the drill. Consider whether encryption is worth its key-loss risk for data that is mostly public market data.
- known_status: new for the co-location/self-assertion risk. The separate decision to pause the off-host mirror is owner-accepted and is not re-raised here.

### security-4 (MEDIUM) - Production host remote-access surface and at-rest protection (doc-claimed, a month old)

- `CLI_SSH_HANDOVER_2026-08-13.md:1,501-517`: agents operate the production host through an SSH session, i.e. an SSH server runs on it. `:491-494` lists as deferred: "Do not make SSH key-only until confirmed key access is demonstrated" (password auth still enabled) and "Where should the BitLocker recovery key be stored before enabling C: encryption?" (disk not encrypted). `:71-72` and `:206-207`: IIS and the current RDP scope are "operator-confirmed intentional".
- Positive items in the same note (`:496-499`): Telnet/Simple-TCP features removed, Secure Boot, VBS, Defender real-time, firewall profiles healthy.
- I could not verify live service state (process/service commands are forbidden in this audit).
- Impact: password-auth SSH plus RDP on a host with the items in security-1/2; an unencrypted disk means theft of the PC yields the Desktop credential file and the passphrase-less workstation SSH key in clear. The production-to-workstation key is also a lateral-movement path to the PC that holds the archive key and would hold wallet credentials.
- Recommendation: finish the two deferred decisions (key-only SSH; BitLocker with the recovery key in the same off-PC place chosen for security-3); restrict sshd/RDP to the LAN or a specific source address; put a passphrase or a forced-command restriction (`command=` in `authorized_keys`) on the workstation key.
- known_status: known_open (SSH, BitLocker) / known_accepted (IIS, RDP - reported once, not a headline).

### security-5 (LOW) - The currently served path unpickles model artifacts with no integrity check

- `src/weather/model/model_features.py:59-71`: when no release bundle is bound, `_read_feature_model_hgb` resolves `artifacts/models/hgb/feature_model_hgb*.pkl` and calls `pickle.load` directly. Compare the release path, `src/weather/release_serving.py:197-214`, which checks SHA-256 before and after deserialisation. Per project context Release #1 has not shipped, so the unverified fallback is what the capture loops execute (the "release pointer absent" state is inferred, not checked live).
- Pickles are LFS-tracked (`.gitattributes:9`). Anyone able to write that directory or push to the remote gets code execution inside the capture workers. With a single owner this is low; it is mainly a reason to protect push credentials. Other `pickle.loads` sites (`mm_paper_aggregation.py:35-40`, `taker_bot_aggregation.py:62`) round-trip the process's own temp SQLite spill and are benign.
- Recommendation: reuse `_checked_pickle` against a tracked hash manifest for the fallback path.
- known_status: new.

### security-6 (LOW) - `shell=True` behind a prefix-only allowlist in MM preflight recovery

- `src/weather/operations/market_making_preflight_recovery.py:94-95`: `_command_allowed` is `command.startswith(prefix)` over five prefixes (`:25-31`); `:146-153` runs the string with `shell=True`. `python -m weather.collection.snapshot_tracker & <anything>` passes. The string comes from `preflight_remediation.json` in a run folder (`:40-55`, `:67-76`).
- Traced instance: generators emit static strings (`market_making_preflight.py:939-953`), so there is no remote-controlled input today; exploitation needs write access to `data/`. Separate correctness defect: several generated commands contain literal `<YYYY-MM-DD>` placeholders, which cmd.exe parses as redirection if `--execute` is ever used. The bare `python` also resolves through PATH rather than the venv.
- Recommendation: `shlex.split` + `shell=False`, exact-argv allowlist, absolute venv interpreter, refuse strings containing `<`.
- known_status: new.

### security-7 (LOW) - Dependency supply chain: nine exact direct pins, no lock file, no hashes, no automated advisories

- `requirements.txt:4-12` and `pyproject.toml:9-27` pin only direct dependencies. No lock/constraints file, Dependabot, or pip-audit config is tracked (`git ls-files` filter returned only `requirements.txt`). CI does `pip install -r requirements.txt` (`.github/workflows/ci.yml:36-39`), so the large Streamlit transitive tree (tornado, protobuf, pyarrow, pillow, GitPython, ...) floats, and the production venv is whatever resolved on install day.
- Actions are first-party and tag-pinned (`actions/checkout@v4`, `setup-python@v5`, `upload-artifact@v4`), not SHA-pinned.
- Contrast (strength): the live SDK is a sealed wheelhouse with SHA-256-verified manifest, tree and core wheel (`src/weather/market/live_sdk_overlay.py:228-336,342-362`).
- Recommendation: commit `pip freeze` from the production venv as a constraints file and use `-c` in CI; add a monthly `pip-audit` job.
- known_status: new.

### security-8 (LOW) - A weather.com API key literal is in Git history; the settlement source depends on a scraped front-end key

- `git show 88fb27a27:src/wu_history.py` line 44 (through `9d3cbcd12` line 82) and `9d3cbcd12:src/model_constants.py:17-21` contain a 32-hex `WEATHER_COM_KEY`; the project's own comment calls it "the widely-published browser key". It is gone from the tree by `fd728d4a4` (2026-06-13). No other secret-named file was ever added in any ref (`git log --all --diff-filter=A` over `.env*`, `*.pem`, `*.key`, `*.pfx`, `*.cred`, `*rclone*.conf`, `*id_rsa*`, `*id_ed25519*` returns only `.env.example`).
- Current code holds no key: it scrapes `API_KEY` from the public WU history page at request time (`src/weather/sources/wu_history.py:274-291,301-325`), never persists it (`:364-394`), and redacts it in error text (`:123-138`).
- Residual: history rewrite is not worth it for a public key. The real exposure is operational: the project's settlement truth depends on using a third party's embedded front-end key, which is a ToS/availability fragility.
- Minor: `historical_backfill_runner.py:28-30` redaction is case-sensitive while `wu_history.py:126` is case-insensitive.
- known_status: new (low).

### security-9 (LOW) - Dashboard launcher does not pin the listen address

- `scripts/launch/start_weather_dashboard.ps1:32-37` passes `--server.port` and `--server.headless` only; no tracked `.streamlit/config.toml`. Streamlit then listens on all interfaces, unauthenticated. The app is read-only (no `subprocess`/`st.button` under `app/`), so the exposure is information disclosure to the LAN, subject to the Windows firewall.
- Recommendation: add `--server.address 127.0.0.1`.
- known_status: new.

### security-10 (INFO) - Self-asserted safety flags in the credential path

- `mm_credential_import_cli.py:727-728,912`: `--confirm-source-acl-private` is a boolean the caller sets; the importer does not read the ACL (the runbook's PowerShell does, `INTERNATIONAL_MM_LIVE_PILOT.md:694-740`).
- `mm_exchange.py:218-227`: `contains_secret_material` inspects key *names* only; a secret under an unexpected key name passes.
- `.env.example:29-30` documents `POLYMM_ALERT_WEBHOOK_URL`, but no code under `src/weather` references a webhook (stale template line; the importer would reject it as an unknown key, `mm_credential_import_cli.py:609-610`).
- known_status: new (hygiene).

## 4. Strengths (verified)

1. No live secret in the tracked tree. Greps for provider token shapes, PEM headers, bearer strings, `apiKey=` literals and credentialed URLs across `src/`, `scripts/`, `config/`, `tests/`, `docs/` found only synthetic fixtures (`example.invalid`, `secret123`). `.gitignore:44-46` ignores `.env*` except the example; history never contained a secret-named file.
2. Credential-by-reference design is well above hobby grade: secrets only in Windows Credential Manager, never argv/env (`mm_credentials.py:1-6,242-258`; direct-secret env vars are a hard failure, `mm_exchange.py:360-383`); create-only import with rollback, constant-time compare, bounded identity-checked source read, outputs forced outside the repo (`mm_credential_import_cli.py:528-545,548-589,639-647,862-902`); redacting `__repr__` on bundles (`mm_credentials.py:73-77`); error output reduced to the exception type (`:946-948`).
3. Scheduled tasks are uniformly current-user `S4U` / `RunLevel Limited` with no stored passwords and no `RunLevel Highest` anywhere under `scripts/` (e.g. `register_boot_recovery.ps1:54`, `register_health_watchdog.ps1:30-31`), with read-back verification of principal/action.
4. GitHub Actions posture is clean: `permissions: contents: read` on all three workflows, no secrets, no `pull_request_target`, only first-party actions (`ci.yml:8-9`, `retrain.yml:13-14`, `host-load-hook.yml:15-16`).
5. Injection-resistant process plumbing: PowerShell children receive data as base64 inside `-EncodedCommand` rather than interpolated strings (`scripts/ops/quiet_window_merge.ps1:1458-1491`); no `Invoke-Expression`, no `verify=False`/cert bypass anywhere; rclone password travels only in a private child environment and is zeroed (`workstation_cold_archive_stage.py:1264-1273,1540-1542`); archive restore rejects links/special members, unexpected names and hash mismatches instead of using `extractall` (`verified_cold_archive.py:1417-1451`); sealed live templates null out git hooks, credential helpers and proxy variables (`international_live_templates/stage0.py.tmpl:105-137`); host/principal IDs in `config/international_live_execution_host.json` are domain-separated SHA-256 of MachineGuid/SID, not credentials (`execution_host.py:67-71,140-144`).

## 5. Not covered

- Live host state: listening ports, sshd_config, firewall rules, BitLocker status, scheduled-task XML, Credential Manager contents, NTFS ACLs (all require forbidden commands).
- Contents of `C:\Users\micha\Desktop\.env.txt`, `C:\Users\micha\ops\secure\weather-live\`, any rclone config, any custody record under `data/cold_archive/` (data/ was out of brief).
- The workstation host entirely.
- GitHub repository visibility, branch protection, collaborator list, Drive sharing settings (no network).
- The 210 unmerged branches and 200 worktrees were not scanned for secrets; only named files in a handful of early commits were inspected.
- User-level agent config (`~/.claude/settings.json`, `~/.codex/hooks.json`).
- `config/location_market_events.json` was grepped for secret-like keys only, not read.

## 6. Open questions for the owner

1. Is `Desktop\.env.txt` populated with real values? If yes, what does the wallet/Safe behind it currently hold?
2. Is `github.com/michaelbooth1/weather` private? (`item-325:81` says "public repository prose".)
3. Is the Drive recovery-key JSON plaintext or stored through the crypt remote? Is there any key copy outside that Google account and outside both PCs?
4. Did recovery-key material pass through an agent transcript on 2026-09-10 (`production-cold-archive-staging.md:86-89`)?
5. Is sshd on production still accepting passwords, and is it reachable beyond the LAN?
