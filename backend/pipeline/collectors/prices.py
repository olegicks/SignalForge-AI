"""Price data from yfinance. All numbers shown to the LLM come from here, never from the model."""

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from pydantic import BaseModel

from pipeline.retry import network_retry

logger = logging.getLogger(__name__)

HISTORY_PERIOD = "6mo"
PRICE_BAR_DAYS = 90


class PriceMetrics(BaseModel):
    ticker: str
    last_close: float
    last_date: date
    change_1d_pct: float | None
    change_5d_pct: float | None
    change_30d_pct: float | None
    volume_vs_20d_avg: float | None


class EmptyHistoryError(RuntimeError):
    pass


@network_retry
def fetch_history(ticker: str) -> pd.DataFrame:
    """Daily OHLCV for the last few months. Raises if yfinance returns nothing."""
    history = yf.Ticker(ticker).history(period=HISTORY_PERIOD, interval="1d", auto_adjust=True)
    history = history.dropna(subset=["Close"])
    if history.empty:
        raise EmptyHistoryError(f"yfinance returned no price history for {ticker}")
    return history


def _pct_change(new: float, old: float) -> float | None:
    if old == 0 or pd.isna(old):
        return None
    return round((new / old - 1) * 100, 2)


def compute_metrics(ticker: str, history: pd.DataFrame) -> PriceMetrics:
    """1d and 5d changes are over trading sessions; the 30d change is over calendar days."""
    closes = history["Close"]
    last_close = float(closes.iloc[-1])
    last_date = closes.index[-1].date()

    change_1d = _pct_change(last_close, float(closes.iloc[-2])) if len(closes) >= 2 else None
    change_5d = _pct_change(last_close, float(closes.iloc[-6])) if len(closes) >= 6 else None

    cutoff = last_date - timedelta(days=30)
    older = closes[[ts.date() <= cutoff for ts in closes.index]]
    change_30d = _pct_change(last_close, float(older.iloc[-1])) if not older.empty else None

    volume_ratio = None
    if "Volume" in history and len(history) >= 21:
        avg_volume = float(history["Volume"].iloc[-21:-1].mean())
        if avg_volume > 0:
            volume_ratio = round(float(history["Volume"].iloc[-1]) / avg_volume, 2)

    return PriceMetrics(
        ticker=ticker,
        last_close=round(last_close, 4),
        last_date=last_date,
        change_1d_pct=change_1d,
        change_5d_pct=change_5d,
        change_30d_pct=change_30d,
        volume_vs_20d_avg=volume_ratio,
    )


def recent_closes(history: pd.DataFrame, days: int = PRICE_BAR_DAYS) -> list[tuple[date, float]]:
    """(date, close) pairs for the price chart, oldest first."""
    cutoff = history.index[-1].date() - timedelta(days=days)
    return [
        (ts.date(), round(float(close), 4))
        for ts, close in history["Close"].items()
        if ts.date() >= cutoff
    ]


@network_retry
def download_closes(tickers: list[str], start: date, end: date) -> dict[str, pd.Series]:
    """Batched daily closes for many tickers between start and end (inclusive).

    Returns one Series per ticker, indexed by date, with missing days dropped.
    """
    if not tickers:
        return {}
    frame = yf.download(
        tickers,
        start=start.isoformat(),
        # yfinance treats `end` as exclusive.
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
        progress=False,
        threads=True,
        multi_level_index=True,
    )
    if frame is None or frame.empty:
        return {}

    closes = frame["Close"]
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(name=tickers[0])

    result: dict[str, pd.Series] = {}
    for ticker in tickers:
        if ticker not in closes.columns:
            continue
        series = closes[ticker].dropna()
        series.index = [ts.date() for ts in series.index]
        result[ticker] = series
    return result
