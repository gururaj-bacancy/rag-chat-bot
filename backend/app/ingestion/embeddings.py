import voyageai
from app.config import settings

EMBEDDING_MODEL = "voyage-4-large"

# Initialize client lazily to handle empty API key at import time
_client = None


def _get_client():
    """Lazily initialize and return the voyageai client."""
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=settings.voyage_api_key)
    return _client


def embed_documents(texts: list[str]) -> list[list[float]]:
    result = _get_client().embed(texts, model=EMBEDDING_MODEL, input_type="document")
    return result.embeddings


def embed_query(text: str) -> list[float]:
    result = _get_client().embed([text], model=EMBEDDING_MODEL, input_type="query")
    return result.embeddings[0]
