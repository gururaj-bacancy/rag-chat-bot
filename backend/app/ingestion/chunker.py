from dataclasses import dataclass
from app.ingestion.pdf_parser import TextBlock

@dataclass
class Chunk:
    text: str
    page_number: int

def _looks_like_heading(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    is_mostly_upper = sum(1 for c in letters if c.isupper()) / len(letters) > 0.9
    return is_mostly_upper and len(text) <= 60

def chunk_policy_blocks(blocks: list[TextBlock]) -> list[Chunk]:
    chunks: list[Chunk] = []
    current_lines: list[str] = []
    current_page: int | None = None

    def flush():
        if current_lines:
            chunks.append(Chunk(text="\n".join(current_lines), page_number=current_page or 1))

    for block in blocks:
        if _looks_like_heading(block.text) and current_lines:
            flush()
            current_lines = [block.text]
            current_page = block.page_number
        else:
            if current_page is None:
                current_page = block.page_number
            current_lines.append(block.text)
    flush()
    return chunks
