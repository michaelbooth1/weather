import numpy as np
import pandas as pd

from tools.research.missing_information.clocks import asof, epoch_seconds, check3
from tools.research.missing_information.supplement import weighted_quantile, lag_intervals, ratio_rise
from tools.research.missing_information.methods import summary
from tools.research.missing_information.regimes import odds_summary
from tools.research.missing_information.run import write_json
import json


def test_clock_uses_only_past_quotes_and_rejects_stale_values():
    actual = asof([100., 200.], [.2, .8], np.array([99., 100., 199., 200., 321.]))
    np.testing.assert_allclose(actual, [np.nan, .2, .2, .8, np.nan], equal_nan=True)
    assert epoch_seconds(pd.Series(["1970-01-01T00:02:00Z"]))[0] == 120


def test_weighted_median_keeps_crossed_draw_weights_and_missing_draws():
    np.testing.assert_allclose(weighted_quantile([3, 1, 2], np.array([[0,0,0],[1,1,1],[3,0,0]])),
                               [np.nan, 2, 3], equal_nan=True)


def test_lag_censoring_and_paired_ratio_are_not_silently_dropped():
    rows = [dict(date=d, market=m, hour=h, model_loss=v, market_loss=.1)
            for d in ("a","b","c") for m in ("x","y","z") for h,v in ((8,.2),(14,.1),(18,.05))]
    frame = pd.DataFrame(rows)
    lag = lag_intervals(frame)
    assert lag[8]["median"]["estimate"] == 6
    assert lag[8]["censoring"]["estimate"] == 0
    assert ratio_rise(frame)["estimate"] == -1
    frame.model_loss = .2
    assert lag_intervals(frame)[18]["censoring"]["estimate"] == 1


def test_no_variation_does_not_claim_power_against_unseen_events():
    frame = pd.DataFrame([dict(date=d, market=m, zero=0., tail=(d=="a"))
                          for d in ("a","b") for m in ("x","y")])
    assert summary(frame, "zero", alternative=.1)["power"] is None
    assert odds_summary(frame, "zero")["status"] == "NO_TAG_VARIATION"


def test_json_retains_numpy_scalar_median_and_nulls_missing(tmp_path):
    path = tmp_path/"result.json"
    write_json(path, {"median": weighted_quantile([1.,2.], np.ones(2)), "missing": np.array([np.nan])})
    assert json.loads(path.read_text()) == {"median": 1., "missing": [None]}


def test_clock_jump_delay_uses_capture_time_and_excludes_stale_quote_gaps(tmp_path):
    folder = tmp_path/"highest-temperature-in-atlanta-on-august-15-2026"
    folder.mkdir()
    (folder/"observation_payloads_long.csv").write_text("source,provider_observed_at,first_seen_at\n")
    books = []
    for local, low_value in (("09:59:00",.6),("10:00:00",.6),("10:01:00",.7),("10:02:00",.7),("10:05:00",.8)):
        for kind,value,mid,token in (("lte",79,low_value,"one"),("gte",80,1-low_value,"two")):
            books.append(dict(captured_at_utc=f"2026-08-15T{local}-04:00",outcome="Yes",bin_kind=kind,
                              bin_value=value,bin_value_hi=value,midpoint=mid,best_bid=mid-.01,
                              best_ask=mid+.01,clob_token_id=token))
    pd.DataFrame(books).to_csv(folder/"order_books_summary.csv",index=False)
    frame = pd.DataFrame([dict(date="2026-08-15",market="atlanta",stratum="before_20260823",
                               decimal_hour=h, captured_at_utc=f"2026-08-15T{time}-04:00",
                               p_market=[.6,.4],tokens=["one","two"],winner=0,
                               bands=[dict(kind="lte",low=79,high=79),dict(kind="gte",low=80,high=80)])
                          for h,time in ((9.98,"09:59:00"),(10.05,"10:03:00"),(10.15,"10:09:00"))])
    result = check3(frame,tmp_path,pd.DataFrame(columns=["date","market"]),tmp_path)
    # Jump at 10:01 -> snapshot 10:03. The 10:05 change spans a stale 3-minute gap.
    assert result["strata"]["before_20260823"]["move_latency"]["estimate"] == 2
