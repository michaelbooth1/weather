# Workstation current-serving disagreement map — 2026-08-01

## Verdict

The current model has **material live disagreements** in the complete recent
window. This is not a clean or diffuse-gap result: current-serving replay
Brier is `0.052596844` against market Brier `0.036846918`, a
`+0.015749925` model-minus-market gap over 211,915 band rows. The
daily-first comparison gives the same answer: `0.052558312` versus
`0.036734065`, a `+0.015824247` gap.

The stale queue and the current map must be separated:

- At their exact historical coordinates, **2/9 queue rows are dead** under
  the current model and **7/9 still clear the original 30-point trigger**.
  The two accepted Seattle 2026-06-07 lanes are the dead rows; each collapsed
  from about 72.5 points to 0.24 points.
- Only **1/9 existing queue rows** also clears the current-window contribution
  and recurrence cut: San Francisco 68–69°F. The other eight should be
  retired as standalone repair lanes, even though six of them still reproduce
  a large gap on a partial-label June 23 snapshot.
- Five current bands justify future map-scoped repair lanes: Los Angeles
  78–79°F, Dallas 98–99°F, Houston 94–95°F, Austin 98–99°F, and San
  Francisco 68–69°F. Together they carry **18.64%** of the daily-normalized
  positive resolution-gap contribution.

This report builds and prioritizes the map only. It does **not** build, tune,
score, or authorize a candidate.

## Source, run root, and declared window

