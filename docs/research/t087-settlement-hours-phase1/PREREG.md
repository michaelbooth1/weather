# T087 E8 — Phase 1 preregistration

Frozen before any real settlement input is opened. Phase 1 builds and tests
machinery only. Authority: prompt.md and RQ-COMMON.md, with the verbatim named
owner-opened label-integrity scope in prompt.md. No other look opens.

Hypothesis (DERIVED, directional): including the admitted previous evening can
raise, never lower, the maximum relative to a strict local date, when the
linked window covers that whole date. It can leave the event band unchanged.
The paid band may agree with either reading or neither; no direction is assumed
for that comparison. This is descriptive label integrity, never an edge claim.

Population planned for the master's one Phase 2 extract: all 12 BUILTIN_SPECS,
local target dates 2026-10-23..2026-11-09 inclusive (last fully ended date at this
Phase 1 freeze). No expansion cities. Denver uses KDEN, not KBKF. Dates are not
extended automatically. No observations before D-1 21:00 or at/after D+1 00:00
local. Endpoints are constructed in the market zone, then compared in UTC.

One contrast / two fixed readings: strict local date versus the dated source
link's [date-hours, date) intersected with the authorized observation envelope
and capped at D+1 00:00. A source link requiring an earlier start, ending before
the target day ends, or naming a different station is refused, never silently
clipped into apparent coverage. The link's next-morning tail is explicitly
outside this extract; this does not test its full, untruncated query response.

Inputs: minimal IEM routine-source observations (valid, metar, declaration 3;
optional receipt_time and next routine timestamp only if actually recorded),
dated resolutionSource, band labels, and the final Gamma paid band extracted
by the master. No other weather fields, prices, models or own-session records.
Master certifies a complete scoped extract; missing/unknown days stay refusals.

Metric: enumerate every comparable day whose parsed event bands differ; show
both maxima, rounded degrees, tied maximum times, and each match to paid band.
Also disclose expected, supplied, missing, refused and comparable keys and
effective distinct dates. Exact enumeration only: no significance test, CI,
forecast score, profitability metric, fitting, bootstrap, or selection of arms.
No real value or rate is measured in Phase 1, so an interval is not applicable.

Kill/refusal rule: invalid dates/schema/source geometry, incomplete extract,
unparseable/nonpartitioning bands, ambiguous duplicate observations, unsupported
correction timing, or no routine temperature prevents a comparison for that key.
No WU fallback or extra data read is authorized by this task. Zero differing
bands would describe no discrepancy in this finite admitted extract, not prove
the venue's general rule. Verdict vocabulary: DESCRIBE only.

Sanity controls: synthetic front day, tied maxima and degrees in the same band,
half-up ties in F and C, negative C, SPECI/unknown exclusion, COR replacement,
late correction, 27/30-hour geometry, UTC/local boundaries and DST fold. Any
failed control prevents handoff as ready.

Reuse: this reads no real development dates and no post-09-29 data in Phase 1.
DEV_WINDOW_LEDGER at source 73140b20eed0f81c8fa26bb5faf6defcb269533a says the
candidate denominator is at least 214 plus unitemised earlier reads. This task
is D, not K; its proposed dates are outside that ledger's 07-31..09-29 scope,
so a reuse count for these post-cutover dates is not supplied there. Do not
invent zero prior exposure. Master must log the named Phase 2 read separately
and bind the exposure record before running it. Phase 1 adds zero data reads.
