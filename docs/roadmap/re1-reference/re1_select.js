// RE-1 selection rule (pre-registration 2026-09-20), executed mechanically. Public reads only.
// usage: node re1_select.js <event-date YYYY-MM-DD = tomorrow, market-local> [output-dir]
const fs = require('fs');
const path = require('path');
const L = require('./re1_lib.js');

(async () => {
  const eventDate = process.argv[2];
  const outDir = process.argv[3] || 'C:/tmp/re1';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(eventDate || '')) { console.error('usage: node re1_select.js <event-date> [output-dir]'); process.exit(2); }
  const snap = JSON.parse(fs.readFileSync(L.SNAPSHOT, 'utf8'));
  const universe = snap.markets.filter((m) => m.event_date === eventDate && m.liquidity_rewards && m.liquidity_rewards.current_daily_rate_usdc > 0);
  const rows = [];
  for (const m of universe) {
    const row = { condition_id: m.condition_id, location_id: m.location_id, event_date: m.event_date, tick: Number(m.order_price_min_tick_size) || 0.01, reasons: [] };
    try {
      const rec = await L.rewardRecord(m.condition_id);
      if (!rec) { row.reasons.push('no_reward_record'); rows.push(row); continue; }
      Object.assign(row, { question: rec.question, rate: rec.rate, min_size: rec.minSize, max_spread_cents: rec.maxSpread, competitiveness: rec.competitiveness, yes_token: rec.yesToken, no_token: rec.noToken, assets: rec.assets });
      if (!(rec.minSize <= L.RULE.max_min_size)) row.reasons.push('min_size>' + L.RULE.max_min_size);
      if (!(rec.rate >= L.RULE.min_rate)) row.reasons.push('rate<' + L.RULE.min_rate);
      if (!(rec.maxSpread >= L.RULE.min_max_spread_cents)) row.reasons.push('max_spread<' + L.RULE.min_max_spread_cents);
      if (!row.reasons.length) {
        const yesBook = await L.book(rec.yesToken);
        const ev = L.evaluate(yesBook, { maxSpread: rec.maxSpread, minSize: rec.minSize }, null);
        row.book_status = ev.status;
        if (ev.status !== 'ok') row.reasons.push(ev.status);
        else {
          Object.assign(row, { mid: ev.mid, best_bid: ev.bestBid, best_ask: ev.bestAsk, spread: ev.spread });
          if (ev.spread > L.RULE.max_book_spread + 1e-9) row.reasons.push('book_spread>6c');
          if (ev.mid < L.RULE.mid_low || ev.mid > L.RULE.mid_high) row.reasons.push('mid_outside_0.20-0.80');
          if (Math.abs(row.tick - 0.01) > 1e-9) row.reasons.push('tick!=0.01');
          const q = L.quoteFor(ev.mid, row.tick, L.RULE.distance_cents);
          const own = { yesBid: q.yesBid, yesAsk: q.yesAsk, size: L.RULE.size };
          const scored = L.evaluate(yesBook, { maxSpread: rec.maxSpread, minSize: rec.minSize }, own);
          Object.assign(row, { yes_buy_price: q.yesBuyPrice, no_buy_price: q.noBuyPrice,
            capital_pusd: L.RULE.size * (q.yesBuyPrice + q.noBuyPrice),
            worst_case_loss_pusd: L.RULE.size * Math.max(q.yesBuyPrice, q.noBuyPrice),
            share_single: scored.share_single, share_many: scored.share_many,
            predicted_pusd_many: rec.rate / 1440 * L.RULE.minutes * scored.share_many,
            predicted_pusd_single: rec.rate / 1440 * L.RULE.minutes * scored.share_single });
        }
      }
    } catch (e) { row.reasons.push('read_failed:' + (e && e.message ? e.message.slice(0, 60) : 'error')); }
    rows.push(row);
    await L.sleep(400);
  }
  const rank = (r) => { const i = L.LOCATION_ORDER.indexOf(r.location_id); return i < 0 ? L.LOCATION_ORDER.length : i; };
  for (const r of rows) if (!r.reasons.length && !(r.predicted_pusd_many >= L.RULE.min_predicted_pusd)) r.reasons.push('predicted<' + L.RULE.min_predicted_pusd);
  const eligible = rows.filter((r) => !r.reasons.length).sort((a, b) => b.predicted_pusd_many - a.predicted_pusd_many || rank(a) - rank(b) || a.condition_id.localeCompare(b.condition_id));
  const nearMiss = rows.filter((r) => r.reasons.length === 1 && r.reasons[0].startsWith('predicted<')).sort((a, b) => b.predicted_pusd_many - a.predicted_pusd_many);
  const report = { schema: 're1_selection.v1', generated_at_utc: new Date().toISOString(), event_date: eventDate, rule: L.RULE, location_order: L.LOCATION_ORDER,
    selected: eligible[0] || null, eligible, rejected: rows.filter((r) => r.reasons.length) };
  const body = JSON.stringify(report, null, 1);
  fs.mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, 're1_selection_' + eventDate + '_' + report.generated_at_utc.replace(/[:.]/g, '') + '.json');
  fs.writeFileSync(file, body);
  console.log('universe', universe.length, 'eligible', eligible.length, 'rejected', report.rejected.length);
  for (const r of eligible.slice(0, 8)) console.log((r === eligible[0] ? '>> ' : '   ') + r.location_id.padEnd(14), String(r.rate).padStart(4) + '/day', 'mid', r.mid.toFixed(3), 'YES buy', r.yes_buy_price.toFixed(2), 'NO buy', r.no_buy_price.toFixed(2), 'cap', r.capital_pusd.toFixed(2), 'share', r.share_many.toFixed(2) + '-' + r.share_single.toFixed(2), 'pred', r.predicted_pusd_many.toFixed(2) + '-' + r.predicted_pusd_single.toFixed(2), 'compet', r.competitiveness, '|', (r.question || '').replace('Will the highest temperature in ', ''));
  for (const r of nearMiss.slice(0, 6)) console.log(' x ' + r.location_id.padEnd(14), String(r.rate).padStart(4) + '/day', 'mid', r.mid.toFixed(3), 'share', r.share_many.toFixed(2) + '-' + r.share_single.toFixed(2), 'pred', r.predicted_pusd_many.toFixed(2) + '-' + r.predicted_pusd_single.toFixed(2), 'compet', r.competitiveness);
  console.log('file', file); console.log('sha256', L.sha256(body));
})();
