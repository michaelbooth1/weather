# Live-path qualification

Status: canonical. Owns the public endpoint contract probe, source ratchets and
requirements-only environment smoke. Read before qualifying an attended live
path or adding an outbound HTTP caller. This is no live-trading authorization.

## Public contract probe

From a clean reviewed checkout containing RE-1, run once before an owner
preflight or as a daily attended check:

```powershell
python -m weather.operations.live_contract_probe --token <configured-token> --condition <condition-id> --public-address <public-address>
```

Choose a token/condition pair from `config/location_market_events.json`, with a
currently rewarded condition, and supply a public address explicitly. The probe
never discovers an account from credentials. It makes at most one request per
contract: geoblock GET, Polygon `eth_blockNumber` POST, CLOB book GET,
per-condition rewards GET, exact public address/condition positions GET. It
prints five JSON PASS/FAIL rows and source hashes, and exits nonzero on failure.
It does not retry, follow redirects, page a universe, or read an authenticated
endpoint. A geoblock shape PASS is not proof of geographic eligibility.

The frozen RE-1 files mix public reads with credentials and order code. Until
that separation can be changed after the campaign, `live_contract_sources`
compiles an explicit list of their **unchanged AST definitions** in an isolated
namespace. It does not import those modules or execute module initializers.
The same request construction, User-Agent, clean-tip check, public reader and
consumer validation run against a real bounded opener. Unknown imports fail
closed. The source hashes identify the exact code tested. This is function-path
qualification, not proof of the full module-import/live-session composition.
The single-book check validates the fields consumed by the two-book live path;
it deliberately does not fetch fee-rate endpoints or a second book.

## Shared HTTP and ratchets

New JSON callers use `weather.http.json_request(url, method=..., body=...,
timeout=..., max_bytes=..., headers=...)`. `body` is a JSON value; timeout and
response size are mandatory and bounded. `user_agent(component)` supplies
`weather/<component>/<short-commit>` (`unknown` outside a Git checkout).
Accept is always JSON. Errors carry `status` and `body_preview` (at most 200
characters); callers own retries. Redirects fail. Do not log error bodies from
authenticated endpoints. `location_config_refresh` is the migration example.

`tests/operations/test_live_path_ratchets.py` inventories urllib requests and
openers, imports at every lexical depth, and PowerShell argument vectors,
including canonical executable variables. `live_path_allowlist.json` owns the
exact file:line HTTP exceptions and dependency issue list. Delete exceptions
as debt is removed; never add a new bypass to make a test pass. Transitive
installation alone does not count as a direct dependency declaration. Optional
distribution name mappings allow the static test to run without the live SDK.
PowerShell spawns must put `-ExecutionPolicy Bypass` before the execution mode;
this changes the child process policy only, never the machine/user policy.

## Fresh environment

```powershell
scripts/ops/fresh_venv_smoke.ps1 -PythonPath <absolute-project-python>
```

The script dispatches the fixed `weather.operations.fresh_venv_smoke` module
through `workstation_heavy.ps1`. It holds the host/principal-bound shared lease
and kill-on-close Job while creating a random scratch venv, installing only
`requirements.txt` from public PyPI, and importing each `mm_*` and `re1_*` module
in a separate child. The import child refuses network connections and `.env`
reads. Missing RE-1 modules fail the inventory. Each row names an import failure
and missing package; cleanup deletes only that invocation's checked temporary
venv. A wrapper kill may leave its temporary directory for explicit review.

The smoke tests module initialization, not dependencies imported lazily inside
functions. The AST dependency ratchet covers those names separately. The live
SDK extra is intentionally not installed by the requirements-only smoke.
Never run while a live session owns the shared lease. Follow the host load
policy and any dated mission deadline for a full suite.

## Venue fixtures

`tests/fixtures/venue_shapes/README.md` owns provenance and reconstruction
limits. Credential-named keys are forbidden recursively. Never label a
reconstructed envelope as an original retained wire message.

## Update when

Update alongside endpoint scope, CLI flags, selected source definitions,
transport semantics, wrapper admission, smoke behavior or ratchet policy.
