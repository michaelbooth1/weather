# Retracted Claims and False Leads

Status: canonical. Written for LLM agents.

**Everything in this file looks true, or was once believed true, and is not.** Each entry cost real
agent hours at least once. Read this before acting on a surprising result, and before "discovering"
something in the list below.

Companion to [ESTABLISHED_FINDINGS.md](ESTABLISHED_FINDINGS.md), which holds what survived.

---

## 1. Retracted model claims

### The 24.69% absorption claim — RETRACTED

Published, then found to **cross zero under crossed date x market clustering**. It was produced with
exchangeable market-day resampling, which yields intervals that are too narrow.

**Do not cite it.** The correct served figure is **18.32%**.

### The 5.39% figure — RETRACTED as described

It was a **separately fitted transform**, not a propagated one. The real served value is **18.32%**.
A separately fitted transform measures what a fresh fit could achieve, not what the deployed pipeline
does — those are different claims and the difference is the whole point.

### The 78% absorption leak — NEVER EXISTED

It was **mismatched denominators**, not a leak. Time was spent hunting a defect that was an
arithmetic artifact. **Only the floor's absorption interval excludes zero. The floor stays.**

### item-224's "win" over the market — LEAKAGE

The one result that appeared to beat the market was leakage. Toronto parity is **underpowered, not a
win**. Any future claim of beating the market must clear the method rules in `ESTABLISHED_FINDINGS.md`
§5 before it is reported as real.

### The age-curve evidence for the cool bias — DIED 2026-08-05

Do not build on it. The cool bias itself survives (`ESTABLISHED_FINDINGS.md` §2); the *age* mechanism
explanation does not.

### Blindness as the cause of centre displacement — REJECTED

Intuitive, and wrong. In the excluded lane, blindness moves the centre **warmer** (`+0.005453` bands)
while the served displacement is `-0.297504` bands **cooler**. Blindness destroys information; it is
not the centre mechanism. The actual mechanism is floor truncation (`ESTABLISHED_FINDINGS.md` §2).

### "The gap is 1.7x" — CONTAMINATED WINDOW

On the clean regime it is **1.24x**. The larger figure came from windows mixing artifact regimes.

### "Recalibration will close the gap" — FALSE BY DECOMPOSITION

98.88% resolution / 1.12% reliability. There is almost no calibration error left to harvest. The gap
is information. Calibration work is not a path to edge.

---

## 2. Statistical traps

### The slice gate was a lottery

False rejection rate **99.885–99.9905%** — it rejected a **better** candidate. **Every slice-gate
rejection in that month is uninformative.** Do not treat a historical rejection as evidence about a
candidate's quality.

### The 5-date window was a convention, not a constraint

**We have 34 date clusters.** Analyses limited to 5 dates were self-limiting for no reason.

### `quality_grade == "complete"` is NOT the admission bar

The bar is **`promotion_countable`**. The complete-only bar starved a previous corpus and produced
underpowered results that were then misread as null findings.

### `market_day_labels.csv` is NOT the settlement authority

**`data/settlements/<market>/ledger.jsonl` is.** The CSV is a projection and can disagree.

### `2026-07-31` is not a date cutoff

It is an **artifact-provenance regime boundary**. Filtering by target-date age instead of artifact
provenance silently mixes regimes. Anchor commit: `b77cfbed`.

---

## 3. Operational false alarms

### "A reboot kills the fleet" — FALSE

Capture is all S4U and survives unattended reboot. This was fixed and verified. Do not re-raise it.

### "The merge report shows a failure" — STALE, BUT REAL

The merge `0x1` is stale-but-real, and the merge report file is **last-write-wins**. No merge trigger
is scheduled. Read the file's timestamp before reacting to its contents.

### "99 stale / 33 permission" on the maker — WRONG FRAMING

That was a **post-window rollover tick**, not the active window. Recorded by the operations agent as
its own error. Do not build on it.

### LA's `stale_code` was not an LA defect

It was **process-wide deployment drift across all 12 markets**, and it is **already resolved** — the
01:15 roll onto current code cleared it. Do not re-fix it.

### `live_variant_settlement_scorecard` reporting BLOCK with 0.0 coverage — CORRECT BEHAVIOUR

