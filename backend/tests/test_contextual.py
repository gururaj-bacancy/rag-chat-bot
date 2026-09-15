import pytest
from unittest.mock import patch, MagicMock


def test_generate_contextual_text():
    """Test that generate_contextual_text calls client with correct params and returns blurb + chunk."""
    with patch("app.ingestion.contextual._client") as mock_client:
        # Setup mock response
        mock_response = MagicMock()
        mock_text_content = MagicMock()
        mock_text_content.type = "text"
        mock_text_content.text = "This chunk discusses the main concepts."
        mock_response.content = [mock_text_content]
        mock_client.messages.create.return_value = mock_response

        # Import and call
        from app.ingestion.contextual import generate_contextual_text

        chunk_text = "The concept of RAG is important for retrieval."
        document_summary = "This document explains RAG systems."
        result = generate_contextual_text(chunk_text, document_summary)

        # Assert client was called correctly
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args
        assert call_args.kwargs["model"] == "claude-haiku-4-5"
        assert call_args.kwargs["max_tokens"] == 200
        assert "user" in str(call_args)

        # Assert result contains the blurb followed by the chunk
        assert result.startswith("This chunk discusses the main concepts.")
        assert chunk_text in result
        # Verify the format: blurb\n\nchunk_text
        assert "\n\n" in result
        parts = result.split("\n\n", 1)
        assert parts[0] == "This chunk discusses the main concepts."
        assert parts[1] == chunk_text
