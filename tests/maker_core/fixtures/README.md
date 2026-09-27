# Phase 0 offline reference fixtures

`fictional_domain.py` implements the four v0.1 Protocols using only contracts.
It filters captured bias records by query time and expires them after one hour.
The event replay test runs decisions and a journal without a production loader.

`re1_sessions.json` is the owner-authorized read-only projection of twelve RE-1
attempt journals (eleven launched sessions). Every source SHA-256, byte count,
row count, minute sequence and recorded snapshot clock is retained. Only books,
reward terms, sizes, quote prices, requote leg indices, and terminal fields used
by the parity test survive. No account/order/token identities, wallet balances,
SDK payloads, credentials, signatures or raw journals are included.

`re1_session_export.py` is the bounded explicit-path derivation, with the pinned
original RE-1 SecretGuard unchanged and a stricter stop-on-detection check.
The owner explicitly allowed the `lifecycle_key` false-positive exception only
when it equals `order_id` on a normalized official user-stream event; neither
field survives projection. Every file is guarded before projection, its hash
chain is verified, and it is guarded/hashed again to detect concurrent change.
Normal tests never call the exporter on local campaign files.

`re1_session_replay.py` drives the existing `blind_re1` kernel with carried state;
`re1_session_findings.json` retains exact comparison hashes, every mismatching
minute index, the first divergence, and independently measured recorded-state
reasons. Ten projected traces fail byte equality (strict expected-failure tests);
two match only the minute/fill-terminal projection. No full session is qualified.
The [110l report](../../../docs/roadmap/agent-report-2026-09-110l-maker-replay-harness.md#recorded-session-qualification--2026-09-26-owner-authorization)
defines the projection, neutral scaffolding, missing transport coverage and
reproduction command. Matching projected fill termination is conditional on the
recorded fill flag; it does not validate a fill model or economic result.

`re1_reward_quote.py` is a frozen, unmodified source copy from
`2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8:src/weather/market/reward_quote.py`.
The new price module changes its reward import to the copied core kernels and
adds independently tested helper facades. This is a source dependency for
offline differential testing, not runtime adoption of that branch.

`re1_price_parity.json` projects public quote inputs, size and quote prices from
the local read-only campaign's twelve attempt selection files. It also retains
the first recorded minute prices where present (eight attempts), with SHA-256
of each original selection and journal. It contains no account responses,
identities, orders, signatures, auth fields, balances or credential material.
Attempt folders are not session counts. Four attempts have no minute-price row;
those tests prove recorded selection-price parity only. Freshness/close clocks
are synthetic in this price-only replay; no live-state parity is claimed.

`replay_bundle.py` creates three synthetic closed UTC days for two fictional
markets, with a missing book minute and later-captured plugin/settlement inputs.
It supplies the [neutral replay envelope](../../../docs/operations/maker-replay-bundle.md)
tests. It contains no production data and proves no real-data fill or parity result.
