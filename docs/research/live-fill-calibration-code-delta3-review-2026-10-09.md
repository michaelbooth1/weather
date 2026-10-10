# Delta review 3: LFC range `468607b13..acd052a2d` and clarification D at `1cb231033`

Reviewed range: `origin/claude/lfc-pinned-ext-20261009` `468607b13..acd052a2d0c38e701e951f7e5efd53d0a7e11781` (6 commits,
19 files: `6c45aaa14` N-10, `6e418f0f8`+`64e294f28` ext, `0311b8cf7` fee class rule, `388043de5` reader any-LAN/fresh,
`acd052a2d` deadline). Clarification D read at `1cb231033` (`origin/claude/live-fill-calibration-runbook-20261009`),
path `docs/research/live-fill-calibration-clarification-D-2026-10-09.md`. Method: `git --no-optional-locks` diff/show/
cat-file only; read-only; no pytest, no live command, no `.env`/`config/local`, no `data\`. Line numbers are
`git show acd052a2d:<path>` numbers unless another commit is named. Tests were read, not run.

## Verdict: PASS-WITH-REQUIRED-FIXES

- **Code at `acd052a2d`: PASS.** Nothing in the range can lose more than L, place or keep an order past its GTD, or
  let the fee classifier pass on missing, ambiguous or stale data. The classifier fails closed at all five
  application points; the stage-2 hook is additive; the reader's fresh path is GET-only, rate-capped and keeps the
  account-mismatch check; the deadline refusal precedes the campaign root, the mutex and any credential. No code fix
  is required before session 0 (two LOW code items are recommended, section 6).
- **D ready to sign: no as drafted (sha256 `238a9c67…` verified); yes after four text precisions (R-D1..R-D4,
  section 5) and a re-hash.** None of them changes a limit; each corrects a sentence that claims more than the code
  enforces or omits a signed value D changes.

---

## 1. Money safety (question 1)

### 1a. L, GTD, sizes, caps

No file in the range touches the L formula, `BUDGET_PUSD`, `SIZES`, `BAND_CEILING`, the order/band caps, `cancel_leg`,
`Session.cleanup`, the GTD (`expiration = end + 60 s`, `re1_attended.py:481`) or the ledger schema. The only behaviour
changes on the live path are new refusals (fee class, deadline) and a wrapper on `venue.client` that refuses before
signing. `load_conditions` and `shadow-scope-union` only grow the exclusion sets or refuse (section 3).

### 1b. Can we submit on a market where the maker is charged?

The classifier (`lfc_fees.classify`, 142-199) admits exactly two classes and refuses everything else:

- `WEATHER_TAKER_ONLY`: Gamma `feesEnabled is True` (type-checked, 161-163), `feeType == 'weather_fees'` (176),
  `feeSchedule` present with exactly the keys {rate, exponent, takerOnly, rebateRate} and `takerOnly` a real bool
  (121-139), CLOB `fd` present with exactly {r, e, to} (182-184), `fd.to is takerOnly` (185), `takerOnly is True`
  (187), `(r, e) == (rate, exponent)` (189), every token's `/fee-rate base_fee == takerBaseFee == tbf` and
  `makerBaseFee == mbf` (191-196). A negative `rebateRate` (a charge) refuses `maker_fee_nonzero` (137-138).
- `FEE_FREE`: `feesEnabled is False`, no `feeType`/`feeSchedule`/`fd`, base fields absent or 0, every `base_fee` 0
  (164-172).
- Any builder field on Gamma or CLOB that is not zero-ish refuses `builder_fee_nonzero` (157-158); any extra
  `maker*` field that is non-zero refuses (109-118, 159-160).
- The signed order: `SignedOrderGuard.create_limit_order` refuses any `*builder*` or `*fee*` kwarg before calling the
  SDK and `check_signed_order` requires `signed.builder == bytes32 zero` and every `*fee*` attribute zero-ish
  (313-330). `guard_signed_orders(venue)` is applied in `run_live` right after `OwnerVenue` is built and before any
  submit (`lfc_cli.py:583-585`); `OwnerVenue.submit` signs through `self.client.create_limit_order(**request)`
  (`re1_transport.py:463`), kwargs only, so the wrapper intercepts it; `post_order`, `signer`, `_ctx` pass through
  `__getattr__`. An SDK order type without a `builder` attribute would read `'none'` and refuse (fail closed).

Residual if the venue metadata itself were wrong (takerOnly true but makers charged): the weather taker schedule is
`0.05·p(1−p)` per share (EF §10o); on a BUY at price p the fee is deducted from the shares received, so the cash
outlay is still bounded by L and the value lost is `0.05(1−p)·cost ≤ 0.05·0.83·100 ≈ 4.2 pUSD` campaign-wide at the
0.17 price floor. That cannot breach L; D7 should state it (R-D3).

### 1c. Missing, ambiguous or stale data

- Missing: `snapshot['fee_evidence']`/`['rules']`/`gamma`/`clob`/`fee_rate_bps` absent or wrong type → `KeyError`/
  `TypeError` → `fee_fields_unreadable` (144-151); `evidence['error']` set by a failed read → unreadable (150);
  `None` snapshot (no `submit_snapshot`) → `TypeError` → unreadable. Booleans, NaN, infinities, negative or
  fractional base fees → unreadable (78-106). `fee_key` returns a never-equal key when unreadable (227-234).
- Ambiguous: Gamma vs CLOB vs `/fee-rate` disagreement → `fee_fields_inconsistent`; unknown `feeType`, schedule key
  or `fd` key → `fee_schedule_unknown`.
- Stale: Gamma market reused only from the event read of the same selection pass and only ≤ 60 s old
  (`FeeEvidenceBooks.fee_evidence`, 278-290; the cached entry is popped, so every later snapshot re-reads Gamma);
  CLOB `/clob-markets/<condition>` is read fresh every time; `/fee-rate` comes from the snapshot being classified.
  The submit-time snapshot is the fresh `submit_snapshot` (≤ 10 s old, `re1_attended.py:459-462,477`); the
  selection-time row snapshot (≤ 30 min, N-7) is re-checked at submit and every minute.

### 1d. The five application points, traced

| Point | Where | Both profiles? | Fails closed? |
| --- | --- | --- | --- |
| Selection (preflight and live) | `_selector` → `require_maker_fee_zero(table, require_fee_free=session0)` (`lfc_cli.py:421-436`, `lfc_fees.py:213-224`); `run_preflight` and `run_live` both use `select` | Yes (`Session0Books`/`LfcPublicBooks` both carry `FeeEvidenceBooks`) | `RuntimeError(code)` before any session object; a row without `snapshot`/`token_ids` → `fee_fields_unreadable` |
| Each session-0 candidate | `session0_candidate` (`lfc_pilot.py:206-211`): `maker_fee_refusal(..., require_fee_free=True)` then `sibling_fee_refusal(event_fee_fields)` | Session 0 | `QuoteRefused` → row ineligible; `event_fee_fields` missing/empty → `fee_fields_unreadable` |
| Session start | `PilotSession.__init__` classifies the chosen row (438-440); `before_first_post` journals `lfc_fee_rule phase=selection` and raises `HoldEnd(code)` (524-527) before the first submit | Both | Yes; see N-12 for the (dead) duplicate-keyword path |
| Every submit | `authorize_post` (550-558): both tokens of `submit_snapshot`, class must equal the opening class else `fee_class_changed`; `HoldEnd` before `_pending` is set, so no intent and no POST | Both | Yes (`test_a_fee_refusal_at_submit_posts_nothing`, `test_a_class_flip_before_submit_posts_nothing`) |
| Every minute | `minute_extra` (582-597): re-classify, class flip → `fee_class_changed`, any fee-field change (`fee_key`) → `market_rules`; `HoldEnd` → cleanup | Both | Yes (`test_a_fee_change_mid_session_ends_it`, `test_session0_ends_when_its_market_becomes_fee_enabled`) |

### 1e. Stage-2 hook

`PublicBooks.EXTRA_CLOB_PATHS = ()` (`mm_stage2_selection.py:177`) and the allowlist adds only
`any(re.fullmatch(p, parts.path) for p in self.EXTRA_CLOB_PATHS)` (189): with the empty default this is `False`, so
the RE-1/Stage-2 allowlist is byte-for-byte the previous set. The only class that sets it is `FeeEvidenceBooks`
(`lfc_fees.py:255`, `/clob-markets/0x[0-9a-f]{64}` full match), mixed only into `LfcPublicBooks` and
`Session0Books` (`lfc_pilot.py:290-294`). RE-1 behaviour cannot change. (The file is loop-imported on the production
host; roll verdict is out of this review's scope.)

## 2. The reader (question 2)

- **GET-only:** `dispatch` refuses `method != 'GET'` (405) after source and token and before routing
  (`wallet_reader_server.py:20-27`); `ReadTransport.request` always builds `Request(url, method='GET')` (166).
- **Rate-capped:** the fresh branch only skips the cache lookup (`if not fresh and url in self.cache`, 148); the
  budget check `remaining() <= 0 → upstream_minute_budget` (153-154) and `self.calls.append(now)` (169) run for
  fresh and cached alike, 30 per rolling 60 s (92-95). The failed result is cached too (195), so the 10 s failure
  cache still applies to the next cached read. Test `test_fresh_reads_count_against_the_rate_cap_and_are_refused_over_it`.
- **Account mismatch:** `open_orders(fresh=True)` is the same method; the `maker_address != funder` check runs after
  `pages()` regardless of `fresh` (`wallet_reader.py:185-190`). `fresh` is a keyword, never a query param to
  upstream, so `check_request`'s param allowlist is unchanged (139).
- **Query surface:** `fresh` is allowed only on `/open-orders` and only with the value `1` (36-42); any other
  value or path → 400. The client refuses `fresh` for any command but `open-orders` and any non-bool value
  (`wallet_reader_client.py:25`).
- **Source admission:** `source_admitted` (RFC1918 or 127/8 literal IPv4; `--allow` narrows to exact) is applied in
  `verify_request` (`wallet_reader_server.py:126-127`) and again first thing in `dispatch` (20-21). The bind stays
  `lan_ip` (RFC1918 only, 118-121). Token unchanged and always required.

## 3. Deadline, `load_conditions`, `shadow-scope-union` (question 3)

- **Deadline before any lock or credential:** `run_preflight` and `run_live` call `check_flags(args)` (pure argument
  validation, `lfc_cli.py:108-119`) then `session0_deadline_refusal(_now(), profile)` (497-499, 530-532) before
  `pilot_root()`, `Ledger.open`, `live_mutex()` and `load_owner_credentials`. `_now()` is aware UTC (67-68);
  `utc(now) >= SESSION0_DEADLINE_UTC` (125), `datetime(2026,10,15,tzinfo=utc)` (`lfc_constants.py:65`). Counted runs
  (`profile.session0` false) are untouched. Tests cover one second before, the instant, and counted runs.
- **A dict with both keys refuses:** `keys = {'conditions','extra_conditions'} & set(value)`; `conditions` is taken
  only when `len(keys) == 1`, else `None` → `ValueError('condition_file_shape')` (354-360). Neither key → refuses.
  `update_windows_utc` is ignored but hashed (sha256 over raw bytes). Test `test_condition_file_refuses_a_dict_naming_both_lists`.
- **`shadow-scope-union` touches no tape and fails closed:** inputs are the registry (`all_specs`,
  `event_slug_for_date`) and `maker_core.venue.public_feed.PublicFeed(UrllibTransport())`, whose allowlist is
  Gamma `/events?slug=…` (≤ 20 slugs per batch, `MAX_SLUGS = 20`, code batches by 20), CLOB book/rewards and public
  data-api trades, GET only, no account filter, no redirects (`public_feed.py:44-66`). Any event missing, without
  markets, or with a malformed `conditionId` raises (`lfc_cli.py:378-391`); `write_new` opens the output `xb` (refuses
  an existing file) and runs only after the union is complete, so nothing is written on refusal (403-404). Tests cover
  missing event, failed read and "opens no path but its output".

## 4. Clarification D against the code (question 4)

Hash: `git cat-file -p 1cb231033:docs/research/live-fill-calibration-clarification-D-2026-10-09.md` →
`238a9c67aa838289288d146868ef502927412603b28224181114df4ccfa54134`, as stated.

Every `file:line` reference in D resolves at `acd052a2d`: `lfc_cli.py` 122-127, 154, 176, 198-207 (205 is the
comparison), 234-237, 497, 530, 996-997; `lfc_constants.py:65`; `re1_resilience.py` 108, 110, 112, 124, 138;
`re1_attended.py` 650, 659, 679, 696; `lfc_pilot.py:18`.

| Section | Matches code? | Notes |
| --- | --- | --- |
| D1 attestation flag, gap rule, equality passes, verify re-check, refused attestation writes nothing | Yes | `_utc_timestamp` also accepts `-00:00` (immaterial). Cadence paragraph: see (a) |
| D2 unterminated last line only | Yes | Same rule in `_post_order_ids` (786-796) and `session0_0c_last_journal_utc` (186-193) |
| D3 "0d and 0g journal" | Yes | Delta-2 §1 |
| D4 "recorded no leg intent" | Yes | `lfc_cli.py:154` |
| D5 snapshot scope | **Mostly** | "the next start refuses `wallet_activity_outside_pilot`" is conditional: `start_refusals` compares current positions outside our tokens with the **latest t40** (`lfc_ledger.py:518-524`), and the runbook retakes t40 before every sub-run (90-min age). A 0b fill followed by a retaken t40 is **not** refused and the code's S0-6 comparison does not see it. R-D1 |
| D6 fresh endpoint every 3 s, ≤ 8 reads, 503 → `ERR`, topology | Yes to the code | D omits that it changes three signed S0 §5 values (cached `open-orders` → `fresh=1`; 2 s → 3 s; 60 s → 21 s cutoff); the runbook §11.17 says so, D does not. Cap claim: see (b). R-D2 |
| D7 class rule, codes, order guard, mid-session rule | Yes | Two precisions: siblings are judged on **Gamma fields only** (`sibling_fee_refusal`, 237-248: `feesEnabled` false, no `feeType`/`feeSchedule`, base and builder fields zero-ish; no CLOB `fd`/`base_fee` check), and D7 does not say what it widens relative to signed C8 or the residual bound. R-D3 |
| D8 neg-risk known limit | **Not code** | No `neg_risk` check exists in `session0_candidate` (the only `neg_risk` read is `_rule_key`, 131, for change detection). "The session-0 picks are plain binary markets" is an expectation, not a rule. R-D4 |
| D9 owner approvals | n/a | Owner statements, consistent with the runbook |
| D10 deadline | Yes | Section 3 |

### (a) Journal frequency and the N-10 gap rule

The workstation is right and delta-2 §4 was wrong. `Session.run` writes no row per cycle: the loop is
`heartbeat_loop.tick(); control(); …; sleep(≤ 1 s)` (`re1_attended.py:646-696`) and its periodic rows are
`market_snapshot` (659) and `minute` (679) once per ≥ 60 s (650). The heartbeat thread journals `heartbeat_request`
and `heartbeat_response` on every send (`re1_resilience.py:110,112`); after an acknowledged send the next is due 2 s
later (124), after a failed one 1 s later (108, left in place on failure), and the thread wakes every 0.1 s (138). In
0c the sends run until the kill, so L0 (last complete row) is at most ≈ 2 s plus one send's latency before the kill.
D1's list of "other rows" is incomplete, the venue's SDK hooks also journal `sdk_request`/`sdk_response` for every
REST call including the ≤ 10 s order re-reads (`re1_transport.py:335-359`), but those only make rows denser; the
heartbeat bound is the tightest and D1's conclusion stands.

Consequence for the gap rule: `T − L0 ≥` true kill-to-zero, over-estimating by ≤ ≈ 2-3 s. With `S ≥ T − L0` and
`S ≤ 20`, the effective pass threshold on the true time is ≈ 17-18 s: strictly conservative, as D1 says. `reconcile`
does not append to the session `journal.jsonl` (it writes ledger rows and `session_end.json`, `lfc_cli.py:308,332-340`),
so L0 is not displaced after the kill. `Measure-TimeToZero` takes `$at` after the read returns (runbook 72), matching
D6.1's definition of T. Same host clock for both.

### (b) The shared 30-per-60 s cap

The capture host's `WeatherManualOrderJournal` runs `order_journal record` every 5 minutes (trigger `PT5M` from
midnight, `register_manual_order_journal.ps1:75,89`, so at :00/:05/…). Per run it calls the reader for
`rewards` today (every run) and the prior day (hourly, `PRIOR_REWARDS_RECHECK = 3600`), `trades`, and `summary`
(`order_journal.py:79-93`). Reader upstream cost (`wallet_reader.py`): `rewards(day)` = `/rewards/user` pages (≥ 1) +
`/total` + `/percentages` (cached on the second day) ≈ 3 + 2; `trades` = `/data/trades` + `/trades` + `/activity` = 3;
`summary` = `/balance-allowance` + `/data/orders` + `/positions` (+ `/activity` for the campaign book) ≈ 3-4 with no
holdings, plus Gamma metadata and 2 reads (`/book`, `/rewards/markets`) per held position under the 24-GET composite
plan. **With the owner holding no positions (D9.1): ≈ 9-13 upstream GETs per run, bursty within a few seconds.**
`8 + 13 = 21 < 30`, so the 3 s fresh loop is safe under the cap **even if it coincides with a journal run**, provided
no other reader calls (manual `Get-OpenOrderCount`, a `baseline`) fall in the same 60 s. With held positions the
journal alone can reach the 24-GET composite cap plus 5-8 and exhaust the budget, after which the loop prints `ERR`
for up to 60 s; S0-2 would then be unmeasurable and 0c repeated (fail rule), not mis-measured (`ERR` never counts as
0). D6.2 should state the condition and the runbook should start the kill/drop ≥ 60 s after a 5-minute boundary and
≥ 60 s after the last manual helper call. Also note the fresh read's URL (`/data/orders`) equals the journal's
`open_orders` URL, so a fresh read refreshes the cache the journal may then hit (fewer, not more, upstream calls).

### (c) Does any D clause weaken a signed hard limit?

- D1, D2, D10: stricter. D3, D4: wording.
- D5/D9.2: drops the after-settlement snapshot when nothing filled. PR §5 Baselines (`1cb231033`, lines 194-203)
  names only the T − 24 h and T − 40 min snapshots; no signed text requires an after-settlement one, so nothing
  signed is weakened; it is an owner decision and is labelled as such. The "next start refuses" sentence overstates
  the code (R-D1); S0-6 detection, not a money limit.
- D6: changes three signed S0 §5 procedure values (above). S0-2's 20 s limit is unchanged and the 3 s cadence can
  only lengthen the measurement. Not a weakening, but D must name what it changes (R-D2).
- D7: replaces signed C8. Under C8 as signed (`fee_rate_bps == 0` on every token) every weather band reads
  `base_fee` 1000 and would have been refused, so D7 **admits markets C8 refused**, on venue metadata
  (`feeSchedule.takerOnly`, `fd.to`) plus EF §10o. That is not a weakening of a hard money limit (L, sizes, caps,
  GTD unchanged; residual ≤ ≈ 4.2 pUSD of share value if the metadata lied, cash outlay still ≤ L) but it is the one
  clause that widens what may be traded, and D7 presents it only as "Replaces C8". It must be stated as a widening
  with the residual bound (R-D3).
- D8: no limit; but it asserts a property the code does not enforce (R-D4).

## 5. Required before signing D (text only; re-hash after)

- **R-D1 (D5):** replace "If either fills, S0-6 fails and the next start refuses `wallet_activity_outside_pilot`"
  with "If either fills, S0-6 fails. The code's start refusal compares against the **latest** t40 baseline
  (`lfc_ledger.py:518-524`); because t40 is retaken before every sub-run, the owner judges a 0b fill against the t40
  taken before 0b (or the t24 record), not by relying on the refusal."
- **R-D2 (D6):** add "This changes S0 §5's helper: the cached `open-orders` route becomes `GET /open-orders?fresh=1`,
  the 2 s poll becomes 3 s, and the 60 s cutoff becomes 21 s; S0-2's 20 s limit is unchanged and 3 s can only
  lengthen the measurement." In D6.2 replace "so it stays within the cap" with "so it stays within the cap while the
  owner holds no positions (a journal run then costs ≈ 9-13 upstream reads) and no other reader call falls in the
  same 60 s; start the kill or drop ≥ 60 s after a 5-minute boundary."
- **R-D3 (D7):** add "C8 as signed would have refused every weather band (`base_fee` 1000); D7 admits them on the
  venue's own schedule metadata and EF §10o. If that metadata were wrong, the taker schedule on our fills is
  `0.05(1−p)` of the cost, deducted from shares, ≤ ≈ 4.2 pUSD campaign-wide; L, sizes, caps and GTD are unchanged."
  And "every open market of its event must be fee-free **on its Gamma fields** (`feesEnabled` false, no
  `feeType`/`feeSchedule`, base and builder fields zero); siblings are not checked against CLOB."
- **R-D4 (D8):** "The session-0 picks are **expected to be** plain binary markets; the code does not check
  `neg_risk` for session 0. The owner confirms `neg_risk: false` for the selected row in `selection.json` before
  `go`." (Or add the one-line check to `session0_candidate`, which would move the pinned tip.)

## 6. Findings (new, by severity)

No HIGH. No MED.

**N-11 LOW (code, recommended) - `FeeEvidenceBooks.fee_evidence` swallows control-checkpoint `HoldEnd`s.**
`lfc_fees.py:278-290` wraps its Gamma and CLOB reads in `except Exception`, and those reads call `checkpoint()`
(`= self.control`) before and after the HTTP request (`mm_stage2_selection.py:193,207`). `HoldEnd` is a
`RuntimeError` (`mm_stage2_hold.py:83`), so a `fixed_end`, `fill`, `geoblock`, `heartbeat_stale`,
`order_no_longer_resting` or `venue_deadman_*` raised inside those ~0.3 s per minute is converted to
`error: 'HoldEnd'` and the session then ends `fee_fields_unreadable` from `minute_extra` (or `market_rules`). Every
pre-existing read in `Re1PublicBooks.snapshot` lets the `HoldEnd` through (try/finally, `re1_rehearsal.py:27-34`),
so this is new. Effect: the end is mislabelled and a session-0 run can **spuriously fail** its mechanical gate
(0a needs `fixed_end`; 0d/0g need their codes); it cannot produce a false pass, delay the cleanup by more than the
remaining snapshot work, or move L (any `halt`/`fill` ledger row is written before the raise). Probability per
minute-boundary event ≈ fee-read duration / 60 s, well under 1 % per run. Fix: `except HoldEnd: raise` ahead of
`except Exception` (or pass `checkpoint=lambda: None` to the two fee reads). Not required before session 0; worth
landing before session 1 with the next tip.

**N-12 LOW (code, recommended) - Duplicate `refusal=` keyword on the selection-phase journal row.**
`lfc_pilot.py:524-525` passes `refusal=self.opening_fee_code, **self.opening_fee`; when a code was returned,
`maker_fee_refusal` puts `'refusal'` into the record too (`lfc_fees.py:207,209`), so the call raises `TypeError`
instead of `HoldEnd(code)`. Unreachable in production: the identical classification with the identical
`require_fee_free` already ran on the same row in `_selector` and would have raised there. If reached, the
`TypeError` is caught by `run()`'s `except BaseException` → reason `exception`, cleanup runs, nothing was posted
(`before_first_post` precedes the first submit). Fix as at submit: `**{k: v for k, v in self.opening_fee.items() if
k != 'refusal'}`; add the selection-phase refusal to the tests (today they only mutate the venue's snapshot).

**N-13 LOW (text) - D5's `wallet_activity_outside_pilot` sentence** (R-D1).
**N-14 LOW (text) - D6 omits the signed S0 §5 values it changes and the cap condition** (R-D2, section 4b).
**N-15 LOW (text) - D7 does not state the C8 widening, the residual bound, or that siblings are Gamma-only** (R-D3).
**N-16 LOW (text) - D8 states as fact what the code does not enforce** (R-D4).
**N-17 INFO - D1's row list omits the `sdk_request`/`sdk_response` rows**; the heartbeat bound still governs.
**N-18 INFO - Session-0 feasibility, not safety:** `sibling_fee_refusal` requires `feesEnabled` to be a bool on
every open market of the event; if Gamma omits the field on fee-free markets, every session-0 candidate refuses
`fee_fields_unreadable`. Fail-closed direction; the owner will see it at the first preflight.

## 7. Signed hashes (question 5)

`git cat-file -p <commit>:<path>` to a file, SHA-256 of the bytes (LF as stored):

| File | Commit | SHA-256 | Match | At `1cb231033` |
| --- | --- | --- | --- | --- |
| `live-fill-calibration-preregistration-2026-10-09.md` | `82936d68` | `122d08e4ede30706284fce80d1479536e554526945d005d71f86e7ab49c20975` | Yes | identical |
| `live-fill-calibration-panel-clarifications-2026-10-09.md` | `82936d68` | `29d37a47709d4f207ff457a1e48fd6e1d3b8c0c091175bc925e7d3be33c52284` | Yes | identical |
| `live-fill-calibration-session0-spec-2026-10-09.md` | `82936d68` | `9c331b1f63f8a11afa8b83a314a32b165aa70e45d0eeafe6e5195aafefa7c5f2` | Yes | identical |
| `maker-pnl-adverse-selection-clarification-2-2026-10-09.md` | `fb740523` | `7f1e9c454db9984ef60bc878ce457057d62603d5eab33a9c982f34537c892b9e` | Yes | not present on this branch (lives on `codex/maker-pnl-adverse-selection-20261001`), so it cannot have been altered there |
| `live-fill-calibration-clarification-C-2026-10-09.md` | `ab4968afe` | `4d6ae37a4f2cb6a098ef709dd0148b9babba6e465c3d202dff2ab4242d369054` | Yes | identical |
| `live-fill-calibration-clarification-D-2026-10-09.md` | `1cb231033` | `238a9c67aa838289288d146868ef502927412603b28224181114df4ccfa54134` | Yes (as stated) | - |

The C signature record at `1cb231033` cites `ab4968afe` and the same hash. The code branch at `acd052a2d` carries no
`docs/research` LFC file (its docs change is `docs/operations/wallet-reader.md` only).

## 8. Runbook notes carried forward (not code)

- Before the 0c kill and the 0d/0g drop: no manual `Get-OpenOrderCount` in the preceding 60 s; start the window
  ≥ 60 s after a 5-minute boundary (the capture host's journal burst), section 4b.
- A `fee_fields_unreadable` end on a run whose journal shows the expected terminal event in the same second is N-11,
  not a venue fact; re-run the sub-run.
- Session-0 pass gate for 0a/0d/0g unchanged; the owner should still read `evidence_complete: false` on a REST-path
  0d/0g pass as expected (delta-1 N-4).
- Pinned worktree for the sub-runs, `session0-attest` and session 1: `acd052a2d`. D is signed only after R-D1..R-D4
  and a re-hash; the signed hash is the one at signature time.
