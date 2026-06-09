import json
p = json.load(open('data/backtest/historical_backfill_plan.json'))
for q in p['queue']:
    print(f"{q['market_id']} ({q['source']}): missing {q['detail']['missing_days']} days, {q['detail']['missing_ranges']} ranges")
