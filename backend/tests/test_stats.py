import pytest

from app.stats import Outcome, horizon_stats, is_hit


@pytest.mark.parametrize(
    ("signal", "ret", "expected"),
    [
        ("bullish", 0.02, True),
        ("bullish", -0.01, False),
        ("bullish", 0.0, False),
        ("bearish", -0.03, True),
        ("bearish", 0.01, False),
        ("neutral", 0.05, None),
    ],
)
def test_is_hit(signal: str, ret: float, expected: bool | None) -> None:
    assert is_hit(signal, ret) is expected


def test_horizon_stats_hit_rate_excludes_neutral() -> None:
    outcomes = [
        Outcome("bullish", 0.8, 0.05),  # hit
        Outcome("bullish", 0.5, -0.02),  # miss
        Outcome("bearish", 0.2, -0.04),  # hit
        Outcome("bearish", 0.9, 0.01),  # miss
        Outcome("bullish", 1.0, 0.03),  # hit
        Outcome("neutral", 0.1, 0.10),  # excluded
    ]
    stats = horizon_stats(7, outcomes)

    assert stats.evaluated == 6
    assert stats.directional == 5
    assert stats.hits == 3
    assert stats.hit_rate == 0.6
    assert stats.by_signal["bullish"].count == 3
    assert stats.by_signal["bullish"].avg_return == pytest.approx(0.02)
    assert stats.by_signal["bearish"].avg_return == pytest.approx(-0.015)
    assert stats.by_signal["neutral"].avg_return == pytest.approx(0.10)

    buckets = {b.bucket: b for b in stats.by_confidence}
    assert (buckets["0.0-0.4"].count, buckets["0.0-0.4"].hits) == (1, 1)
    assert (buckets["0.4-0.7"].count, buckets["0.4-0.7"].hit_rate) == (1, 0.0)
    # 0.8 hit, 0.9 miss, 1.0 hit (1.0 belongs to the top bucket)
    assert (buckets["0.7-1.0"].count, buckets["0.7-1.0"].hits) == (3, 2)


def test_horizon_stats_benchmark_and_base_rate() -> None:
    outcomes = [
        Outcome("bullish", 0.5, 0.03, benchmark=0.01),  # up and beat SPY: hit, relative hit
        Outcome("bullish", 0.5, 0.01, benchmark=0.04),  # up but lagged SPY: hit, relative miss
        Outcome("bearish", 0.5, 0.02, benchmark=0.05),  # up (miss) but lagged SPY: relative hit
        Outcome("neutral", 0.1, -0.01, benchmark=0.00),  # excluded from (relative) hit rates
        Outcome("bullish", 0.5, 0.02),  # no benchmark: counted only in absolute stats
    ]
    stats = horizon_stats(7, outcomes)

    assert (stats.directional, stats.hits) == (4, 3)
    assert (stats.relative_directional, stats.relative_hits) == (3, 2)
    assert stats.relative_hit_rate == pytest.approx(0.6667, abs=1e-4)
    assert stats.base_rate_up == 0.8  # 4 of 5 went up
    assert stats.avg_benchmark_return == pytest.approx(0.025)
    assert stats.by_signal["bullish"].avg_excess_return == pytest.approx(-0.005)
    assert stats.by_signal["bearish"].avg_excess_return == pytest.approx(-0.03)


def test_horizon_stats_empty() -> None:
    stats = horizon_stats(30, [])
    assert stats.hit_rate is None
    assert stats.by_signal["bullish"].avg_return is None
    assert all(b.hit_rate is None for b in stats.by_confidence)
