"""Frozen occupied-public-trade-minute CP calibration; never invokes a policy/scorer."""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import math

from scipy.special import betainc

from maker_core.evidence.journal import digest
from maker_core.replay.bundle import BundleError
from maker_core.replay.payloads import decode

CALIBRATION_DATES = tuple(date(2026, 9, d) for d in (27, 28, 29))
FORMULA = "public_trade_occupied_minute_cp99_max_city"


def unavailable_calibration(quote_markets, reason):
    """Unavailable files yield a conservative scalar, never a countable manifest."""
    if (not isinstance(quote_markets, list) or any(not isinstance(m, str) or not m for m in quote_markets)
            or len(quote_markets) > 2000 or quote_markets != sorted(set(quote_markets))):
        raise BundleError("invalid_quote_market_inventory")
    return dict(format="maker_core.replay.calibration.v1", formula=FORMULA,
                dates=[d.isoformat() for d in CALIBRATION_DATES], quote_markets=quote_markets,
                markets=quote_markets, hazard_per_minute="1.000000000000", global_fallback=reason,
                cities={m: dict(n=0, x=0, dates=[], upper="1.000000000000000",
                               fallback_reasons=[reason], bound_source="unavailable_one") for m in quote_markets},
                input_hashes={}, binding_status="INCOMPLETE_REFUSE_MANIFEST")


def cp_upper(n, x, markets, *, check=lambda: None):
    """Invert the exact binomial CDF by bisection, retaining the larger endpoint.

    I_(1-p)(n-x,x+1) equals P[Binomial(n,p)<=x]. No normal or Bayesian approximation.
    scipy's regularized beta evaluates that CDF; it does not choose the quantile.
    """
    if any(type(v) is not int for v in (n, x, markets)) or not 0 <= x <= n or n == 0 or markets < 1:
        raise BundleError("invalid_cp_counts")
    if x == n:
        return dict(lower=1.0, upper=1.0, rounded_upper="1.000000000000")
    low, high, alpha = 0.0, 1.0, .01 / markets
    while high-low > 1e-13:
        check()
        middle = (low+high)/2
        cdf = float(betainc(n-x, x+1, 1-middle))
        if not math.isfinite(cdf):
            raise ArithmeticError("uncomputable_cp_cdf")
        if cdf > alpha:
            low = middle
        else:
            high = middle
    rounded = min(Decimal(1), Decimal.from_float(high).quantize(Decimal(".000000000001"), rounding=ROUND_CEILING))
    return dict(lower=low, upper=high, rounded_upper=str(rounded))


def sparse(count):
    return [reason for failed, reason in ((count["n"] < 1440, "n_below_1440"),
            (count["x"] < 30, "x_below_30"), (len(count["dates"]) < 3, "dates_below_3")) if failed]


def _trades(bundles, check):
    seen, occupied, invalid = {}, set(), set()
    for bundle in bundles:
        for row in bundle.records:
            check()
            if row.kind != "trade":
                continue
            minute = row.captured_at.replace(second=0, microsecond=0)
            cell = row.condition_id, minute
            try:
                trade = decode(row)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                invalid.add(cell)
                continue
            key, signature = (row.condition_id, trade.trade_id), digest(trade)
            if key in seen:
                previous, cells = seen[key]
                cells.add(cell)
                if previous != signature:
                    invalid.update(cells)
                    seen[key] = None, cells  # Every subsequent duplicate remains conflicted.
                continue
            seen[key] = signature, {cell}
            occupied.add(cell)
    return occupied, invalid


def _count(bundle, condition, occupied, invalid, check):
    descriptors, coverage = [], []
    for row in bundle.records:
        if row.condition_id != condition.condition_id or row.kind not in ("descriptor", "coverage"):
            continue
        check()
        try:
            value = decode(row)
            if row.kind == "descriptor" and value.market.domain_id != condition.domain_id:
                raise BundleError("descriptor_domain_mismatch")
            if row.kind == "coverage" and (value.valid_until_utc-row.captured_at).total_seconds() > 30:
                raise BundleError("coverage_exceeds_exporter_expiry")
        except (ValueError, KeyError, TypeError, ArithmeticError):
            value = None
        (descriptors if row.kind == "descriptor" else coverage).append((row.captured_at, value))
    dtimes, ctimes = [v[0] for v in descriptors], [v[0] for v in coverage]
    n = x = 0
    exclusions = Counter()
    start = datetime.combine(bundle.day, datetime.min.time(), tzinfo=timezone.utc)
    for i in range(1440):
        check()
        at = start+timedelta(minutes=i)
        end = at+timedelta(minutes=1)
        di = bisect_right(dtimes, at)-1
        descriptor = descriptors[di][1] if di >= 0 else None
        if descriptor is None:
            exclusions["missing_or_invalid_descriptor"] += 1
            continue
        if descriptor.horizon_days not in (1, 2):
            exclusions["outside_t1_t2"] += 1
            continue
        if (condition.condition_id, at) in invalid:
            exclusions["invalid_or_conflicting_trade"] += 1
            continue
        cursor, ci = at, bisect_right(ctimes, at)-1
        while cursor < end:
            value = coverage[ci][1] if ci >= 0 else None
            if value is None or not value.trade_stream_ok or value.valid_until_utc <= cursor:
                break
            next_capture = ctimes[ci+1] if ci+1 < len(ctimes) else end
            cursor = min(end, next_capture, value.valid_until_utc)
            if cursor == next_capture and cursor < end:
                # Last capture at a timestamp wins, matching captured sequence order.
                ci = bisect_right(ctimes, cursor)-1
        if cursor < end:
            exclusions["trade_coverage_gap"] += 1
            continue
        n += 1
        x += (condition.condition_id, at) in occupied
    return n, x, exclusions


