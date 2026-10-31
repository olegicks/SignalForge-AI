from core.config import Settings
from pipeline.analyzer.base import Analyzer, AnalyzerError, SignalResult


def get_analyzer(settings: Settings) -> Analyzer:
    """Pick the analyzer from ANALYZER_PROVIDER. Add new providers here."""
    if settings.analyzer_provider == "openai":
        from pipeline.analyzer.openai_analyzer import OpenAIAnalyzer

        return OpenAIAnalyzer(settings)
    raise AnalyzerError(f"Unknown ANALYZER_PROVIDER: {settings.analyzer_provider!r}")


__all__ = ["Analyzer", "AnalyzerError", "SignalResult", "get_analyzer"]
