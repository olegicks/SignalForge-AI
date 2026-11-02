"""POST /ask: the only write-capable endpoint. Everything else in the API is read-only."""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from openai import OpenAIError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.rag import AskError, AskLLM, OpenAIAskLLM, answer_question
from app.ratelimit import RateLimiter
from app.schemas import AskIn, AskOut, AskSourceOut, AskTokensOut
from core.config import get_settings
from core.db import get_session
from core.models import AskRequest
from pipeline.embeddings import Embedder, EmbeddingError, OpenAIEmbedder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])


@dataclass
class AskServices:
    embedder: Embedder
    llm: AskLLM


@lru_cache
def _build_services() -> AskServices:
    settings = get_settings()
    return AskServices(embedder=OpenAIEmbedder(settings), llm=OpenAIAskLLM(settings))


def get_ask_services() -> AskServices:
    try:
        return _build_services()
    except (AskError, EmbeddingError) as exc:
        logger.warning("ask is not configured: %s", exc)
        # The message only ever names a missing setting (e.g. "OPENAI_MODEL is not set"),
        # never a value, so it is safe to show and tells the operator what to add.
        raise HTTPException(
            status_code=503, detail=f"Ask the news is not configured on this server: {exc}."
        ) from exc


@lru_cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_settings().ask_rate_limit_per_minute)


def client_ip(request: Request) -> str:
    # Render puts the real client first in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def asks_today(session: Session) -> int:
    start = datetime.combine(datetime.now(UTC).date(), time(), tzinfo=UTC)
    stmt = select(func.count()).select_from(AskRequest).where(AskRequest.created_at >= start)
    return session.scalar(stmt) or 0


@router.post("/ask", response_model=AskOut)
def ask(
    body: AskIn,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    services: Annotated[AskServices, Depends(get_ask_services)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> AskOut:
    """Answer a question using only stored news and signals, with verifiable sources."""
    settings = get_settings()
    ip = client_ip(request)
    if not limiter.allow(ip):
        raise HTTPException(status_code=429, detail="Too many questions. Try again in a minute.")
    if asks_today(session) >= settings.ask_daily_limit:
        raise HTTPException(
            status_code=429, detail="The daily question limit is reached. Try again tomorrow."
        )

    try:
        result = answer_question(
            session,
            body.question,
            ticker=body.ticker,
            embedder=services.embedder,
            llm=services.llm,
            settings=settings,
        )
    except (AskError, EmbeddingError, OpenAIError) as exc:
        logger.error("ask failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=502, detail="The answer service failed. Please try again."
        ) from exc

    session.add(
        AskRequest(
            ip_hash=hashlib.sha256(ip.encode("utf-8")).hexdigest(),
            ticker=body.ticker,
            retrieved_count=result.retrieved_count,
            sufficient_evidence=result.sufficient_evidence,
            embedding_tokens=result.embedding_tokens,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            est_cost_usd=Decimal(str(round(result.est_cost_usd, 6))),
        )
    )
    session.commit()

    return AskOut(
        answer=result.answer,
        sources=[
            AskSourceOut(
                id=n,
                kind=item.kind,
                title=item.title,
                url=item.url,
                source=item.source,
                published_at=item.published_at,
                ticker=item.ticker,
                similarity=round(item.similarity, 4),
            )
            for n, item in result.sources
        ],
        sufficient_evidence=result.sufficient_evidence,
        retrieved_count=result.retrieved_count,
        tokens=AskTokensOut(
            embedding=result.embedding_tokens,
            input=result.input_tokens,
            output=result.output_tokens,
        ),
        est_cost_usd=round(result.est_cost_usd, 6),
    )