def calibrate(bundles, quote_markets, *, check=lambda: None):
    bundles = tuple(sorted(bundles, key=lambda b: b.day))
    if tuple(b.day for b in bundles) != CALIBRATION_DATES:
        raise BundleError("calibration_requires_exact_three_dates")
    if (not isinstance(quote_markets, list) or len(quote_markets) > 2000
            or any(not isinstance(m, str) or not m for m in quote_markets)
            or quote_markets != sorted(set(quote_markets))):
        raise BundleError("invalid_quote_market_inventory")
    if any(row.kind not in ("descriptor", "coverage", "trade") for b in bundles for row in b.records):
        raise BundleError("calibration_requires_descriptor_coverage_trade_only_bundles")
    markets = sorted(set(quote_markets) | {c.market_id for b in bundles for c in b.conditions})
    occupied, invalid = _trades(bundles, check)
    counts = {m: dict(n=0, x=0, dates=set(), exclusions=Counter()) for m in markets}
    identity = {}
    for bundle in bundles:
        for condition in bundle.conditions:
            check()
            cid = condition.condition_id
            cluster = (condition.market_id, condition.domain_id)
            if identity.setdefault(cid, cluster) != cluster:
                raise BundleError("condition_cluster_identity_changed")
            n, x, exclusions = _count(bundle, condition, occupied, invalid, check)
            count = counts[condition.market_id]
            count["n"] += n
            count["x"] += x
            if n:
                count["dates"].add(bundle.day.isoformat())
            count["exclusions"].update(exclusions)
    pooled = dict(n=sum(c["n"] for c in counts.values()), x=sum(c["x"] for c in counts.values()),
                  dates=sorted({d for c in counts.values() for d in c["dates"]}))
    pooled["fallback_reasons"] = sparse(pooled)
    for count in counts.values():
        count["dates"] = sorted(count["dates"])
        count["exclusions"] = dict(sorted(count["exclusions"].items()))
    numeric_failure = False
    try:
        pooled["bound"] = cp_upper(pooled["n"], pooled["x"], len(markets), check=check) if not sparse(pooled) else None
        for market, count in counts.items():
            count["dates"] = sorted(count["dates"])
            count["exclusions"] = dict(sorted(count["exclusions"].items()))
            count["fallback_reasons"] = sparse(count)
            if count["n"] == 0:
                count["fallback_reasons"].append("absent_calibration_city")
            count["bound"] = (pooled["bound"] if count["fallback_reasons"] else
                              cp_upper(count["n"], count["x"], len(markets), check=check))
            count["bound_source"] = ("pooled" if count["bound"] else "sparse_pool_one") if count["fallback_reasons"] else "city"
            count["upper"] = count["bound"]["rounded_upper"] if count["bound"] else "1.000000000000"
    except ArithmeticError:
        numeric_failure = True
    hazard = "1.000000000000" if numeric_failure else max((c["upper"] for c in counts.values()), default="1.000000000000")
    return dict(format="maker_core.replay.calibration.v1", formula=FORMULA,
                dates=[d.isoformat() for d in CALIBRATION_DATES], quote_markets=quote_markets, markets=markets,
                alpha_family=.01, quantile=1-.01/len(markets) if markets else None,
                cities=counts, pooled=pooled, hazard_per_minute=hazard,
                global_fallback="uncomputable_numerical_bound" if numeric_failure else "empty_inventory" if not markets else None,
                fallback_counts=dict(Counter(c.get("bound_source", "uncomputable") for c in counts.values())),
                input_hashes={b.day.isoformat(): dict(b.input_hashes) for b in bundles},
                source_hashes_sha256=digest([dict(r.source_hashes) for b in bundles for r in b.records]),
                interpretation="Working binomial family bound; public opportunities, not actual own fills or guaranteed losses.")
