"""Tests for the synthetic sample data generator (Task 20).

Generates 3 PDFs (bill, policy, settlement) and verifies -- by parsing them
back with the real PDF parser (Task 3) -- that the exact reference
reconciliation numbers used throughout the plan are present as text,
including the deliberately wrong settlement approval amount (Rs 70,000)
that Task 21's end-to-end test relies on to prove the reconciliation
engine catches the discrepancy.
"""
import fitz
import pytest

from app.ingestion.pdf_parser import parse_pdf
from scripts.generate_sample_data import generate_sample_documents


@pytest.fixture
def generated_paths(tmp_path):
    return generate_sample_documents(str(tmp_path / "generated"))


def _full_text(path: str) -> str:
    return "\n".join(block.text for block in parse_pdf(path))


def test_returns_expected_keys(generated_paths):
    assert generated_paths.keys() == {"bill", "policy", "settlement"}


def test_all_files_exist_with_at_least_one_page(generated_paths):
    for path in generated_paths.values():
        doc = fitz.open(path)
        try:
            assert doc.page_count >= 1
        finally:
            doc.close()


def test_bill_pdf_contains_room_rent_and_total(generated_paths):
    text = _full_text(generated_paths["bill"])
    assert "40,000" in text or "40000" in text
    assert "1,20,000" in text or "120,000" in text or "120000" in text


def test_policy_pdf_contains_room_rent_limit_and_copay(generated_paths):
    text = _full_text(generated_paths["policy"])
    assert "5,000" in text or "5000" in text
    assert "10%" in text


def test_settlement_pdf_contains_wrong_approved_amount(generated_paths):
    text = _full_text(generated_paths["settlement"])
    assert "70,000" in text or "70000" in text
