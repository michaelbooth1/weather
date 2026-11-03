"""POST-HOC diagnostic for row 28 (L59). Gates nothing; not part of the prereg; the verdict is frozen.

Reads only the stage-5 and stage-6 per-row score outputs (look_rows.jsonl and final_rows.jsonl, sha256 bound in the
committed look_result.json and score_result.json; the runner scores look_rows + final_rows) and those two files. No refit, no label join beyond what is in the rows.
D1: X-S and X-A by calendar month and by fold, plus S's and A's own Brier by month.
D2: realised SE vs the projected sigma_eff: block design effect, per-fold contributions, input ratios.
"""
import hashlib, json, math, sys
from collections import defaultdict
from datetime import date

LOOK_ROWS = sys.argv[1]
ROWS = sys.argv[2]
LOOK_RESULT = sys.argv[3]
RESULT = sys.argv[4]
OUT = sys.argv[5]
LOOK_ROWS_SHA = "449d392a0025b77ab44d86f6adca2729e1996569f920db1a3264b07a67df24f2"
LOOK_RESULT_SHA = "9611df778250d2fa98001617c965eb9597014a02dd8122fd8b20dd450e677996"
ROWS_SHA = "a1a0a2b4d92506529a97d1e031942aa91b7e5310611ee0a3bd93b08df64fe27a"
RESULT_SHA = "32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b"

US10 = ("atlanta", "austin", "chicago", "dallas", "houston", "los-angeles",
        "miami", "nyc", "san-francisco", "seattle")
HOURS = (13, 14, 15, 16)
KAPPA_FLOOR, INFLATION, EDGE, ZH = 1.318, 1.07, 0.0057, 2.498
SIGMA_EFF = 0.016304 * math.sqrt(1.318)
PROJ_SD, PROJ_RHO, PROJ_ROWS = 0.016304, 0.137, 65.5
N_FROZEN = 660


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def as_date(s):
    return date.fromisoformat(s)


def season_year(s):
    d = as_date(s)
    return d.year + 1 if (d.month == 12 and d.day >= 17) else d.year


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


assert sha(ROWS) == ROWS_SHA, "rows sha"
assert sha(RESULT) == RESULT_SHA, "result sha"
res = json.load(open(RESULT, encoding="utf-8"))
assert res["final_rows_sha256"] == ROWS_SHA
assert sha(LOOK_ROWS) == LOOK_ROWS_SHA and sha(LOOK_RESULT) == LOOK_RESULT_SHA
assert json.load(open(LOOK_RESULT, encoding="utf-8"))["look_rows_sha256"] == LOOK_ROWS_SHA

rows = [json.loads(l) for p in (LOOK_ROWS, ROWS) for l in open(p, encoding="utf-8") if l.strip()]
maxd = max(r["date"] for r in rows)
assert maxd < "2026-09-30", "embargo"
scored = [r for r in rows if r["market"] in US10 and r["hour"] in HOURS]


def daily(left, right=None, rs=scored):
    acc = defaultdict(lambda: [0.0, 0])
    for r in rs:
        if r.get(left) is None or (right and r.get(right) is None):
            continue
        a = acc[r["date"]]
        a[0] += r[left] - (r[right] if right else 0.0)
        a[1] += 1
    return {d: s / k for d, (s, k) in acc.items()}


def stats(series):
    dates = sorted(series)
    n = len(dates)
    xs = [series[d] for d in dates]
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    pairs = [(series[a], series[b]) for a, b in zip(dates, dates[1:])
             if (as_date(b) - as_date(a)).days == 1 and season_year(a) == season_year(b)]
    u = [p[0] - m for p in pairs]; v = [p[1] - m for p in pairs]
    rho = sum(i * j for i, j in zip(u, v)) / math.sqrt(sum(i * i for i in u) * sum(j * j for j in v))
    kar = (1 + rho) / (1 - rho)
    k = max(kar, KAPPA_FLOOR)
    by = defaultdict(list)
    for d in dates:
        by[season_year(d)].append(series[d])
    blocks = []
    for vals in by.values():
        for i in range(0, len(vals), 3):
            c = vals[i:i + 3]
            blocks.append((sum(c) / len(c), len(c)))
    w = sum(b for _, b in blocks)
    mb = sum(a * b for a, b in blocks) / w
    se2b = sum(b * (a - mb) ** 2 for a, b in blocks) / w / len(blocks)
    kb3 = se2b / (sd * sd / n)
    kw = max(k, kb3)
    sew = INFLATION * sd * math.sqrt(kw / n)
    return {"n": n, "point": m, "sd": sd, "rho": rho, "pairs": len(pairs), "kappa_ar": kar, "kappa": k,
            "blocks": len(blocks), "kappa_block3": kb3, "kappa_wide": kw, "se_wide_x1.07": sew,
            "sigma_hat_wide": sd * math.sqrt(kw), "power_xs": phi(EDGE / sew - ZH),
            "n_eff": n / kw}


def group_mean(series, key):
    acc = defaultdict(list)
    for d, v in series.items():
        acc[key(d)].append(v)
    return {g: {"n": len(v), "mean": sum(v) / len(v)} for g, v in sorted(acc.items())}


