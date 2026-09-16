import json
import re

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.chat import stream_agent_response

# Module-attribute import, not `from app.db.session import SessionLocal` /
# `get_session` — see app/db/session.py's get_engine() docstring, and the
# identical pattern in app/api/documents.py. Binding a bare name at this
# module's import time (which, for pytest, happens before the test-DB
# fixture reassigns `SessionLocal`) would silently pin every request in this
# router to whatever engine existed at import time. Going through the module
# (`db_session_module.get_session()`) instead resolves the current
# `SessionLocal` at call time, and lets tests `patch.object` it.
from app.db import session as db_session_module
from app.db.models import Chunk, Document, Message

router = APIRouter(prefix="/chat", tags=["chat"])

CITATION_PATTERN = re.compile(r"\[\[(\d+)\]\]")


class ChatRequest(BaseModel):
    message: str


def _resolve_citations(session, raw_text: str) -> tuple[str, list[dict]]:
    """Replace `[[chunk_id]]` markers with renumbered `[n]` references and
    build the citations list, in order of first appearance.

    Numbering starts at 1 and increments each time a *new* chunk_id is seen;
    a repeated marker for a chunk already cited reuses its existing number
    rather than allocating a new one. A marker whose chunk_id doesn't resolve
    to an existing chunk is dropped from the text entirely (no citation
    entry, no leftover bracket).
    """
    citations: list[dict] = []
    seen: dict[int, int] = {}

    def replace(match: re.Match) -> str:
        chunk_id = int(match.group(1))
        if chunk_id not in seen:
            chunk = session.get(Chunk, chunk_id)
            if chunk is None:
                return ""
            document = session.get(Document, chunk.document_id)
            number = len(seen) + 1
            seen[chunk_id] = number
            citations.append(
                {
                    "number": number,
                    "chunk_id": chunk_id,
                    "doc_type": document.doc_type if document else None,
                    "filename": document.filename if document else None,
                    "page_number": chunk.page_number,
                }
            )
        return f"[{seen[chunk_id]}]"

    cleaned_text = CITATION_PATTERN.sub(replace, raw_text)
    return cleaned_text, citations


@router.post("/message")
def post_chat_message(request: ChatRequest):
    # The session is created here, in the outer (non-generator) function body,
    # and deliberately NOT closed here. `stream_agent_response`'s tools
    # (`search_docs`, `reconcile_claim`) close over this `session` object but
    # only execute it lazily, during iteration of the generator below — which
    # happens after this function has already returned control to Starlette's
    # StreamingResponse machinery. Closing the session anywhere in this outer
    # function (or in a `finally` around the `return` statement) would close
    # it before those tool calls ever run. The session must stay open until
    # the generator itself is fully exhausted, so it is only closed inside
    # `event_stream`'s own `finally` block below.
    session = db_session_module.get_session()

    def event_stream():
        try:
            history = [
                {"role": m.role, "content": m.content}
                for m in session.query(Message).order_by(Message.id).all()
            ]
            session.add(Message(role="user", content=request.message))
            session.commit()

            raw_chunks = []
            for token in stream_agent_response(session, history, request.message):
                raw_chunks.append(token)
                yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"

            raw_text = "".join(raw_chunks)
            cleaned_text, citations = _resolve_citations(session, raw_text)

            session.add(Message(role="assistant", content=cleaned_text, citations=citations))
            session.commit()

            yield f"data: {json.dumps({'type': 'done', 'content': cleaned_text, 'citations': citations})}\n\n"
        finally:
            # Only closes once event_stream has been fully consumed by the
            # StreamingResponse — i.e. after stream_agent_response (and thus
            # every tool call that uses `session`) has actually run.
            session.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history")
def get_chat_history():
    session = db_session_module.get_session()
    try:
        messages = session.query(Message).order_by(Message.id).all()
        return [
            {"id": m.id, "role": m.role, "content": m.content, "citations": m.citations}
            for m in messages
        ]
    finally:
        session.close()
