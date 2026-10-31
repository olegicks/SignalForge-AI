"""Analyzer backed by OpenAI Structured Outputs (Responses API, parsed into Pydantic)."""

import logging
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from core.config import Settings
from pipeline.analyzer.base import Analyzer, AnalyzerError, LLMSignal, SignalResult
from pipeline.analyzer.prompts import SYSTEM_PROMPT, build_user_prompt
from pipeline.analyzer.validation import resolve_source_ids, validate_result
from pipeline.collectors.news import NewsArticle
from pipeline.collectors.prices import PriceMetrics

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 60


class OpenAIAnalyzer(Analyzer):
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        if not settings.openai_model:
            raise AnalyzerError("OPENAI_MODEL is not set")
        self._model = settings.openai_model
        self._max_output_tokens = settings.llm_max_output_tokens
        self._reasoning_effort = settings.openai_reasoning_effort
        if client is None:
            api_key = settings.openai_api_key.get_secret_value()
            if not api_key:
                raise AnalyzerError("OPENAI_API_KEY is not set")
            client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=2)
        self._client = client

    @property
    def model_name(self) -> str:
        return self._model

    def analyze(self, ticker: str, metrics: PriceMetrics, news: list[NewsArticle]) -> SignalResult:
        extra: dict[str, Any] = {}
        if self._reasoning_effort:
            extra["reasoning"] = {"effort": self._reasoning_effort}

        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=SYSTEM_PROMPT,
                input=build_user_prompt(ticker, metrics, news),
                text_format=LLMSignal,
                max_output_tokens=self._max_output_tokens,
                store=False,
                **extra,
            )
        except ValidationError as exc:
            # The SDK parses before returning; a reply cut off at the token cap lands here.
            raise AnalyzerError(
                f"Unparseable output for {ticker} (likely cut off at "
                f"LLM_MAX_OUTPUT_TOKENS={self._max_output_tokens}): {exc.errors()[0]['msg']}"
            ) from exc

        usage = response.usage
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
        parsed = response.output_parsed
        if parsed is None:
            reason = getattr(response.incomplete_details, "reason", None) or response.status
            raise AnalyzerError(
                f"No structured output for {ticker} (status={response.status}, reason={reason}, "
                f"output_tokens={output_tokens})"
            )

        result = SignalResult(
            **parsed.model_dump(exclude={"source_ids"}),
            sources=resolve_source_ids(parsed.source_ids, news),
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return validate_result(result, news)
