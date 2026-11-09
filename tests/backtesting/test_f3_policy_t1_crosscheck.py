"""Guards: WP-01 Decimal scoring parity without market -> backtesting imports."""
from decimal import Decimal as D
import random

from weather.backtesting import t1_rewards
from weather.market import f3_policy


def test_decimal_order_score_and_q_min_equal_t1_for_500_cases_each():
    rng=random.Random(347)
    for _ in range(500):
        size, minimum = D(rng.randint(0,200)), D(rng.randint(1,80))
        distance, spread = D(rng.randint(0,1000))/100, D(rng.randint(1,1000))/100
        assert f3_policy.order_score(size,distance,spread,minimum) == t1_rewards.order_score(size,distance,spread,minimum)
        one,two,mid=D(rng.randint(0,10000))/100,D(rng.randint(0,10000))/100,D(rng.randint(0,1000))/1000
        assert f3_policy.q_min(one,two,mid) == t1_rewards.q_min(one,two,mid)


def test_competition_upper_bound_agrees_with_t1_on_mirrored_anonymous_book():
    from datetime import datetime, timezone
    from weather.market.f3_types import BookState, Level, Terms, TokenBook

    at=datetime(2026,9,20,tzinfo=timezone.utc)
    yes=TokenBook((Level(D(".40"),D(45)),),(Level(D(".43"),D(45)),),D(".01"),D(20))
    no=TokenBook((Level(D(".57"),D(45)),),(Level(D(".60"),D(45)),),D(".01"),D(20))
    public=BookState("known",yes,no,at)
    terms=Terms(D(24),D(20),D("4.5"),D(".05"),D(0),D(".25"))
    captured={"at":at.isoformat(), "YES":dict(bids=[dict(price=".40",size="45")], asks=[dict(price=".43",size="45")]),
              "NO":dict(bids=[dict(price=".57",size="45")], asks=[dict(price=".60",size="45")])}
    resting=[dict(outcome="YES",price=D(".40"),remaining=D(20)),dict(outcome="NO",price=D(".57"),remaining=D(20))]
    share=t1_rewards.reward_share(captured,resting,dict(min_size="20",max_spread_cents="4.5"),"aggregate_upper_bound")
    own=f3_policy.q_min(*(f3_policy.order_score(D(20),D("1.5"),D("4.5"),D(20)) for _ in range(2)),D(".415"))
    competition=f3_policy.competitor_q(public,D(".415"),terms)
    assert share == own/(own+competition)
