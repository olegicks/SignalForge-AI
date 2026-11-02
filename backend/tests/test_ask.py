"""POST /ask with OpenAI fully faked: a deterministic embedder and a scripted LLM."""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.ask import AskServices, get_ask_services, get_rate_limiter
from app.main import app
from app.rag import (
    INSUFFICIENT_ANSWER,
    AskLLMAnswer,
    LLMReply,
    build_context,
    retrieve,
    valid_source_ids,
)
from app.ratelimit import RateLimiter
from core.config import Settings
from core.db import get_session
from core.models import (
    AskRequest,
    NewsEmbedding,
    NewsItem,
    PipelineRun,
    Signal,
    SignalEmbedding,
)
from pipeline.embeddings import EmbeddingBatch
from tests.factories import NOW

DIM = Settings(_env_file=None).embedding_dim


def vec(**axes: float) -> list[float]:
    """A vector with values on named axes a, b, c (the rest zero)."""
    v = [0.0] * DIM
    for name, value in axes.items():
        v["abc".index(name)] = value
    return v


QUESTION_VECTOR = vec(a=1.0)


class FakeEmbedder:
    model_name = "fake-embedding"
    dim = DIM

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(vectors=[QUESTION_VECTOR for _ in texts], tokens=5)


class FakeLLM:
    model_name = "fake-llm"

    def __init__(self, reply: AskLLMAnswer) -> None:
        self.reply = reply
        self.contexts: list[str] = []

    def answer(self, question: str, context: str) -> LLMReply:
        self.contexts.append(context)
        return LLMReply(parsed=self.reply, input_tokens=300, output_tokens=60)


def add_news(session: Session, key: str, ticker: str, vector: list[float]) -> None:
    item = NewsItem(
        ticker=ticker,
        title=f"News {key}",
        summary=f"Summary {key}.",
        url=f"https://news.example.com/{key}",
        source="Reuters",
        published_at=NOW,
    )
    session.add(item)
    session.flush()
    session.add(NewsEmbedding(news_item_id=item.id, embedding=vector, model="fake"))


@pytest.fixture
def corpus(db_session: Session) -> Session:
    # Similarity to the question (axis a): A 1.0, B 0.8, AAPL signal 0.6, MSFT news 0.0.
    add_news(db_session, "A", "AAPL", vec(a=1.0))
    add_news(db_session, "B", "AAPL", vec(a=0.8, b=0.6))
    add_news(db_session, "C", "MSFT", vec(b=1.0))
    signal = Signal(
        run=PipelineRun(model="m"),
        ticker="AAPL",
        as_of_date=date(2026, 10, 30),
        signal="bullish",
        score=7,
        risk="medium",
        confidence=0.6,
        reasoning="Demand looks solid.",
        key_factors=[],
        sources=[],
        price_at_signal=Decimal("100"),
        model="m",
    )
    db_session.add(signal)
    db_session.flush()
    db_session.add(
        SignalEmbedding(
            signal_id=signal.id, embedding=vec(a=0.6, c=0.8), content_hash="x", model="fake"
        )
    )
    db_session.flush()
    return db_session


@pytest.fixture
def make_client(corpus: Session) -> Iterator:
    def build(reply: AskLLMAnswer, limit: int = 5) -> tuple[TestClient, FakeLLM]:
        llm = FakeLLM(reply)

        def override_session() -> Iterator[Session]:
            yield corpus

        limiter = RateLimiter(limit)
        app.dependency_overrides[get_session] = override_session
        app.dependency_overrides[get_ask_services] = lambda: AskServices(FakeEmbedder(), llm)
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
        return TestClient(app), llm

    yield build
    app.dependency_overrides.clear()


GOOD_REPLY = AskLLMAnswer(
    answer="Demand is solid [1] and the signal is bullish [3].",
    source_ids=[1, 3, 9, 1],
    sufficient_evidence=True,
)


# --- retrieval ---------------------------------------------------------------


def test_retrieval_ranks_by_similarity_and_applies_threshold(corpus: Session) -> None:
    items = retrieve(corpus, QUESTION_VECTOR, top_k=8, min_similarity=0.3)
    assert [(i.kind, i.title.split(":")[0]) for i in items] == [
        ("news", "News A"),
        ("news", "News B"),
        ("signal", "AAPL signal on Oct 30"),
    ]
    assert [round(i.similarity, 2) for i in items] == [1.0, 0.8, 0.6]
    # MSFT news (similarity 0) is below the threshold; a stricter threshold drops more.
    assert len(retrieve(corpus, QUESTION_VECTOR, top_k=8, min_similarity=0.7)) == 2


def test_retrieval_respects_top_k(corpus: Session) -> None:
    items = retrieve(corpus, QUESTION_VECTOR, top_k=2, min_similarity=0.0)
    assert [i.title for i in items] == ["News A", "News B"]


def test_retrieval_filters_by_ticker(corpus: Session) -> None:
    items = retrieve(corpus, QUESTION_VECTOR, top_k=8, min_similarity=-1, ticker="MSFT")
    assert [i.ticker for i in items] == ["MSFT"]


def test_context_is_numbered_and_has_no_urls(corpus: Session) -> None:
    context = build_context(retrieve(corpus, QUESTION_VECTOR, top_k=8, min_similarity=0.3))
    assert context.startswith("[1] (news, AAPL")
    assert "[3] (signal, AAPL" in context
    assert "https://" not in context


