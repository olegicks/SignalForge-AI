"""Analyzer interface. Each LLM provider is one subclass of `Analyzer`."""

from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field

from pipeline.collectors.news import NewsArticle
from pipeline.collectors.prices import PriceMetrics

SignalType = Literal["bullish", "bearish", "neutral"]
RiskLevel = Literal["low", "medium", "high"]

SCORE_MIN, SCORE_MAX = 1, 10
MAX_KEY_FACTORS = 4


# The structure the model is asked to fill in. Kept free of numeric constraints so it works
# with strict structured outputs; ranges are enforced afterwards in validation. (No docstring:
# it would be sent to the model as part of the schema.)
class LLMSignal(BaseModel):
    signal: SignalType
    score: int = Field(description="1 (very bearish) to 10 (very bullish); 5 is neutral")
    risk: RiskLevel
    confidence: float = Field(description="0 to 1")
    reasoning: str = Field(description="2-3 plain sentences")
    key_factors: list[str] = Field(description="Up to 4 short strings")
    sources: list[str] = Field(description="URLs taken only from the provided news list")


class SignalResult(LLMSignal):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class AnalyzerError(RuntimeError):
    pass


class Analyzer(ABC):
    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def analyze(
        self, ticker: str, metrics: PriceMetrics, news: list[NewsArticle]
    ) -> SignalResult: ...
