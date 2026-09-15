import anthropic
from app.config import settings

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

CONTEXTUAL_PROMPT = """Here is a document summary:
<document_summary>
{document_summary}
</document_summary>

Here is a chunk from that document:
<chunk>
{chunk_text}
</chunk>

Write a short (1-2 sentence) blurb that situates this chunk within the \
overall document, so it can be understood on its own. Answer with only \
the blurb, no preamble."""

def generate_contextual_text(chunk_text: str, document_summary: str) -> str:
    response = _client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": CONTEXTUAL_PROMPT.format(
                document_summary=document_summary, chunk_text=chunk_text
            ),
        }],
    )
    blurb = next(b.text for b in response.content if b.type == "text").strip()
    return f"{blurb}\n\n{chunk_text}"
