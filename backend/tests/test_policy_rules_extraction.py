from unittest.mock import MagicMock, patch

from app.ingestion.extraction import PolicyRuleExtraction


def test_extract_policy_rules():
    """extract_policy_rules should return the mocked parsed_output exactly,
    calling the right model and output_format."""
    policy_fixture = PolicyRuleExtraction(
        sum_insured=500000.0,
        room_rent_limit_per_day=5000.0,
        room_rent_limit_type="fixed_amount",
        co_pay_percentage=10.0,
        sub_limits={"cataract": 40000.0, "knee_replacement": 150000.0},
    )

    with patch("app.ingestion.extraction._client") as mock_client:
        mock_client.messages.parse.return_value = MagicMock(
            parsed_output=policy_fixture
        )

        from app.ingestion.extraction import extract_policy_rules

        text = "Sample mediclaim policy document text with sum insured and limits."
        result = extract_policy_rules(text)

        assert result is policy_fixture

        mock_client.messages.parse.assert_called_once()
        call_kwargs = mock_client.messages.parse.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5"
        assert call_kwargs["output_format"] is PolicyRuleExtraction
        assert call_kwargs["max_tokens"] == 4096
        assert text in call_kwargs["messages"][0]["content"]
        assert call_kwargs["messages"][0]["role"] == "user"