def test_valid_source_ids_drops_unknown_and_duplicates() -> None:
    assert valid_source_ids([2, 0, 5, 2, -1, 1], count=3) == [2, 1]


# --- endpoint ----------------------------------------------------------------


def test_ask_returns_grounded_answer_with_mapped_sources(make_client) -> None:
    client, llm = make_client(GOOD_REPLY)
    body = client.post("/ask", json={"question": "How is Apple doing?"}).json()

    assert body["sufficient_evidence"] is True
    assert body["retrieved_count"] == 3
    # Invalid id 9 and the duplicate 1 are dropped; numbers match the items sent.
    assert [s["id"] for s in body["sources"]] == [1, 3]
    assert body["sources"][0]["url"] == "https://news.example.com/A"
    assert body["sources"][0]["similarity"] == pytest.approx(1.0)
    signal_source = body["sources"][1]
    assert (signal_source["kind"], signal_source["url"]) == ("signal", "/tickers/AAPL")
    assert signal_source["similarity"] == pytest.approx(0.6)
    assert body["tokens"] == {"embedding": 5, "input": 300, "output": 60}
    assert "https://" not in llm.contexts[0]


def test_ask_with_ticker_filter_and_nothing_relevant_skips_the_llm(make_client) -> None:
    client, llm = make_client(GOOD_REPLY)
    body = client.post("/ask", json={"question": "How is Microsoft?", "ticker": "msft"}).json()
    assert body["sufficient_evidence"] is False
    assert body["answer"] == INSUFFICIENT_ANSWER
    assert body["retrieved_count"] == 0
    assert body["sources"] == []
    assert llm.contexts == []


def test_model_saying_insufficient_evidence_is_respected(make_client) -> None:
    reply = AskLLMAnswer(answer="Maybe up?", source_ids=[1], sufficient_evidence=False)
    client, _ = make_client(reply)
    body = client.post("/ask", json={"question": "Will Apple double next year?"}).json()
    assert body["sufficient_evidence"] is False
    assert body["answer"] == INSUFFICIENT_ANSWER
    assert body["sources"] == []


def test_answer_without_any_valid_source_is_rejected(make_client) -> None:
    reply = AskLLMAnswer(answer="Trust me.", source_ids=[42], sufficient_evidence=True)
    client, _ = make_client(reply)
    body = client.post("/ask", json={"question": "How is Apple doing?"}).json()
    assert body["sufficient_evidence"] is False
    assert body["answer"] == INSUFFICIENT_ANSWER


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "x" * 301},
        {"question": "  "},
        {"question": "ok?"[:2]},
        {"question": "Valid question?", "ticker": "AAPL; DROP"},
        {},
    ],
)
def test_input_validation(make_client, payload: dict) -> None:
    client, llm = make_client(GOOD_REPLY)
    assert client.post("/ask", json=payload).status_code == 422
    assert llm.contexts == []


def test_question_at_the_300_char_limit_is_accepted(make_client) -> None:
    client, _ = make_client(GOOD_REPLY)
    assert client.post("/ask", json={"question": "a" * 300}).status_code == 200


def test_rate_limit_per_ip(make_client) -> None:
    client, _ = make_client(GOOD_REPLY, limit=5)
    headers = {"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
    codes = [
        client.post("/ask", json={"question": "How is Apple?"}, headers=headers).status_code
        for _ in range(6)
    ]
    assert codes == [200] * 5 + [429]
    # Another client is not affected.
    other = {"X-Forwarded-For": "198.51.100.2"}
    assert client.post("/ask", json={"question": "Apple?"}, headers=other).status_code == 200


def test_daily_cap(make_client, corpus: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASK_DAILY_LIMIT", "2")
    client, _ = make_client(GOOD_REPLY, limit=100)
    codes = [client.post("/ask", json={"question": "Apple?"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    # Each answered request is logged, without the question text.
    rows = corpus.scalars(select(AskRequest)).all()
    assert len(rows) == 2
    assert all(len(r.ip_hash) == 64 and r.input_tokens == 300 for r in rows)
    assert corpus.scalar(select(func.count()).select_from(AskRequest)) == 2


def test_ask_not_configured_returns_503(corpus: Session) -> None:
    def override_session() -> Iterator[Session]:
        yield corpus

    app.dependency_overrides[get_session] = override_session
    try:
        # No OPENAI_EMBEDDING_MODEL in a clean environment -> the real dependency refuses.
        from app.api import ask as ask_module

        ask_module._build_services.cache_clear()
        settings = Settings(_env_file=None)
        original = ask_module.get_settings
        ask_module.get_settings = lambda: settings
        response = TestClient(app).post("/ask", json={"question": "Apple?"})
    finally:
        ask_module.get_settings = original
        ask_module._build_services.cache_clear()
        app.dependency_overrides.clear()
    assert response.status_code == 503
    # Names the missing setting so the operator knows what to add, without any secret.
    assert "OPENAI_EMBEDDING_MODEL is not set" in response.json()["detail"]


def test_post_is_only_allowed_on_ask(make_client) -> None:
    client, _ = make_client(GOOD_REPLY)
    for path in ("/runs", "/signals", "/signals/latest", "/stats/track-record", "/health"):
        assert client.post(path).status_code == 405
    preflight = client.options(
        "/ask",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert "POST" in preflight.headers["access-control-allow-methods"]
