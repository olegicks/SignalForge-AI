"""Post-checks on model output. The model is never trusted to stay within the rules."""

from pipeline.analyzer.base import MAX_KEY_FACTORS, SCORE_MAX, SCORE_MIN, SignalResult
from pipeline.collectors.news import NewsArticle


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def validate_result(result: SignalResult, news: list[NewsArticle]) -> SignalResult:
    """Drop sources we did not provide, clamp numbers and trim lists."""
    allowed_urls = {article.url for article in news}
    sources: list[str] = []
    for url in result.sources:
        url = url.strip()
        if url in allowed_urls and url not in sources:
            sources.append(url)

    key_factors = [factor.strip() for factor in result.key_factors if factor.strip()]

    return result.model_copy(
        update={
            "score": int(clamp(round(result.score), SCORE_MIN, SCORE_MAX)),
            "confidence": round(clamp(result.confidence, 0.0, 1.0), 3),
            "reasoning": result.reasoning.strip(),
            "key_factors": key_factors[:MAX_KEY_FACTORS],
            "sources": sources,
        }
    )
