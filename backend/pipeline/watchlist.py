"""Watchlist loading."""

from pathlib import Path

import yaml
from pydantic import BaseModel


class WatchlistEntry(BaseModel):
    ticker: str
    name: str
    query: str


def load_watchlist(path: Path, limit: int, only: list[str] | None = None) -> list[WatchlistEntry]:
    """Read the watchlist, optionally narrowed to `only`, capped at `limit` entries.

    Tickers in `only` that are not in the file are still allowed, with a default news query.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = [WatchlistEntry(**item) for item in data.get("tickers", [])]

    if only:
        by_ticker = {entry.ticker.upper(): entry for entry in entries}
        entries = [
            by_ticker.get(t, WatchlistEntry(ticker=t, name=t, query=f"{t} stock"))
            for t in dict.fromkeys(symbol.strip().upper() for symbol in only if symbol.strip())
        ]
    return entries[:limit]
