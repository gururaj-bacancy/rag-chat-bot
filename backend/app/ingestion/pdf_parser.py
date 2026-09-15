from dataclasses import dataclass
import fitz  # PyMuPDF's import name is "fitz"

@dataclass
class TextBlock:
    text: str
    page_number: int

def parse_pdf(path: str) -> list[TextBlock]:
    """Extract text blocks from a PDF, preserving 1-indexed page numbers."""
    blocks: list[TextBlock] = []
    doc = fitz.open(path)
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            for raw in page.get_text("blocks"):
                text = raw[4].strip()
                if text:
                    blocks.append(TextBlock(text=text, page_number=page_index + 1))
    finally:
        doc.close()
    return blocks
