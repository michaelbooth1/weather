# RE-1 open positions review — 2026-09-25

- **Owns:** the hold/sell/resting-sell analysis of the two Sep-25 RE-1 lots, the proposed standing inventory policy and bleed
  limit for RE-1 fills, and the wallet-reader recommendation.
- **Read when:** an RE-1 fill leaves inventory, or before building the wallet reader (handoff 100a).
- **Do not use for:** current positions (the owner's wallet and [STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)).

Auditor: Fable read-only subagent (four public GETs, no authenticated calls). The production agent re-read both public books at
15:07Z before the recommendation went to the owner. The owner placed both orders; no agent touched the account.

## Evidence (15:01Z books, 14:53Z KMIA / 13:51Z KORD METARs, 14:59Z snapshots)

| | Miami 90-91°F Sep 25 (75 YES @0.35, cost 26.25) | Chicago 68-69°F Sep 25 (75 YES @0.43, cost 32.25) |
| --- | --- | --- |
| Running high | 81°F at 10:53 ET, BKN017 after an overcast morning | 63°F at 08:51 CDT, OVC120 |
| Forecast highs | NWS hourly 86; ensemble 86.7 (85.6-87.5); Open-Meteo 86.5 | NWS hourly 67; ensemble 65.8 (64.4-70.8); Open-Meteo 67 |
| Our served p(band) | 0.0055 (not trusted alone: the model does not beat the market) | 0.548 (same caveat) |
| Book | 15:01Z bid 0.23 x52 / ask 0.27; **15:07Z bid 0.18 x161 / ask 0.22** | bid 0.31 x10, then 5/5/16 down to 0.25; ask 0.36 x5, then 0.42 |
| Reward terms | `rewardsMinSize` 100, max spread 4.5 c, rate 53/day | `rewardsMinSize` 100, max spread 4.5 c, rate 73/day |
| Recommendation | Sell into the bid (limit 0.18 after the move) | Resting maker sell 75 @0.37 GTC; hold if unfilled |
| Owner action (~11:10 ET) | **Market-sold** (proceeds to reconcile) | **Limit sell 75 @0.37 placed** |

Sweeping the thin Chicago bid would have realized ~17 against a ~25.5 mid. Neither 75-share lot can earn rewards (minimum 100).
Maker fee is zero; the taker fee is `0.05·p(1−p)` per share (EF §10o).

## Proposed standing inventory policy (owner may amend)

Re-check held lots at ~10:30-11:00 local of the target day, once daytime METARs and the NWS hourly grid are in.

1. **Sell into the bid** when the band is at least two bands from the forecast-consensus mode, the 11:00 running high is at
   least 7°F short of the band (or already above it), and the bid within 1 c covers about two-thirds of the lot.
2. **Resting maker sell** when the band is contested (mid 0.15-0.70), the ask side is thinner than the lot, and taker buys at or
   above mid+2 c printed in the last two hours: one tick above a thin best ask, else join it. Read `rewardsMinSize` each time;
   at or above it, the sell also earns rewards.
3. **Hold** otherwise; settlement is recorded either way.
4. **EF §10n:** a resting sell needs no cash and never crowds a buy elsewhere, but any open order stops an RE-1 session
   (`foreign_open_order`): cancel resting sells before a session starts.
5. **Bleed limit:** no new RE-1 sessions when cash < 60 pUSD or campaign P&L (realized plus marked) < −40; hard stop −75.

## Wallet reader

Worth building as a small keyless script on the workstation first; an MCP wrapper can come later. Public GETs only: data-api
positions, trades and activity by the public address; gamma metadata and reward terms; public CLOB books; the pUSD balance via a
public Polygon RPC. Open orders and reward earnings need the L2 key, which also signs orders, so they stay in the app. Risks:
credential creep (no `.env`, no `py-clob-client`, allowlisted hosts, GET only), rate limits shared with a live session, positions
lag, output treated as instruction. Handoff: [100a](../workstation-handoff-2026-09-100a-wallet-public-reader.md).

## Unverified

The owner's exact Miami proceeds and cash; whether `rewardsMinSize` was 100 during the RE-1 sessions on these bands; WRH
rounding at the Chicago 67/68 boundary; fill-probability estimates (judgment from ~2 h of prints).