It is a **release/variant-contract gate**, not a skill series. Served rows on a pre-release host carry
blank `release_id` and `release_identity_status=research_unbound_non_countable`, and the scorecard
correctly requires an explicit immutable release ID. It should begin returning real verdicts after
release #1. **Do not "fix" it by relaxing release identity or deleting expected variants** — that
turns a valid gate into a misleading skill claim.

### "All Toronto ECCC payloads failed their pinned hashes" — FALSE, THE VERIFIER WAS WRONG

`-09-22a` reported that every available Toronto ECCC raw-payload receipt failed its pinned canonical
hash, fell back to METAR, and therefore shipped free-source parity with `humidity`, `pressure`, and
`pressure_trend_3h` at **0% population**. **There is no ECCC integrity problem.**

Verified on the production host 2026-08-06: **836 of 836** `eccc_swob` payloads across five Toronto
market-days reproduce their declared `payload_hash` exactly. The payloads also contain `rel_hum`,
`stn_pres`, `dwpt_temp`, `air_temp` and `mslp` — precisely the fields reported as unpopulated.

**The trap:** `payload_hash_algorithm` is **`sha256-canonical-json`**, not a raw-bytes digest. The
hash is taken over `canonical_json(parsed_payload)`, not over the file. The stored file carries a
trailing newline, so it is exactly **one byte longer** than the hashed canonical form (8,014 vs
8,013 in the checked example) and its raw digest never matches. Hashing the file bytes fails 100% of
the time by construction, which is what "all 254 failed" actually means.

```python
# WRONG - fails every time
hashlib.sha256(path.read_bytes()).hexdigest() == row["payload_hash"]
# RIGHT
hashlib.sha256(canonical_json(json.loads(path.read_bytes())).encode("utf-8")).hexdigest()
```

**Consequence: full free-source parity has never actually been measured.** `-09-22a`'s severe-tail
result (6.58%, crossed CI [0.49%, 14.14%], D=5) was measured with Toronto's ECCC-only fields
needlessly absent — and Toronto humidity/pressure were the point of that work. Re-run before drawing
any conclusion about what free-source parity is worth.

**Generalises: a 100% failure rate is a signal about the verifier, not the data.** Check the declared
algorithm before concluding that canonical evidence is corrupt.

### The `SOURCE_PATTERNS` glob is NOT the roll-sensitivity test

Roll sensitivity is the **loaded-module import closure**, recorded in the capture status files as
`runtime_identity.source_scope_files`. Markdown under `docs/` is not a source-identity file and is
roll-free. Deriving a roll verdict from the glob over-reports and wastes quiet windows.

### Capture-loop restart risk is not avoidable by keeping a schema local

`schema_version()` raises `KeyError` on any name absent from the central `SCHEMAS_BY_NAME`, so central
registration in `schema_registry_data.py` is **mandatory**. That module is in **all four** capture
import closures. The roll is unavoidable — the objective is to make it **purely additive** so it is
behaviourally inert, not to eliminate it.

---

## 4. Backlog and branch traps

### Branch names lie

`-09-01a` is named "consolidate merge queue" and contains a 1,536-line point-in-time training corpus,
a fail-closed all-market base retrain, and the PIT binding. It was nearly retired as housekeeping.
**Read the commits before judging a branch.**

### No held branch clears any of the 97 retrain blockers

Checked exhaustively. Do not go looking for one.

### Agent reports exist only on unmerged branches

**46 reports live nowhere else. Never delete a branch**, even one declared superseded. Retiring a
branch from the merge queue and deleting its ref are different operations; only the first is ever
authorized.

### A "held" branch is not necessarily refreshable

`-09-01a` sat 59 commits behind master. Held branches rot. Age a branch against master before
planning work that depends on it.

---

## 5. How to add to this file

When a claim is retracted or a false lead is closed, record:

1. **What it looked like** — the version that seemed true.
2. **What is actually true**, with the corrected number if there is one.
3. **Why it fooled us** — the mechanism, so the same shape is recognised next time.

Do not delete retracted claims from the record. A deleted mistake gets re-derived; a documented one
does not.
