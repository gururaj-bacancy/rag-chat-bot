from unittest.mock import MagicMock, patch

from app.ingestion.extraction import (
    BillExtraction,
    LineItemExtraction,
    SettlementExtraction,
    SettlementLineItemExtraction,
)


def test_extract_bill():
    """extract_bill should return the mocked parsed_output exactly, calling the
    right model and output_format."""
    bill_fixture = BillExtraction(
        line_items=[
            LineItemExtraction(
                description="Room rent (Deluxe) x 3 days",
                category="room_rent",
                amount=15000.0,
            ),
            LineItemExtraction(
                description="Operation theatre charges",
                category="ot_charges",
                amount=25000.0,
            ),
        ],
        room_category="Deluxe",
        room_rent_per_day=5000.0,
    )

    with patch("app.ingestion.extraction._client") as mock_client:
        mock_client.messages.parse.return_value = MagicMock(parsed_output=bill_fixture)

        from app.ingestion.extraction import extract_bill

        text = "Sample hospital bill text with room rent and OT charges."
        result = extract_bill(text)

        assert result is bill_fixture

        mock_client.messages.parse.assert_called_once()
        call_kwargs = mock_client.messages.parse.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5"
        assert call_kwargs["output_format"] is BillExtraction
        assert call_kwargs["max_tokens"] == 4096
        assert text in call_kwargs["messages"][0]["content"]
        assert call_kwargs["messages"][0]["role"] == "user"


def test_extract_settlement():
    """extract_settlement should return the mocked parsed_output exactly, calling
    the right model and output_format."""
    settlement_fixture = SettlementExtraction(
        line_items=[
            SettlementLineItemExtraction(
                description="Room rent",
                claimed_amount=15000.0,
                approved_amount=12000.0,
                deducted_amount=3000.0,
                deduction_reason="Room rent capping as per policy",
            ),
            SettlementLineItemExtraction(
                description="Medicines",
                claimed_amount=5000.0,
                approved_amount=5000.0,
                deducted_amount=0.0,
                deduction_reason=None,
            ),
        ],
        total_claimed=20000.0,
        total_approved=17000.0,
        total_deducted=3000.0,
    )

    with patch("app.ingestion.extraction._client") as mock_client:
        mock_client.messages.parse.return_value = MagicMock(
            parsed_output=settlement_fixture
        )

        from app.ingestion.extraction import extract_settlement

        text = "Sample insurance settlement letter text."
        result = extract_settlement(text)

        assert result is settlement_fixture

        mock_client.messages.parse.assert_called_once()
        call_kwargs = mock_client.messages.parse.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5"
        assert call_kwargs["output_format"] is SettlementExtraction
        assert call_kwargs["max_tokens"] == 4096
        assert text in call_kwargs["messages"][0]["content"]
        assert call_kwargs["messages"][0]["role"] == "user"
