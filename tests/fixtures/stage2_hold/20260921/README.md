# Mission 80b: public-input, fake-exchange rehearsals

The complete configured tomorrow-market selection was captured on 2026-09-21
at 14:55 UTC from unauthenticated Gamma event, per-condition reward, book and
fee endpoints. `selection.json` retains the response bytes/provenance and all
ranked or refused rows. No account endpoint, credentials or grant was used.

Miami, Dallas and Los Angeles are the first three qualifying conditions in
that table. Each subdirectory retains the real hold controller's journal,
frozen prediction and bundle from a closed in-memory exchange. Only Miami is
marked selected for a hypothetical live seal. No live seal was produced.

**Simulated:** the 125-second accelerated clock, resting orders, added own
depth, two visible minutes, scoring booleans, geography receipt and cancellation
responses. These replay one real public observation; they are not a time
series, observed rewards, eligibility evidence, paid evidence or trading
authority. The maker address is an explicit public fixture label. All source
network responses are public; no authentication headers or source IP are kept.

Reproduce any band from the repository root with the project interpreter:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_live_pilot_cli stage2-hold rehearse --condition 0x5e0efc3ebbf93111ed44ccca7aa815a058cacd59fbcfe648fd787ad7ef4dca90 --public-capture tests/fixtures/stage2_hold/20260921/selection.json --out data/research/stage2-hold-replay/miami
```

Use a new output directory each time. The same command accepts
`--scenario fill_first` or `--scenario reject_second` for fake transport faults.
Omitting `--public-capture` fetches a new complete public selection and may
correctly refuse this formerly eligible condition. Selection rules never change.
