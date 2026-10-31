from pathlib import Path

from pipeline.watchlist import load_watchlist

WATCHLIST = """
tickers:
  - { ticker: AAPL, name: Apple, query: "Apple stock" }
  - { ticker: MSFT, name: Microsoft, query: "Microsoft stock" }
  - { ticker: NVDA, name: NVIDIA, query: "Nvidia stock" }
"""


def write(tmp_path: Path) -> Path:
    path = tmp_path / "watchlist.yaml"
    path.write_text(WATCHLIST, encoding="utf-8")
    return path


def test_load_caps_at_limit(tmp_path: Path) -> None:
    assert [e.ticker for e in load_watchlist(write(tmp_path), limit=2)] == ["AAPL", "MSFT"]


def test_subset_keeps_order_and_dedupes(tmp_path: Path) -> None:
    entries = load_watchlist(write(tmp_path), limit=10, only=["nvda", " AAPL", "NVDA", ""])
    assert [e.ticker for e in entries] == ["NVDA", "AAPL"]
    assert entries[0].query == "Nvidia stock"


def test_unknown_ticker_gets_default_query(tmp_path: Path) -> None:
    entries = load_watchlist(write(tmp_path), limit=10, only=["IBM"])
    assert entries[0].query == "IBM stock"
