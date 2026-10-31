from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.config import Settings
from pipeline.analyzer import AnalyzerError, get_analyzer
from pipeline.analyzer.base import LLMSignal
from pipeline.analyzer.openai_analyzer import OpenAIAnalyzer
from pipeline.analyzer.prompts import build_user_prompt, truncate
from pipeline.analyzer.validation import validate_result
from tests.factories import make_article, make_metrics, make_result


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"openai_model": "test-model", "openai_api_key": "sk-test"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def fake_response(parsed: LLMSignal | None, status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        output_parsed=parsed,
        usage=SimpleNamespace(input_tokens=812, output_tokens=95),
        status=status,
        incomplete_details=SimpleNamespace(reason="max_output_tokens") if parsed is None else None,
    )


def llm_signal(**overrides: object) -> LLMSignal:
    values: dict[str, object] = {
        "signal": "bullish",
        "score": 14,
        "risk": "low",
        "confidence": 1.7,
        "reasoning": "  Good news.  ",
        "key_factors": ["a", " ", "b", "c", "d", "e"],
        "sources": [
            "https://news.example.com/1",
            "https://made-up.example.org/x",
            "https://news.example.com/1",
        ],
    }
    values.update(overrides)
    return LLMSignal(**values)


# --- validation -------------------------------------------------------------


def test_validate_drops_unknown_sources_and_duplicates() -> None:
    news = [make_article(1), make_article(2)]
    result = make_result(
        sources=[
            "https://news.example.com/2",
            "https://evil.example/x",
            "https://news.example.com/2",
        ]
    )
    assert validate_result(result, news).sources == ["https://news.example.com/2"]


@pytest.mark.parametrize(
    ("score", "confidence", "expected_score", "expected_confidence"),
    [(0, -0.5, 1, 0.0), (11, 1.5, 10, 1.0), (6, 0.42, 6, 0.42)],
)
def test_validate_clamps_values(
    score: int, confidence: float, expected_score: int, expected_confidence: float
) -> None:
    result = validate_result(make_result(score=score, confidence=confidence), [])
    assert result.score == expected_score
    assert result.confidence == expected_confidence


def test_validate_trims_key_factors() -> None:
    result = validate_result(make_result(key_factors=["a", "", " b ", "c", "d", "e"]), [])
    assert result.key_factors == ["a", "b", "c", "d"]


# --- prompt -----------------------------------------------------------------


def test_prompt_contains_data_and_truncated_summaries() -> None:
    long_summary = "word " * 200
    prompt = build_user_prompt("AAPL", make_metrics(), [make_article(1, summary=long_summary)])
    assert "Ticker: AAPL" in prompt
    assert "last close 100.00" in prompt
    assert "30d n/a" in prompt
    assert "https://news.example.com/1" in prompt
    summary_line = next(line for line in prompt.splitlines() if "Summary:" in line)
    assert len(summary_line) < 320


def test_truncate_short_text_unchanged() -> None:
    assert truncate("  hello   world ") == "hello world"


# --- OpenAI analyzer (mocked client) ----------------------------------------


def test_openai_analyzer_parses_and_validates() -> None:
    client = MagicMock()
    client.responses.parse.return_value = fake_response(llm_signal())
    analyzer = OpenAIAnalyzer(settings(llm_max_output_tokens=321), client=client)

    news = [make_article(1)]
    result = analyzer.analyze("AAPL", make_metrics(), news)

    assert result.score == 10
    assert result.confidence == 1.0
    assert result.sources == ["https://news.example.com/1"]
    assert result.key_factors == ["a", "b", "c", "d"]
    assert result.reasoning == "Good news."
    assert (result.input_tokens, result.output_tokens) == (812, 95)
    assert result.model == "test-model"

    kwargs = client.responses.parse.call_args.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["text_format"] is LLMSignal
    assert kwargs["max_output_tokens"] == 321
    assert "reasoning" not in kwargs


def test_openai_analyzer_passes_reasoning_effort_when_set() -> None:
    client = MagicMock()
    client.responses.parse.return_value = fake_response(llm_signal())
    analyzer = OpenAIAnalyzer(settings(openai_reasoning_effort="minimal"), client=client)
    analyzer.analyze("AAPL", make_metrics(), [make_article(1)])
    assert client.responses.parse.call_args.kwargs["reasoning"] == {"effort": "minimal"}


def test_openai_analyzer_raises_on_missing_output() -> None:
    client = MagicMock()
    client.responses.parse.return_value = fake_response(None, status="incomplete")
    analyzer = OpenAIAnalyzer(settings(), client=client)
    with pytest.raises(AnalyzerError, match="max_output_tokens"):
        analyzer.analyze("AAPL", make_metrics(), [make_article(1)])


def test_openai_analyzer_requires_model() -> None:
    with pytest.raises(AnalyzerError, match="OPENAI_MODEL"):
        OpenAIAnalyzer(settings(openai_model=""), client=MagicMock())


def test_get_analyzer_rejects_unknown_provider() -> None:
    with pytest.raises(AnalyzerError, match="grok"):
        get_analyzer(settings(analyzer_provider="grok"))


def test_get_analyzer_builds_openai_without_network() -> None:
    assert isinstance(get_analyzer(settings()), OpenAIAnalyzer)
