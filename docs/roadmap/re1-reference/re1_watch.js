// RE-1 session watcher. Public reads only: it never sees the account, places nothing, cancels nothing.
// Each minute: venue reward record + YES book for the chosen condition; scores OUR two resting prices with
// the desk model; accumulates the frozen prediction; prints an ALERT line when the owner must act.
// usage: node re1_watch.js <selection.json> <yes-buy-price> <no-buy-price> [minutes=360] [output-dir]
const fs = require('fs');
const path = require('path');
const L = require('./re1_lib.js');

(async () => {
  const [selFile, yesArg, noArg, minutesArg, outArg] = process.argv.slice(2);
  if (!selFile || !yesArg || !noArg) { console.error('usage: node re1_watch.js <selection.json> <yes-buy-price> <no-buy-price> [minutes] [output-dir]'); process.exit(2); }
  const sel = JSON.parse(fs.readFileSync(selFile, 'utf8')).selected;
  if (!sel) { console.error('selection file has no selected band'); process.exit(2); }
  const minutes = Number(minutesArg || L.RULE.minutes), outDir = outArg || path.dirname(selFile);
  const own = { yesBid: Number(yesArg), yesAsk: Math.round((1 - Number(noArg)) * 1e9) / 1e9, size: L.RULE.size, resting: true };
  fs.mkdirSync(outDir, { recursive: true });
  const started = new Date(), tag = started.toISOString().replace(/[:.]/g, '');
  const journal = path.join(outDir, 're1_watch_' + tag + '.jsonl');
  const endAt = started.getTime() + minutes * 60000;
  let pMany = 0, pSingle = 0, scoredMinutes = 0, visibleMinutes = 0, samples = 0;
  console.log('watching', sel.question, '| YES buy', own.yesBid, '| NO buy', noArg, '| until', new Date(endAt).toISOString());
  while (Date.now() < endAt) {
    const tick0 = Date.now();
    const row = { observed_utc: new Date().toISOString(), condition_id: sel.condition_id, alerts: [] };
    try {
      const rec = await L.rewardRecord(sel.condition_id);
      const ev = L.evaluate(await L.book(sel.yes_token), { maxSpread: rec.maxSpread, minSize: rec.minSize }, own);
      Object.assign(row, { rate: rec.rate, min_size: rec.minSize, max_spread_cents: rec.maxSpread, competitiveness: rec.competitiveness, assets: rec.assets }, ev);
      samples++;
      if (rec.minSize > L.RULE.size) row.alerts.push('MIN_SIZE_NOW_' + rec.minSize + '_QUOTE_NO_LONGER_ELIGIBLE__CANCEL_BOTH_AND_STOP');
      if (rec.rate < L.RULE.min_rate) row.alerts.push('RATE_BELOW_' + L.RULE.min_rate);
      if (ev.status === 'ok') {
        for (const [name, d] of [['YES', ev.bid_distance_cents], ['NO', ev.ask_distance_cents]]) {
          if (d < L.RULE.window_low_cents) row.alerts.push(name + '_LEG_' + d.toFixed(1) + 'c_FROM_MID__TOO_CLOSE__REQUOTE');
          if (d > L.RULE.window_high_cents) row.alerts.push(name + '_LEG_' + d.toFixed(1) + 'c_FROM_MID__TOO_FAR__REQUOTE');
        }
        const visible = ev.displayed_at_our_bid >= L.RULE.size && ev.displayed_at_our_ask >= L.RULE.size;
        if (!visible) row.alerts.push('A_LEG_IS_NOT_VISIBLE_IN_THE_BOOK__FILLED_OR_CANCELLED__CHECK_ACCOUNT');
        if (visible) visibleMinutes++;
        if (visible && ev.own_q > 0 && rec.minSize <= L.RULE.size) {
          scoredMinutes++;
          pMany += rec.rate / 1440 * ev.share_many;
          pSingle += rec.rate / 1440 * ev.share_single;
        }
      } else row.alerts.push('BOOK_' + ev.status.toUpperCase());
    } catch (e) { row.alerts.push('READ_FAILED'); row.error = String(e && e.message).slice(0, 120); }
    Object.assign(row, { cumulative_predicted_many: pMany, cumulative_predicted_single: pSingle, scored_minutes: scoredMinutes });
    fs.appendFileSync(journal, JSON.stringify(row) + '\n');
    const line = row.observed_utc.slice(11, 19) + ' mid ' + (row.mid != null ? row.mid.toFixed(3) : 'na') + ' share ' + (row.share_many != null ? row.share_many.toFixed(2) : 'na') + ' predicted ' + pMany.toFixed(3) + '-' + pSingle.toFixed(3) + ' scored_min ' + scoredMinutes;
    console.log(row.alerts.length ? 'ALERT ' + line + ' :: ' + row.alerts.join(' ; ') : line);
    await L.sleep(Math.max(1000, 60000 - (Date.now() - tick0)));
  }
  const summary = { schema: 're1_prediction.v1', condition_id: sel.condition_id, question: sel.question, started_utc: started.toISOString(), ended_utc: new Date().toISOString(),
    own, planned_minutes: minutes, samples, visible_minutes: visibleMinutes, scored_minutes: scoredMinutes, P_many: pMany, P_single: pSingle, journal, journal_sha256: L.sha256(fs.readFileSync(journal, 'utf8')) };
  const body = JSON.stringify(summary, null, 1);
  const file = path.join(outDir, 're1_prediction_' + tag + '.json');
  fs.writeFileSync(file, body);
  console.log('FROZEN PREDICTION', file, 'sha256', L.sha256(body));
})();
