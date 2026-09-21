"""Development scoring only, called after the freeze and push gate."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import numpy as np
import pandas as pd

from tools.research.morning_guidance.candidate import candidates
from tools.research.morning_guidance.statistics import planning, summarize


def score(path, freeze_date):
    rows = []
    first_score = None
    with path.open() as stream:
        for line in stream:
            s = json.loads(line)
            if not 6 <= s["hour"] < 13:
                continue
            c1, c2, reason = candidates(s["bands"], s["p_model"], s["features"])
            if first_score is None:
                first_score = datetime.now(timezone.utc).isoformat()
            p, market = np.array(s["p_model"]), np.array(s["p_market"])
            y = np.eye(len(p))[s["winner"]]
            row = {"date": s["date"], "market": s["market"], "stratum": s["stratum"],
                   "window": "morning_06_10" if s["hour"] < 10 else "secondary_10_13",
                   "reason": reason, "served": float(np.mean((p-y)**2)),
                   "market_loss": float(np.mean((market-y)**2)), "eligible": int(reason == "eligible")}
            for name, candidate in (("C1", c1), ("C2", c2)):
                row[name] = float(np.mean((candidate-y)**2))
                row[name+"_delta"] = row[name] - row["served"]
                row[name+"_changed"] = int(not np.array_equal(candidate, p))
            row["C2_minus_C1"] = row["C2"] - row["C1"]
            rows.append(row)
    frame = pd.DataFrame(rows)
    result = {"first_score_at_utc": first_score, "tables": []}
    for window, window_frame in frame.groupby("window"):
        for population in ("US11", "all12"):
            region = window_frame[window_frame.market != "toronto"] if population == "US11" else window_frame
            for stratum in ("before_20260823", "from_20260823", "pooled"):
                f = region if stratum == "pooled" else region[region.stratum == stratum]
                columns = ["served", "market_loss", "C1", "C2", "C1_delta", "C2_delta",
                           "C1_changed", "C2_changed", "eligible", "C2_minus_C1"]
                cells = f.groupby(["date", "market"])[columns].mean().reset_index()
                table = {"window": window, "population": population, "stratum": stratum,
                         "snapshots": len(f), "market_days": len(cells),
                         "date_clusters": cells.date.nunique(), "market_clusters": cells.market.nunique(),
                         "reason_counts": dict(Counter(f.reason)),
                         "served": summarize(cells, "served"), "market": summarize(cells, "market_loss"),
                         "C2_minus_C1": summarize(cells, "C2_minus_C1")}
                for name in ("C1", "C2"):
                    table[name] = {"brier": summarize(cells, name),
                        "delta": summarize(cells, name+"_delta"),
                        "ratio_to_market": summarize(cells, name, "market_loss", effect=-.1),
                        "changed_snapshots": int(f[name+"_changed"].sum()),
                        "changed_date_clusters": f[f[name+"_changed"] == 1].date.nunique(),
                        "changed_market_clusters": f[f[name+"_changed"] == 1].market.nunique(),
                        "changed_market_days": len(f[f[name+"_changed"] == 1][["date", "market"]].drop_duplicates()),
                        "changed_snapshot_share": float(f[name+"_changed"].mean()),
                        "changed_market_day_share": summarize(cells, name+"_changed", effect=.1),
                        "planning": planning(cells, name+"_delta", freeze_date)}
                result["tables"].append(table)
                print(f"{window}/{population}/{stratum}: C1={table['C1']['delta']['estimate']:.7f}, C2={table['C2']['delta']['estimate']:.7f}", flush=True)
    return result, frame
