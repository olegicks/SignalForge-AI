from datetime import date
from unittest.mock import MagicMock

import pandas as pd
import pytest

from pipeline.collectors import prices


def make_history(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    index = pd.bdate_range("2026-06-01", periods=len(closes), tz="America/New_York")
    return pd.DataFrame(
        {"Close": closes, "Volume": volumes or [1_000.0] * len(closes)},
        index=index,
    )


def test_compute_metrics_changes_and_volume() -> None:
    closes = [100.0] * 40 + [110.0]
    volumes = [1_000.0] * 40 + [3_000.0]
    metrics = prices.compute_metrics("AAPL", make_history(closes, volumes))

    assert metrics.last_close == 110.0
    assert metrics.change_1d_pct == 10.0
    assert metrics.change_5d_pct == 10.0
    assert metrics.change_30d_pct == 10.0
    assert metrics.volume_vs_20d_avg == 3.0


def test_compute_metrics_with_short_history() -> None:
    metrics = prices.compute_metrics("NEW", make_history([10.0, 11.0]))
    assert metrics.change_1d_pct == 10.0
    assert metrics.change_5d_pct is None
    assert metrics.change_30d_pct is None
    assert metrics.volume_vs_20d_avg is None


def test_completed_sessions_drops_todays_partial_session() -> None:
    history = make_history([10.0, 11.0, 99.0])  # 2026-06-01..03; the 3rd is "today", mid-session
    completed = prices.completed_sessions(history, date(2026, 6, 3))
    assert list(completed["Close"]) == [10.0, 11.0]
    # Early-morning run: nothing dated today yet, so nothing is dropped.
    assert len(prices.completed_sessions(history, date(2026, 6, 4))) == 3


def test_completed_sessions_raises_when_nothing_is_left() -> None:
    with pytest.raises(prices.EmptyHistoryError):
        prices.completed_sessions(make_history([10.0]), date(2026, 6, 1))


def test_recent_closes_keeps_last_days_oldest_first() -> None:
    history = make_history([float(i) for i in range(100)])
    bars = prices.recent_closes(history, days=10)
    assert bars[0][0] < bars[-1][0]
    assert (bars[-1][0] - bars[0][0]).days <= 10
    assert bars[-1][1] == 99.0


def test_fetch_history_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    good = make_history([1.0, 2.0])
    ticker = MagicMock()
    ticker.history.side_effect = [ConnectionError("flaky"), good]
    monkeypatch.setattr(prices.yf, "Ticker", lambda _symbol: ticker)

    result = prices.fetch_history("AAPL")
    assert len(result) == 2
    assert ticker.history.call_count == 2


def test_fetch_history_raises_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    ticker = MagicMock()
    ticker.history.return_value = pd.DataFrame({"Close": [], "Volume": []})
    monkeypatch.setattr(prices.yf, "Ticker", lambda _symbol: ticker)

    with pytest.raises(prices.EmptyHistoryError):
        prices.fetch_history("NOPE")
    assert ticker.history.call_count == 3


def test_download_closes_splits_per_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    index = pd.DatetimeIndex(["2026-10-01", "2026-10-02"])
    columns = pd.MultiIndex.from_product([["Close", "Volume"], ["AAPL", "MSFT"]])
    frame = pd.DataFrame(
        [[1.0, 10.0, 5, 5], [2.0, float("nan"), 5, 5]], index=index, columns=columns
    )
    download = MagicMock(return_value=frame)
    monkeypatch.setattr(prices.yf, "download", download)

    result = prices.download_closes(["AAPL", "MSFT", "GONE"], date(2026, 10, 1), date(2026, 10, 2))

    assert list(result["AAPL"].index) == [date(2026, 10, 1), date(2026, 10, 2)]
    assert list(result["MSFT"]) == [10.0]
    assert "GONE" not in result
    assert download.call_args.kwargs["end"] == "2026-10-03"