| Field | Value |
| :--- | :--- |
| Source | exact `origin/master` `25b6172b495d2a5f816a90c8becd271b2ea0cb89` |
| Topic branch | `codex/workstation-disagreement-map-2026-08-03a` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\disagreement-map-2026-08-03a` |
| Current settled target window | **2026-07-22 through 2026-07-30**, inclusive |
| Markets | 12 on every date; 108 market-days |
| Settlement quality | 108/108 `complete`; ledger authority; zero skipped folders |
| Pinned corpus | `promotion_corpus_v0.1`, hash `fc878cbc5290d45e93b36f9efdf796196708d125788da9458d3c1c8c2ef5fb72` |
| Pinned input size | 19,265 snapshots; 211,915 band rows |
| Serving path | `v0.5.10 HGBC feature-based ML model` |
| Replay integrity | zero corpus warnings; 19,265/19,265 snapshots scored |

The freshness gate read only these 108 exact market-day folders from the
workstation mirror. July 21 was excluded because Miami was partial; July 22
is the first date on which all 12 markets are complete. The mirror did not
yet contain a complete settled date after July 30, so waiting for its global
horizon would not have improved this experiment's exact inputs.

`rows[-1]` boundary: **PASS**. The pinned corpus was generated at
`2026-08-01T19:08:25Z`; every current-serving probability and every result row
was regenerated together after the 2026-07-31 boundary from the same
`25b6172b` code and pinned corpus. No pre-boundary result row was spliced into
the map. Historical audit probabilities are retained only in the explicitly
labelled before columns below.

The six-folder queue-coordinate corpus was separately pinned at hash
`8f76eea5f93ea8992284884d71512c25305dfaefe2a9db82e266172e28543f3c`
with 616 snapshots and 6,787 band rows. Its five June 23 folders have
`quality_grade=partial` and are not promotion-countable; they are used only
to resolve the historical coordinates diagnostically. Seattle June 7 is
complete.

## Leakage posture

Feature/outcome leakage: **PASS for descriptive replay**. Evaluation
independence: **development-only, not unseen-day or promotion evidence**.

- Each probability was reconstructed through the current serving path from
  the sources pinned in that checkpoint's replay record. Market probability
  and settlement outcome are scoring fields, not serving-model features.
- No fitting, parameter selection, candidate branch, outcome-conditioned
  rule, or rerun-after-score occurred.
- This target window is not operationally untouched. July 22–30 has already
  appeared in repository engineering evidence, including the July 17–30
  synthetic rehearsal window; July 22–29 also appears in hash/release
  diagnostics. The replay also uses current code that postdates some target
  days. It is therefore a retrospective current-serving map, not a forward
  holdout claim.
- I found no basis to claim that July 22–30 was part of the older Items
  147/232 fitted model corpus, but that narrower fact does not upgrade the
  evidence because the same dates have been inspected elsewhere.

Replay fidelity correctly classifies all 19,265 snapshots as
changed-model-version comparisons (`same_identity_n=0`). That is expected for
reconstructing today's serving model; recorded probabilities are not treated
as an incumbent canary.

## Existing queue: exact before/after arithmetic

Signed gap is `(model probability - market probability) * 100`. `LIVE` below
means at least one historical sample still has absolute gap at least 30 points
under the current model. It does not by itself mean the lane deserves current
repair work.

| Queue row | Before → current-serving arithmetic | Historical-coordinate verdict | Current-window band evidence | Recommendation |
| :--- | :--- | :---: | :--- | :---: |
| Seattle 64–65°F, market higher | `(0.274247 - 0.999500) * 100 = -72.525300` → `(0.997139 - 0.999500) * 100 = -0.236110` | **DEAD** | 0.0033% contribution; 0 material market-right days | **RETIRE** (accepted) |
| Seattle 66–67°F, model higher | `(0.724665 - 0.000500) * 100 = +72.416500` → `(0.002860 - 0.000500) * 100 = +0.235981` | **DEAD** | 0.0043%; 0 material days | **RETIRE** (accepted) |
| NYC 70–71°F, market higher | `(0.050806 - 0.874000) * 100 = -82.319400` → `(0.067621 - 0.874000) * 100 = -80.637853`<br>`(0.116558 - 0.727500) * 100 = -61.094200` → `(0.120015 - 0.727500) * 100 = -60.748507`<br>`(0.116558 - 0.774000) * 100 = -65.744200` → `(0.120015 - 0.774000) * 100 = -65.398507` | **LIVE**, June 23 partial | 0.00015%; 0 material days | **RETIRE** |
| Seattle 84–85°F, model higher | `(0.688404 - 0.085000) * 100 = +60.340400` → `(0.688404 - 0.085000) * 100 = +60.340391`<br>`(0.762521 - 0.110000) * 100 = +65.252100` → `(0.762521 - 0.110000) * 100 = +65.252091`<br>`(0.770767 - 0.110000) * 100 = +66.076700` → `(0.770767 - 0.110000) * 100 = +66.076710` | **LIVE**, June 23 partial | 0.6451%; material on 2/9 window days | **RETIRE** |
| Chicago 72–73°F, model higher | `(0.869340 - 0.001500) * 100 = +86.784000` → `(0.834900 - 0.001500) * 100 = +83.340031` | **LIVE**, June 23 partial | 0.0453%; material on 1/9 days; net band score favours model | **RETIRE** |
| San Francisco 68–69°F, market higher | `(0.342045 - 0.895000) * 100 = -55.295500` → `(0.342045 - 0.895000) * 100 = -55.295533`<br>`(0.402020 - 0.993500) * 100 = -59.148000` → `(0.403081 - 0.993500) * 100 = -59.041882`<br>`(0.439849 - 0.993500) * 100 = -55.365100` → `(0.440080 - 0.993500) * 100 = -55.342028` | **LIVE**, June 23 partial | **3.0773%**; material on **9/9** days | **KEEP** |
| Seattle 86–87°F, model higher | `(0.548040 - 0.000500) * 100 = +54.754000` → `(0.556902 - 0.000500) * 100 = +55.640243`<br>same arithmetic at the second audited snapshot | **LIVE**, June 23 partial | 0.0142%; material on 2/9 days | **RETIRE** |
| Dallas 92–93°F, market higher | `(0.431085 - 0.940000) * 100 = -50.891500` → `(0.431189 - 0.940000) * 100 = -50.881139` | **LIVE**, June 23 partial | 0.0537%; material on 2/9 days | **RETIRE** |
| San Francisco 70–71°F, model higher | `(0.509086 - 0.006500) * 100 = +50.258600` → `(0.508876 - 0.006500) * 100 = +50.237571` | **LIVE**, June 23 partial | 1.6156%; material on 8/9 days | **RETIRE** as a standalone lane |

The old queue is therefore stale in two different ways. Two rows are literal
ghosts because their point gaps disappeared. Six more still reproduce a June
23 gap, but do not carry enough current complete-window resolution harm to
justify standalone work. San Francisco 68–69°F is the sole old row that
survives both tests. San Francisco 70–71°F remains useful adjacency context
for that investigation, but does not earn a second lane.

## Current complete-window map

For each band row I calculated
`excess = current_model_brier - market_brier`. Ranking uses only positive
excess (cases where the market is closer), weighted by the reciprocal of that
market-day's row count so capture-heavy days cannot dominate. A material
disagreement is at least 10 points. Raw gap size is not the rank key.

Across the window:

| Measure | Result |
| :--- | ---: |
| Market closer rows | 82,961 / 211,915 |
| Model closer rows | 128,954 / 211,915 |
| Market-right rows with gap ≥10 points | 28,311 |
| Market-right rows with gap ≥20 points | 15,279 |
| Market-right rows with gap ≥30 points | 9,032 |
| Net model-minus-market Brier sum | +3,337.645421 |

The model is closer more often, but the market's wins are much larger; that
asymmetry produces the positive aggregate Brier gap.

### Direction-specific ranking

| Rank | Market / band / direction | Daily-normalized positive contribution | Material market-right recurrence | Mean / max absolute gap |
| ---: | :--- | ---: | :---: | ---: |
| 1 | Los Angeles 78–79°F, market higher | **3.8156%** | 6/9 days | 32.20 / 90.66 pts |
| 2 | Denver 100–101°F, market higher | **3.2628%** | 2/3 observed days | 33.10 / 83.60 pts |
| 3 | Los Angeles 76–77°F, market higher | **3.2371%** | 2/9 days | 15.96 / 95.21 pts |
| 4 | Dallas 98–99°F, market higher | **3.0344%** | 6/9 days | 17.01 / 96.97 pts |
| 5 | San Francisco 68–69°F, market higher | **3.0243%** | 4/9 days | 16.70 / 80.81 pts |
| 6 | Houston 94–95°F, market higher | 2.8119% | 4/9 days | 19.75 / 74.86 pts |
| 7 | Austin 98–99°F, market higher | 2.5118% | 3/9 days | 23.62 / 78.50 pts |
| 8 | Miami 90–91°F, model higher | 2.2774% | 8/9 days | 26.06 / 85.20 pts |
| 9 | Los Angeles 80–81°F, market higher | 2.2133% | 1/9 days | 32.28 / 89.86 pts |
| 10 | Seattle 78–79°F, market higher | 1.9309% | 2/8 observed days | 10.09 / 59.73 pts |

Direction can flip across dates at the same band, so repair prioritization
combines both directions. That makes recurrence visible instead of splitting
one unstable band into two smaller rows.

### Repair-lane recommendation

The handback prioritization cut is explicit: keep a band only if it carries
at least **3%** of daily-normalized positive contribution and has a material,
market-right disagreement on at least **8 of the 9** window days. This is a
queue-bounding rule, not a preregistered statistical gate and not a candidate
score.

| Priority | Band | Contribution | Material recurrence | Market closer / rows | Mean / max absolute gap | Recommendation |
| ---: | :--- | ---: | :---: | ---: | ---: | :---: |
| 1 | Los Angeles 78–79°F | **5.5914%** | **9/9** | 1,071 / 1,535 | 29.88 / 90.66 pts | **KEEP** |
| 2 | Dallas 98–99°F | **3.4659%** | **9/9** | 1,184 / 1,587 | 16.74 / 96.97 pts | **KEEP** |
| 3 | Houston 94–95°F | **3.3600%** | **8/9** | 1,113 / 1,595 | 18.31 / 74.86 pts | **KEEP** |
| 4 | Austin 98–99°F | **3.1468%** | **9/9** | 1,038 / 1,600 | 20.13 / 78.50 pts | **KEEP** |
| 5 | San Francisco 68–69°F | **3.0773%** | **9/9** | 775 / 1,577 | 16.21 / 80.81 pts | **KEEP** |

Denver 100–101°F is the clearest example of why recurrence is binding: it is
second in the direction-specific table and has a 3.2628% combined band
contribution, but it appears on only three dates and is materially
market-right on two. It stays off the repair queue until a later map confirms
recurrence. Every other band is likewise retired from the active repair queue
for now; regeneration, rather than an append-only log, can promote one later.

The five retained bands do not authorize five candidates. They are the
ordered scopes for a later mechanism review. A future candidate requires a
separate instruction and a frozen, leakage-safe experiment.

## Machine-readable evidence and guardrails

All generated evidence is under the one declared run root, outside the
mirror. Principal files:

- `disagreement-map.json` — full queue arithmetic, current directional and
  band rankings, recommendation rule, and retained lanes; SHA-256
  `6ffc6b6bcd12688e32c7a15bcbb3b3d6eb8f2f12d0b1a4cb91eb7c04c8a142eb`.
- `ranked-live-disagreements.csv` — direction-specific ranking; SHA-256
  `2e11093bc4292de4f96251aad7e5be3ed74693f3ba52cca94303fe063975b1b8`.
- `aggregate-rankings.json` — band, market-direction, market, and date-market
  aggregations; SHA-256
  `f8dbee385bfeb88fe5999c0b146c95df682e076a39a03be1f7a4d41e46e2e7dd`.
- `queue-before-after.csv` — all 16 historical sample calculations; SHA-256
  `e5f99825fc3baaa5479a39d4f24c44d237fac02d0b1c743eb83056909a62acae`.
- `current-window-corpus.json`, `current-window-replay.json`, and
  `current-window-replay-rows.csv` — pinned complete-window inputs and
  current-serving replay.
- `queue-coordinate-corpus.json`, `queue-current-replay.json`, and
  `queue-current-replay-rows.csv` — diagnostic historical-coordinate replay.

`data/` and the mirror remained read-only. No candidate, tuning, production
artifact, PR, merge, master push, promotion, pointer, serving, scheduler,
capture, mirror, or ACL change occurred. No sync credential was read or
exposed.
