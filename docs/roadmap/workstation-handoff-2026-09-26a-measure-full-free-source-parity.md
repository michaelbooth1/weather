# Workstation handoff 2026-09-26a — measure full free-source parity, with ECCC actually working

## Goal

A trustworthy measurement of what repairing the model's dead feature block is worth, with Toronto's
ECCC fields populated — which has never yet been done.

## Why this mission exists

Two production measurements taken on 2026-08-06 change the picture that `-09-22a` was working from.

**1. There is no ECCC corruption. `-09-22a`'s integrity failure was a verifier bug.**

`-09-22a` reported that every Toronto ECCC raw-payload receipt failed its pinned hash, fell back to
METAR, and therefore measured parity with `humidity`, `pressure` and `pressure_trend_3h` at **0%
population** — the Toronto-only fields that were the point of the work.

Verified on the production host: **836 of 836** `eccc_swob` payloads across five Toronto market-days
reproduce their declared `payload_hash` exactly, and those payloads contain `rel_hum`, `stn_pres`,
`dwpt_temp`, `air_temp` and `mslp`.

The cause is that `payload_hash_algorithm` is **`sha256-canonical-json`**, not a raw-bytes digest:

```python
# WRONG - fails 100% of the time by construction
hashlib.sha256(path.read_bytes()).hexdigest() == row["payload_hash"]
# RIGHT
hashlib.sha256(canonical_json(json.loads(path.read_bytes())).encode("utf-8")).hexdigest()
```

The stored file carries a trailing newline and is exactly one byte longer than the hashed canonical
form. **Follow `point_in_time_evaluation.py:1884` and gate on the declared `payload_hash_algorithm`
before comparing anything.** Full detail in
[`RETRACTED_AND_FALSE_LEADS.md`](../operations/RETRACTED_AND_FALSE_LEADS.md).

**2. The blindness is far larger than "9 of 19 at 09:00–14:00".**

Measured directly on production feature rows:

| Measurement | Result |
| --- | --- |
| Toronto, 5 days, **all** hours 07–20 (919 rows) | 10 base features at **0%**, every hour |
| Fleet, 11 markets, Aug 3–5 (5,761 rows) | the same 10 at **0.0%** |
| `artifacts/models/hgb/feature_model_hgb.pkl` | **8 of 29 trained features dead at serve in all 14 hour models** |

It is not a window. **The model is blind at every hour, in every market, always**, and ~28% of every
prediction's trained inputs are imputed medians. The dead set is the whole local-meteorology block —
trajectory, moisture, pressure, wind. See
[`ESTABLISHED_FINDINGS.md`](../operations/ESTABLISHED_FINDINGS.md) §4.

**So `-09-22a`'s 6.58% severe-tail result is not a small effect from a marginal repair. It is a
partial repair, measured with half of itself disabled, of the largest known defect in the model.**

**3. The defect is ROUTING, and the adapter already parses what is missing.**

Traced on 2026-08-06 and recorded in [`ESTABLISHED_FINDINGS.md`](../operations/ESTABLISHED_FINDINGS.md)
§4. In short: `extract_live_features` binds `history`/`current` to the disabled `wu_history` /
`wu_current` sources, only the observed-high path receives the station fallback, and
`derive_station_observation_data` (`model_sources.py:315-326`) returns a 10-key dict carrying just
`temp_native` and `max_since_7am_native` — while holding the full observation in `latest`.

Meanwhile `eccc_swob_history.py:340-375` already emits `dewpoint_c`, `humidity`, `pressure`,
`wind_speed_kmh`, `wind_gust_kmh`, `wind_dir_deg` and `clouds`, in the field names the extractor
asks for. A real captured Toronto payload parses to `dewpoint_c=17.2`, `humidity=81.0`,
`pressure=997.8`, `wind_speed_kmh=6.5`, `wind_dir_deg=129.0`, and payloads accumulate up to **20
hourly rows**, so the trend features have their history too.

**You are not required to act on this — the mission is measurement — but you should know it before
choosing an approach.** `-09-22a` re-parses `raw_payload` in a separate guarded module. That is safe
and it is why its flag-off path is byte-identical, so **keep using it for this measurement.** If your
findings suggest the durable repair belongs in the adapter instead, say so in the report as a
recommendation; do not restructure the serving path in this mission.

