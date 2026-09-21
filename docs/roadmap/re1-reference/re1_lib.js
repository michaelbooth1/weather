// RE-1 shared helpers. Public, credential-free reads only. No orders, no account access.
// Scoring is a line-for-line port of src/weather/market/reward_share_estimate.py
// (order_score, q_min, share_of, side_score, hypothetical_quote).
const crypto = require('crypto');
const CLOB = 'https://clob.polymarket.com';
const SNAPSHOT = 'C:/Users/micha/Desktop/github/weather/data/backtest/exchange_economics_snapshot.json';
const LOCATION_ORDER = ['los-angeles', 'seattle', 'san-francisco', 'denver'];
const RULE = {
  max_min_size: 20, min_rate: 40, min_max_spread_cents: 3, max_book_spread: 0.06,
  mid_low: 0.20, mid_high: 0.80, distance_cents: 1.5, window_low_cents: 1.0, window_high_cents: 3.0,
  size: 20, minutes: 360, min_predicted_pusd: 2.0,
};

async function getJson(url) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 15000);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url);
    return await r.json();
  } finally { clearTimeout(t); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function orderScore(size, distanceCents, maxSpreadCents, minSize) {
  if (size == null || distanceCents == null || !(maxSpreadCents > 0)) return 0;
  if (size <= 0 || size < minSize) return 0;
  const d = Math.abs(distanceCents);
  if (d >= maxSpreadCents) return 0;
  return size * ((maxSpreadCents - d) / maxSpreadCents) ** 2;
}
function qMin(one, two, mid) {
  const both = Math.min(one, two);
  return (mid >= 0.10 && mid <= 0.90) ? Math.max(both, Math.max(one, two) / 3.0) : both;
}
const shareOf = (own, comp) => (own <= 0 ? 0 : own / (own + Math.max(comp, 0)));
function levels(raw) {
  return (raw || []).map((l) => [Number(l.price), Number(l.size)])
    .filter(([p, s]) => p > 0 && p < 1 && s > 0);
}
function sideScore(lv, mid, maxSpread, minSize, ownPrice, ownSize) {
  let total = 0;
  for (const [p, s0] of lv) {
    // our own resting size is removed from the level it sits on, so we do not compete with ourselves
    const s = (ownPrice != null && Math.abs(p - ownPrice) < 1e-9) ? Math.max(0, s0 - ownSize) : s0;
    total += orderScore(s, (p - mid) * 100, maxSpread, minSize);
  }
  return total;
}
const floorTick = (v, t) => Math.round(Math.floor(v / t + 1e-9) * t * 1e9) / 1e9;
const ceilTick = (v, t) => Math.round(Math.ceil(v / t - 1e-9) * t * 1e9) / 1e9;

// YES-book view: our YES buy is a bid at yesBid; our NO buy at noPrice shows as a YES ask at 1 - noPrice.
function evaluate(book, terms, own) {
  const bids = levels(book.bids), asks = levels(book.asks);
  if (!bids.length || !asks.length) return { status: 'one_sided_book' };
  const bestBid = Math.max(...bids.map((l) => l[0])), bestAsk = Math.min(...asks.map((l) => l[0]));
  if (bestBid >= bestAsk) return { status: 'crossed_book' };
  // 2026-09-21 correction (mission 84a parity stop): the midpoint is the size-adjusted one, from levels
  // holding at least the reward minimum, as src/weather/market/reward_quote.py does and the venue documents.
  // The plain touch midpoint is kept as plain_mid for comparison only.
  const qb = bids.filter((l) => l[1] >= terms.minSize), qa = asks.filter((l) => l[1] >= terms.minSize);
  if (!qb.length || !qa.length) return { status: 'no_size_adjusted_midpoint' };
  const mid = (Math.max(...qb.map((l) => l[0])) + Math.min(...qa.map((l) => l[0]))) / 2;
  const plainMid = (bestBid + bestAsk) / 2;
  const yesBid = own ? own.yesBid : null, yesAsk = own ? own.yesAsk : null, size = own ? own.size : 0;
  // Our size is removed from a level only when our order really rests there (own.resting). At selection
  // time nothing of ours is in the book, so the full displayed depth competes with us.
  const rest = !!(own && own.resting);
  const c1 = sideScore(bids, mid, terms.maxSpread, terms.minSize, rest ? yesBid : null, size);
  const c2 = sideScore(asks, mid, terms.maxSpread, terms.minSize, rest ? yesAsk : null, size);
  const out = { status: 'ok', mid, plain_mid: plainMid, bestBid, bestAsk, spread: bestAsk - bestBid,
    competing_single: qMin(c1, c2, mid), competing_many: (c1 + c2) / 2 };
  if (own) {
    const d1 = (mid - yesBid) * 100, d2 = (yesAsk - mid) * 100;
    const q = qMin(orderScore(size, d1, terms.maxSpread, terms.minSize), orderScore(size, d2, terms.maxSpread, terms.minSize), mid);
    const at = (lv, p) => (lv.find(([lp]) => Math.abs(lp - p) < 1e-9) || [0, 0])[1];
    Object.assign(out, { bid_distance_cents: d1, ask_distance_cents: d2, own_q: q,
      share_single: shareOf(q, out.competing_single), share_many: shareOf(q, out.competing_many),
      displayed_at_our_bid: at(bids, yesBid), displayed_at_our_ask: at(asks, yesAsk) });
  }
  return out;
}
function quoteFor(mid, tick, distanceCents) {
  const yesBid = floorTick(mid - distanceCents / 100, tick);
  const yesAsk = ceilTick(mid + distanceCents / 100, tick);
  return { yesBid, yesAsk, yesBuyPrice: yesBid, noBuyPrice: Math.round((1 - yesAsk) * 1e9) / 1e9 };
}
async function rewardRecord(conditionId) {
  const x = ((await getJson(CLOB + '/rewards/markets/' + conditionId)).data || [])[0];
  if (!x) return null;
  const yes = (x.tokens || []).find((k) => k.outcome === 'Yes'), no = (x.tokens || []).find((k) => k.outcome === 'No');
  return { question: x.question, yesToken: yes && yes.token_id, noToken: no && no.token_id,
    minSize: Number(x.rewards_min_size), maxSpread: Number(x.rewards_max_spread),
    competitiveness: x.market_competitiveness,
    rate: (x.rewards_config || []).reduce((s, k) => s + Number(k.rate_per_day || 0), 0),
    assets: (x.rewards_config || []).map((k) => k.asset_address) };
}
const book = (tokenId) => getJson(CLOB + '/book?token_id=' + tokenId);
const sha256 = (text) => crypto.createHash('sha256').update(text).digest('hex');

module.exports = { SNAPSHOT, LOCATION_ORDER, RULE, sleep, evaluate, quoteFor, rewardRecord, book, sha256 };
