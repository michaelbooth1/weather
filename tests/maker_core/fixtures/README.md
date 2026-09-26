# Phase 0 offline reference fixtures

`fictional_domain.py` implements the four v0.1 Protocols using only contracts.
It filters captured bias records by query time and expires them after one hour.
The event replay test runs decisions and a journal without a production loader.

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
