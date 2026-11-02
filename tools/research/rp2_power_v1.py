"""R-P2 power inputs from the already-read row-109 LOYO rows (disclosed variance only; no dev labels)."""
import json, math, sys
from collections import defaultdict
from statistics import NormalDist
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
by = defaultdict(lambda: [0.0, 0])
for r in rows:
    a = by[r["date"]]; a[0] += r["P3d_N_pool_brier"] - r["P3d_N_11m_brier"]; a[1] += 1
means = [s / n for s, n in by.values()]
k = len(means); mu = sum(means) / k
sd = math.sqrt(sum((m - mu) ** 2 for m in means) / (k - 1))
rows_per_date = sum(n for _, n in by.values()) / k
# lag-1 autocorrelation within year of per-date means
dates = sorted(by)
pairs = [(by[a][0]/by[a][1], by[b][0]/by[b][1]) for a, b in zip(dates, dates[1:]) if a[:4] == b[:4]]
x = [p[0]-mu for p in pairs]; y = [p[1]-mu for p in pairs]
rho = sum(i*j for i, j in zip(x, y)) / math.sqrt(sum(i*i for i in x) * sum(j*j for j in y))
infl_block = 1.0  # from the reported CIs: block-3 width / clustered width
cl = (-0.003448479382480723, -0.0002592661076766197); b3 = (-0.00354912779632077, -6.527541579281363e-05)
infl_block = ((b3[1]-b3[0])/(cl[1]-cl[0])) ** 2
infl_ar1 = (1 + rho) / (1 - rho) if rho > 0 else 1.0
infl = max(infl_block, infl_ar1)
out = {"n_dates": k, "rows_per_date": rows_per_date, "sd_per_date_mean_d": sd, "mean_d": mu,
       "lag1_rho_within_year": rho, "variance_inflation_block3_vs_clustered": infl_block,
       "variance_inflation_ar1": infl_ar1, "inflation_used": infl}
zb = NormalDist().inv_cdf(0.80)
for label, alpha in (("two_sided_0.05", 0.05), ("two_sided_0.01", 0.01), ("two_sided_0.005", 0.005)):
    za = NormalDist().inv_cdf(1 - alpha / 2)
    mde60 = (za + zb) * sd * math.sqrt(infl / 60)
    n_for_002 = ((za + zb) * sd / 0.002) ** 2 * infl
    out[label] = {"dev_window_60_dates_MDE80": mde60, "ratio_to_0.002": mde60 / 0.002,
                  "forward_dates_for_MDE80_0.002": n_for_002}
print(json.dumps(out, indent=1))
