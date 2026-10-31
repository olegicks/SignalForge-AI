"""Prompt text for the analyzer. Kept short to keep token counts low."""

from pipeline.collectors.news import NewsArticle
from pipeline.collectors.prices import PriceMetrics

SUMMARY_MAX_CHARS = 300

SYSTEM_PROMPT = """\
You are a cautious equity research assistant. You turn recent news and price data for one \
stock into a short, structured signal.

Rules:
- Use ONLY the data in the user message. Do not use outside knowledge about recent events, \
prices or news.
- Never invent numbers. Refer only to figures that appear in the data.
- If the news is thin, irrelevant or contradictory, return "neutral" with low confidence \
(0.3 or less) and a score near 5.
- score: 1 = strongly bearish, 5 = neutral, 10 = strongly bullish.
- confidence: 0 to 1, how well the provided news supports the signal.
- risk: how uncertain or volatile the situation looks from the data (low, medium, high).
- reasoning: 2-3 plain sentences.
- key_factors: up to 4 short strings.
- source_ids: the numbers of the news items you relied on (e.g. [1, 3]); empty if none.
"""


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def truncate(text: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def build_user_prompt(ticker: str, metrics: PriceMetrics, news: list[NewsArticle]) -> str:
    volume = "n/a" if metrics.volume_vs_20d_avg is None else f"{metrics.volume_vs_20d_avg:.2f}x"
    lines = [
        f"Ticker: {ticker}",
        f"Price data (as of {metrics.last_date.isoformat()}): last close {metrics.last_close:.2f}; "
        f"change 1d {_fmt_pct(metrics.change_1d_pct)}, 5d {_fmt_pct(metrics.change_5d_pct)}, "
        f"30d {_fmt_pct(metrics.change_30d_pct)}; volume vs 20-day average {volume}.",
        "",
        f"News ({len(news)} items):",
    ]
    for i, article in enumerate(news, start=1):
        lines.append(
            f"{i}. [{article.published_at:%Y-%m-%d %H:%M} UTC] {article.source}: {article.title}"
        )
        if article.summary:
            lines.append(f"   Summary: {truncate(article.summary)}")
    # URLs are left out on purpose: the model cites items by number and the code maps the
    # numbers back to URLs, which saves tokens and makes invented links impossible.
    return "\n".join(lines)
