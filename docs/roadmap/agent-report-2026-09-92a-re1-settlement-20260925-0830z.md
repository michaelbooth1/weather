# Mission 92a — three resolutions observed September 25 at 08:30 UTC

**PARTIAL SETTLEMENT: three of four positions resolved, with 23.984635 pUSD
gross payoff against 17.538235 entry cost, or +6.446400 settlement P&L.
Miami remains unresolved with 26.250000 entry cost. Wallet redemption and
reward payment are not verified.**

This append-only follow-up to the
[campaign amendment](agent-report-2026-09-92a-re1-campaign-analysis-amendment.md)
records the owner's approved four-hour public resolution check. Publication
uses only `codex/re1-campaign-analysis-20260924`, whose clean local and freshly
fetched remote tip before this report was
`7f98359664b284e1dda91ed759146ab55a3aac8d`. The reducer remains unchanged at code
commit `c41d9393600351f5d1c94b3c072cf90e824cc1f2`.

## Position outcomes

| Owner session / attempt | Band and target date | Held side | Shares | Entry cost | Venue winner | Gross payoff | Settlement P&L |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| 1 / 1 | NYC 66–67°F, September 24 | NO | 5.570000 | 2.673600 | NO | 5.570000 | +2.896400 |
| 4 / 5 | Miami 90–91°F, September 25 | YES | 75.000000 | 26.250000 | unresolved | NA | NA |
| 7 / 8 | Atlanta 72–73°F, September 24 | NO | 18.414635 | 10.864635 | NO | 18.414635 | +7.550000 |
| 8 / 9 | Chicago 68–69°F, September 24 | NO | 10.000000 | 4.000000 | YES | 0.000000 | -4.000000 |

All four were unresolved at the preceding 04:30:26–29 UTC check. The new
responses were fetched at 08:30:36–39 UTC on September 25. Those are observation
times, not exact resolution times. NYC, Atlanta and Chicago each have the
exact manifest condition/token/outcome identity, `closed=true`, two distinct
tokens and exactly one winning token. Miami has `closed=false` and no winner.
Public response questions also match the bands and dates shown above.

The resolved subset spans three cities/markets and one target date. These are
descriptive position outcomes, with no statistical interval or causal claim.
The 26.25 unresolved cost is reported separately; it is neither a realized
loss nor a zero-value position. Total campaign P&L remains pending. The
previously reported accrued reward is excluded from these sums because it is
not verified payment. Gross payoff is the venue-resolution entitlement under
the captured held quantities, not an observed wallet transfer or redemption.

## Evidence and reproduction

Manifest SHA-256 was verified before use:
`79c5743cb3231c4fc34cb6443502aa4fe4455b36d0e419640715d3fa0beca04e`.
The unchanged script SHA-256 was also checked:
`9db3b9992f6314e32db024a0a007a61bd63a665d868bf8bef872c6d3896f4daa`.
Four credential-free GETs ran serially with the reducer's per-host throttle.
Raw public responses and generated CSV/JSON are retained in a fresh namespace.
Local paths below are relative to the analysis worktree and are not presumed
present in a clean checkout:

- Prior receipt: `scratch/re1-settlement-20260925T043026Z/settlements.json`,
  SHA-256 `fc14456a9ded9ce91ef4135d622d200be650fb91db6d53f4fc2dc00488c5e6b4`.
- New receipt: `scratch/re1-settlement-20260925T083036Z/settlements.json`,
  SHA-256 `985f0e9333389a9fe6dadc33b8ca899a6977b48cca6ff9109e8904af2b2d1972`.
- Both directories, including all eight cached public responses, are retained
  in `scratch/re1-settlement-evidence-20260925T083036Z.zip`, SHA-256
  `6c99c6bbb1ab5b251b9043d16e31bb706acbb5e6bf52ec5db2e34b3ba006fa2a`.

To reproduce the new result offline, transfer and verify that bundle and the
manifest explicitly, then run from a checkout containing the reducer:

```powershell
& $projectPython tools/re1_campaign_analysis_20260924.py `
  --positions $verifiedManifest --output $extractedNewReceiptDirectory
```

Omitting `--fetch-public` reuses the frozen cache. For a new observation, supply
a fresh output directory and `--fetch-public`; never overwrite a prior public
receipt. The runner exited successfully, and independent decimal sums of the
generated rows reproduced the resolved cost, payoff, P&L and unresolved cost.
No code changed and no heavy verification ran; report whitespace was checked.

This report is Markdown, a roll-free file category; production closure verdicts
and adoption remain with the production owner. No production access, live
campaign read, credential/account API access, trading, cancellation, redemption,
execution-code change, Windows task registration, merge or adoption occurred.
Prior reports and evidence are preserved. The four-hour heartbeat remains
active until Miami also resolves and the final report is published.
