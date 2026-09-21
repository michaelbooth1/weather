# What the market knows: completion of mission 2026-09-79a

**Station guidance is the strongest measured lead; market parity is not proved.**
This completes the available descriptive checks and supersedes the earlier
[no-data checkpoint](missing-information-results-2026-09-79a.md).
[Full handback](../roadmap/agent-report-2026-09-79a-workstation-what-does-the-market-know-completion.md)
and [all aggregate estimates, support, intervals, power and MDE](missing-information-summary-2026-09-79a.json).

The verified export admits **503 market-days / 89,354 snapshots**, separately
239 days (20 date clusters, 12 markets) before August 23 and 264 days (22 dates,
12 markets) from August 23. All intervals use 2,000 crossed date × market draws;
these are descriptive results, with no alpha allocation or candidate fitted.

| Candidate | Verdict | Measured reason |
| --- | --- | --- |
| A. Settlement instrument / precision | **Not supported as the main explanation; cadence remains unresolved** | Final station maximum differs from settlement on 2/239 and 2/264 days: upper 95% bounds 3.35% and 3.41%, below the frozen 10% criterion. No model mass below its own captured floor was observed. |
| B. Station guidance held but unused | **Supported as a research lead; parity unpowered** | Morning NBM+floor minus served Brier is −0.01470 [−0.02603, −0.00334] and −0.01476 [−0.02751, −0.00195]. But its market ratios are 1.217 [1.075, 1.389] and 1.148 [1.005, 1.322], missing the frozen ≤1.10 rule. Support is 149 days/19 dates/9 markets and 166/22/9; MDE for Brier difference 0.0161/0.0181, power at 0.01 only 39.7%/35.0%. |
| C. Weather regimes / bust days | **Unpowered** | Every observed tag has less than 27% power at OR=2; MRMS has no usable tag data. Guidance-bust ORs 0.318 [0.032, 1.243] and 0.846 [0.160, 3.022] do not establish a regime mechanism. |
| D. Training history / population | **Not identified by this design** | Morning served/market ratios 1.482 [1.287, 1.749] and 1.440 [1.247, 1.654] meet the frozen point-estimate pre-day rule, but cannot separate guidance from training history. MDEs 0.325/0.285; power at a 0.30 ratio effect 72.4%/84.8%. |
| E. Trader identity | **Untested** | No trader-identity endpoint was prespecified; a numerical power claim would be invented. |
| F. Latency | **Unpowered as a cause of the forecast gap** | Large captured quote moves precede the next snapshot by a mean 4.44 [3.92, 5.32] and 4.20 [3.81, 4.57] minutes. SPECI responses remain underpowered; all 89,271 relevant payload rows lack a complete provider-time/first-seen pair. |

The frozen “intraday dominant” rule does not fire: only 54.7% and 50.1% of
signed excess occurs at/after noon, below 60%. Ratios nevertheless rise in
the afternoon, so the clock study was performed. IEM observation times are
not publication receipts; neither the event study nor clock histograms
establish a private feed or an unclosable gap.

A real captured feature row reaches the canonical selection/imputation path:
the checked-in Atlanta artifact has 27 selected columns per cutoff and no
direct NBM/NWS-grid/HRRR columns. Removing NBM leaves its input unchanged.
**Historical active binding remains unproved**, and aggregate forecast features
can still carry other guidance indirectly. No stored permutation importance
was present. The trace is structural evidence, not a replay of final served output.

**Single next step to pre-register:** a morning, floor-preserving NBM guidance
candidate, evaluated through the full served pipeline on newly held-out dates,
with point-in-time input/release binding and power assessed on that exact
candidate before any alpha decision. This report only proposes that design.
No model, serving configuration, live operation or production state was changed.