month = lambda d: as_date(d).month
MONTH_ORDER = [12, 1, 2, 3, 4, 5]
out = {"label": "POST-HOC (gates nothing; verdict frozen per prereg 8.2)",
       "inputs": {"look_rows.jsonl": LOOK_ROWS_SHA, "final_rows.jsonl": ROWS_SHA, "look_result.json": LOOK_RESULT_SHA, "score_result.json": RESULT_SHA},
       "rows_total": len(rows), "rows_scored_us10_h13_16": len(scored), "max_date": maxd}

# reproduction check against the committed result
repro = {}
for arm in "ABCD":
    s = stats(daily(arm, "S"))
    ref = res["stats"][arm]["vs_S"]["pooled"]
    repro[arm] = {"point_diff": s["point"] - ref["point"], "se_diff": s["se_wide_x1.07"] - ref["se_wide_x1.07"],
                  "n": s["n"], "pairs": s["pairs"], "blocks": s["blocks"]}
    assert abs(repro[arm]["point_diff"]) < 1e-12 and abs(repro[arm]["se_diff"]) < 1e-12, arm
out["reproduction_vs_committed"] = repro

# D1
d1 = {"x_minus_s_by_month": {}, "x_minus_s_by_fold": {}, "x_minus_a_by_month": {}, "x_minus_a_by_fold": {}}
for arm in "ABCD":
    ser = daily(arm, "S")
    d1["x_minus_s_by_month"][arm] = {str(m): g for m, g in sorted(group_mean(ser, month).items(), key=lambda t: MONTH_ORDER.index(t[0]))}
    d1["x_minus_s_by_fold"][arm] = {str(f): g for f, g in group_mean(ser, season_year).items()}
for arm in "BCD":
    ser = daily(arm, "A")
    d1["x_minus_a_by_month"][arm] = {str(m): g for m, g in sorted(group_mean(ser, month).items(), key=lambda t: MONTH_ORDER.index(t[0]))}
    d1["x_minus_a_by_fold"][arm] = {str(f): g for f, g in group_mean(ser, season_year).items()}
own = {}
for arm in ("S", "A"):
    ser = daily(arm)
    own[arm] = {"by_month": {str(m): g for m, g in sorted(group_mean(ser, month).items(), key=lambda t: MONTH_ORDER.index(t[0]))},
                "by_fold": {str(f): g for f, g in group_mean(ser, season_year).items()},
                "pooled": sum(ser.values()) / len(ser)}
d1["own_brier"] = own
# share of the pooled X-S point contributed by each month (date-weighted)
ser = daily("A", "S"); tot = sum(ser.values())
d1["a_minus_s_point_share_by_month"] = {str(m): sum(v for d, v in ser.items() if month(d) == m) / tot for m in MONTH_ORDER}
# per-month S/A ratio of own Brier
d1["s_over_a_by_month"] = {k: own["S"]["by_month"][k]["mean"] / own["A"]["by_month"][k]["mean"] for k in own["S"]["by_month"]}
out["D1"] = d1

# D2
d2 = {"projection": {"sigma_eff": SIGMA_EFF, "sd_input": PROJ_SD, "rho_input": PROJ_RHO, "kappa_input": 1.318,
                     "rows_per_date_input": PROJ_ROWS, "n": N_FROZEN,
                     "se_wide_x1.07_projected": INFLATION * SIGMA_EFF / math.sqrt(N_FROZEN),
                     "power_projected": phi(EDGE / (INFLATION * SIGMA_EFF / math.sqrt(N_FROZEN)) - ZH)}}
rpd = defaultdict(int)
for r in scored:
    rpd[r["date"]] += 1
d2["rows_per_date_realised"] = sum(rpd.values()) / len(rpd)
for arm in "ABCD":
    ser = daily(arm, "S")
    s = stats(ser)
    m = s["point"]
    folds = defaultdict(list)
    for d, v in ser.items():
        folds[season_year(d)].append(v)
    ss_tot = sum((v - m) ** 2 for v in ser.values())
    per_fold = {}
    for f, v in sorted(folds.items()):
        fm = sum(v) / len(v)
        within = sum((x - fm) ** 2 for x in v)
        between = len(v) * (fm - m) ** 2
        per_fold[str(f)] = {"n": len(v), "mean": fm, "sd": math.sqrt(within / (len(v) - 1)),
                            "ss_within_share": within / ss_tot, "ss_between_share": between / ss_tot,
                            "ss_share": (within + between) / ss_tot}
    months = defaultdict(list)
    for d, v in ser.items():
        months[month(d)].append(v)
    within_m = sum(sum((x - sum(v) / len(v)) ** 2 for x in v) for v in months.values())
    s.update({
        "ratio_sd_to_input_sd": s["sd"] / PROJ_SD,
        "ratio_sqrt_kappa_wide_to_1.318": math.sqrt(s["kappa_wide"] / 1.318),
        "ratio_sqrt_n": math.sqrt(N_FROZEN / s["n"]),
        "ratio_se_realised_to_projected": s["se_wide_x1.07"] / d2["projection"]["se_wide_x1.07_projected"],
        "x_sigma_eff": s["sigma_hat_wide"] / SIGMA_EFF,
        "block_design_effect_kappa_block3": s["kappa_block3"],
        "ar_design_effect_kappa_ar": s["kappa_ar"],
        "per_fold": per_fold,
        "sd_if_month_means_removed": math.sqrt(within_m / (s["n"] - 1)),
    })
    d2[arm] = s
out["D2"] = d2
json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, sort_keys=True)
print(json.dumps(out, sort_keys=True)[:200])
