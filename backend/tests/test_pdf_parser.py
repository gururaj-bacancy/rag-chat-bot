import pytest
import fitz
from app.ingestion.pdf_parser import parse_pdf, TextBlock


@pytest.fixture
def sample_pdf_path(tmp_path):
    """Create a 2-page PDF with text for testing."""
    pdf_path = tmp_path / "sample.pdf"

    # Create a new PDF document
    doc = fitz.open()

    # Page 1: add some text
    page1 = doc.new_page()
    page1.insert_text((72, 72), "This is page 1 text.")
    page1.insert_text((72, 120), "Second line on page 1.")

    # Page 2: add different text
    page2 = doc.new_page()
    page2.insert_text((72, 72), "This is page 2 text.")
    page2.insert_text((72, 120), "Another line on page 2.")

    # Save the PDF
    doc.save(str(pdf_path))
    doc.close()

    return str(pdf_path)


def test_parse_pdf_extracts_text_with_page_numbers(sample_pdf_path):
    """Test that parse_pdf extracts text blocks with correct 1-indexed page numbers."""
    blocks = parse_pdf(sample_pdf_path)

    # Should have 4 text blocks (2 per page)
    assert len(blocks) == 4

    # Check all blocks are TextBlock instances
    assert all(isinstance(block, TextBlock) for block in blocks)

    # Check page 1 text blocks (1-indexed)
    page1_blocks = [b for b in blocks if b.page_number == 1]
    assert len(page1_blocks) == 2
    assert "This is page 1 text." in page1_blocks[0].text
    assert "Second line on page 1." in page1_blocks[1].text

    # Check page 2 text blocks (1-indexed)
    page2_blocks = [b for b in blocks if b.page_number == 2]
    assert len(page2_blocks) == 2
    assert "This is page 2 text." in page2_blocks[0].text
    assert "Another line on page 2." in page2_blocks[1].text