Watch for one real name mismatch: the extractor reads `wind_kmh`, the adapter emits
`wind_speed_kmh`.

## Start from this, do not re-derive it

Read [`ESTABLISHED_FINDINGS.md`](../operations/ESTABLISHED_FINDINGS.md),
[`RETRACTED_AND_FALSE_LEADS.md`](../operations/RETRACTED_AND_FALSE_LEADS.md) and
[`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) first. Take as given:

- The `-09-22a` implementation on `codex/workstation-build-free-source-parity-dark-2026-09-22a`
  (tip `538b5acb`). Its flag-off path is byte-identical to master across 2,868 envelopes and its
  guarded design is sound — **reuse it, do not rewrite it.**
- Its severity rule, copied unchanged from `-08-22a`. **Do not tune it.**
- Crossed date × market clustering is mandatory. `-09-22a` ran at D=5; report your own D and M.
- Pooled Brier crossed zero in `-09-22a`. Expect that it may again; that is a finding, not a failure.

## P0 — prove ECCC now hydrates

Before any effect measurement, re-run `-09-22a`'s frozen replay with hash verification corrected, and
report the population table. The single number that matters: `humidity`, `pressure` and
`pressure_trend_3h` should move off **0.00%** for Toronto.

**If they do not, stop and report why.** Everything below is worthless if the fields are still empty,
and a second wrong cause is more valuable to know than a re-measured effect.

## P1 — measure full parity

With ECCC hydrated, re-measure on the same frozen corpus and predeclared severity rule:

- severe-tail SSE, all-severe / excluded / qualified lanes, with crossed intervals and D, M
- pooled daily-first Brier as guardrail
- centre delta, to re-test whether blindness moves the centre
- per-hour and per-market heterogeneity
- **the population table for all 10 dead features**, which is the mission's primary deliverable

Report the `-09-22a` values beside yours so the ECCC contribution is separable from the METAR-only
baseline.

## P2 — state what a fleet retrain would need

Do not fit anything. State what evidence would justify retraining on the repaired feature set, and
whether this measurement supplies it. Keep the flag **off by default**; the byte-identical flag-off
guarantee must survive unchanged.

## Boundaries

[`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) §2 binds in full. In addition:

- **Do not enable the flag in production, do not promote, do not fit a candidate, do not retrain.**
- **Do not weaken the observed-high floor**, and do not "fix" blindness by widening distributions.
- Free sources only. Open-Meteo/METAR/ECCC as already configured; **no paid provider, no new
  credential, no WU re-enable.**
- Reserved window: read `docs/operations/reserved-confirmation-window.md` before touching evidence.
  Nothing is reserved today; if that has changed, stop.
- Concurrent owners — do not edit: `schema_registry_data.py` (`-09-19a`, `-09-20a`),
  `forecast_history.py`, `base_retrain.py`, `nightly_retrain.py`, `daily_refresh.py`,
  `live_variant_settlement_scorecard.py`. `model_features.py` is co-owned with `-09-20a`; keep any
  change additive and inside the existing guarded block.
- Roll verdict from the retained `runtime_identity.source_scope_files` arrays, not `SOURCE_PATTERNS`.
  Do not merge.

## What would falsify this mission

1. **ECCC still does not hydrate** after correct verification — the cause is elsewhere and P1 is void.
2. **Full parity is no better than METAR-only.** If adding humidity and pressure does not move the
   severe tail beyond `-09-22a`'s 6.58%, the Toronto-only fields are not where the value is.
3. **The severe-tail interval crosses zero at your D and M.** `-09-22a` had a lower bound of 0.49% at
   D=5; that is fragile and may not survive.
4. **Repair moves the centre the wrong way.** `-08-22a` and `-09-22a` both found blindness is not the
   centre mechanism. If full parity contradicts that, say so loudly.
5. **Populating the fields degrades pooled Brier distinguishably.** A model trained with these
   features present, then served them for the first time in months, could behave worse than one
   consistently served imputed medians. That is a real possibility and it would be the most important
   result this mission could produce.

## Deliverables

- Branch: `codex/workstation-measure-full-free-source-parity-2026-09-26a`, based on `-09-22a`'s tip
  `538b5acb` merged with current `origin/master`.
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-measure-full-free-source-parity.md`
- Report structure per [`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) §5.
- Push the branch only. No PR, no merge, no force-push, no branch deletion.
