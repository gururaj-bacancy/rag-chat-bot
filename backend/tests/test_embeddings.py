import pytest
from unittest.mock import patch, MagicMock


def test_embed_documents():
    """Test that embed_documents calls client with correct params and returns embeddings."""
    with patch("app.ingestion.embeddings._client") as mock_client:
        # Setup mock response
        mock_result = MagicMock()
        mock_result.embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.embed.return_value = mock_result

        # Import and call
        from app.ingestion.embeddings import embed_documents

        texts = ["a", "b"]
        result = embed_documents(texts)

        # Assert client was called correctly
        mock_client.embed.assert_called_once_with(
            ["a", "b"], model="voyage-4-large", input_type="document"
        )

        # Assert result is the embeddings list
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_embed_query():
    """Test that embed_query calls client with correct params and returns first embedding."""
    with patch("app.ingestion.embeddings._client") as mock_client:
        # Setup mock response
        mock_result = MagicMock()
        mock_result.embeddings = [[0.7, 0.8, 0.9]]
        mock_client.embed.return_value = mock_result

        # Import and call
        from app.ingestion.embeddings import embed_query

        query_text = "q"
        result = embed_query(query_text)

        # Assert client was called correctly
        mock_client.embed.assert_called_once_with(
            ["q"], model="voyage-4-large", input_type="query"
        )

        # Assert result is the first embedding from the list
        assert result == [0.7, 0.8, 0.9]
