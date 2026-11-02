"""OpenAI embeddings client, shared by the pipeline's embed step and the /ask endpoint."""

from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI

from core.config import Settings

REQUEST_TIMEOUT_SECONDS = 60


class EmbeddingError(RuntimeError):
    pass


@dataclass
class EmbeddingBatch:
    vectors: list[list[float]]
    tokens: int


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed(self, texts: list[str]) -> EmbeddingBatch: ...


class OpenAIEmbedder:
    def __init__(self, settings: Settings, client: OpenAI | None = None) -> None:
        if not settings.openai_embedding_model:
            raise EmbeddingError("OPENAI_EMBEDDING_MODEL is not set")
        self.model_name = settings.openai_embedding_model
        self.dim = settings.embedding_dim
        if client is None:
            api_key = settings.openai_api_key.get_secret_value()
            if not api_key:
                raise EmbeddingError("OPENAI_API_KEY is not set")
            client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=2)
        self._client = client

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        if not texts:
            return EmbeddingBatch(vectors=[], tokens=0)
        response = self._client.embeddings.create(
            model=self.model_name, input=texts, dimensions=self.dim
        )
        # The API may return items out of order; `index` ties each back to its input.
        vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        if len(vectors) != len(texts) or any(len(v) != self.dim for v in vectors):
            raise EmbeddingError(f"unexpected embedding shape from {self.model_name}")
        tokens = response.usage.total_tokens if response.usage else 0
        return EmbeddingBatch(vectors=vectors, tokens=tokens)
