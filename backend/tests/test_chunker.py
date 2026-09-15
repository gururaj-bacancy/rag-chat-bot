import pytest
from app.ingestion.pdf_parser import TextBlock
from app.ingestion.chunker import chunk_policy_blocks, _looks_like_heading, Chunk


def test_chunk_policy_blocks_splits_on_headings():
    """Test that heading-delimited blocks produce the right chunk boundaries."""
    blocks = [
        TextBlock(text="ROOM RENT AND ICU CHARGES", page_number=1),
        TextBlock(text="The company will pay up to Rs. 5,000 per day.", page_number=1),
        TextBlock(text="Additional coverage for special procedures.", page_number=1),
        TextBlock(text="SURGERY AND ANESTHESIA", page_number=2),
        TextBlock(text="Covered expenses include operation theater charges.", page_number=2),
        TextBlock(text="Anesthesia costs up to Rs. 10,000.", page_number=2),
    ]

    chunks = chunk_policy_blocks(blocks)

    # Should have exactly 2 chunks
    assert len(chunks) == 2

    # First chunk should contain the first heading and its body text
    assert chunks[0].text == (
        "ROOM RENT AND ICU CHARGES\n"
        "The company will pay up to Rs. 5,000 per day.\n"
        "Additional coverage for special procedures."
    )
    assert chunks[0].page_number == 1

    # Second chunk should contain the second heading and its body text
    assert chunks[1].text == (
        "SURGERY AND ANESTHESIA\n"
        "Covered expenses include operation theater charges.\n"
        "Anesthesia costs up to Rs. 10,000."
    )
    assert chunks[1].page_number == 2


def test_looks_like_heading():
    """Test that _looks_like_heading correctly identifies headings."""
    # Should return True for heading-like text (short, mostly uppercase)
    assert _looks_like_heading("ROOM RENT AND ICU CHARGES") is True

    # Should return False for regular body text
    assert _looks_like_heading("The company will pay up to Rs. 5,000 per day.") is False
