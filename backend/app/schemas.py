"""API response models."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthOut(BaseModel):
    status: str
    database: bool


class RunOut(ORMModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    tickers_processed: int
    tickers_failed: int
    input_tokens: int
    output_tokens: int
    est_cost_usd: float
    model: str | None
    error_summary: str | None


class SignalOut(ORMModel):
    id: int
    run_id: int
    ticker: str
    as_of_date: date
    signal: str
    score: int
    risk: str
    confidence: float
    reasoning: str
    key_factors: list[str]
    sources: list[str]
    price_at_signal: float
    model: str
    created_at: datetime
    price_7d: float | None
    return_7d: float | None
    price_30d: float | None
    return_30d: float | None
    evaluated_7d_at: datetime | None
    evaluated_30d_at: datetime | None


class LatestSignalsOut(BaseModel):
    as_of_date: date | None
    signals: list[SignalOut]


class NewsOut(ORMModel):
    id: int
    ticker: str
    title: str
    summary: str | None
    url: str
    source: str
    published_at: datetime


class PricePoint(ORMModel):
    date: date
    close: float


class TickerDetailOut(BaseModel):
    ticker: str
    name: str | None
    signals: list[SignalOut]
    news: list[NewsOut]
    prices: list[PricePoint]


class ConfidenceBucketStats(BaseModel):
    bucket: str
    count: int
    hits: int
    hit_rate: float | None


class SignalTypeStats(BaseModel):
    count: int
    avg_return: float | None


class HorizonStats(BaseModel):
    horizon_days: int
    evaluated: int
    directional: int
    hits: int
    hit_rate: float | None
    by_signal: dict[str, SignalTypeStats]
    by_confidence: list[ConfidenceBucketStats]


class TrackRecordOut(BaseModel):
    total_signals: int
    horizons: list[HorizonStats]
    recent_evaluated: list[SignalOut]
