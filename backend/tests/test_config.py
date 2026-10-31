import pytest
import yaml

from core.config import Settings


def make_settings(**overrides: object) -> Settings:
    # _env_file=None keeps a developer's local .env out of the tests.
    return Settings(_env_file=None, **overrides)


def test_defaults_match_env_example() -> None:
    settings = make_settings()
    assert settings.max_news_per_ticker == 8
    assert settings.news_lookback_hours == 48
    assert settings.max_tickers_per_run == 30
    assert settings.llm_max_output_tokens == 400
    assert settings.analyzer_provider == "openai"


def test_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "some-model")
    monkeypatch.setenv("MAX_NEWS_PER_TICKER", "3")
    settings = make_settings()
    assert settings.openai_model == "some-model"
    assert settings.max_news_per_ticker == 3


def test_api_key_is_hidden_in_repr() -> None:
    settings = make_settings(openai_api_key="sk-secret-value")
    assert "sk-secret-value" not in repr(settings)
    assert settings.openai_api_key.get_secret_value() == "sk-secret-value"


def test_cors_origin_list_splits_and_strips() -> None:
    settings = make_settings(cors_origins="http://localhost:5173, https://example.vercel.app,")
    assert settings.cors_origin_list == ["http://localhost:5173", "https://example.vercel.app"]


def test_estimate_cost_usd() -> None:
    settings = make_settings(openai_price_input_per_1m=0.5, openai_price_output_per_1m=2.0)
    assert settings.estimate_cost_usd(1_000_000, 500_000) == pytest.approx(1.5)
    assert settings.estimate_cost_usd(0, 0) == 0


def test_watchlist_file_is_valid() -> None:
    data = yaml.safe_load(make_settings().watchlist_path.read_text(encoding="utf-8"))
    entries = data["tickers"]
    tickers = [entry["ticker"] for entry in entries]
    assert 20 <= len(entries) <= 30
    assert len(tickers) == len(set(tickers))
    for entry in entries:
        assert entry["ticker"] and entry["name"] and entry["query"]
