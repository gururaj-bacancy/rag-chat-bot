import json
import re

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

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
from app.db.models import Chunk, Conversation, Document, Message

router = APIRouter(prefix="/chat", tags=["chat"])

CITATION_PATTERN = re.compile(r"\[\[(\d+)\]\]")


class ChatRequest(BaseModel):
    message: str
    conversation_id: int


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
                for m in session.query(Message)
                .filter(Message.conversation_id == request.conversation_id)
                .order_by(Message.id)
                .all()
            ]
            session.add(
                Message(
                    role="user",
                    content=request.message,
                    conversation_id=request.conversation_id,
                )
            )
            session.commit()

            raw_chunks = []
            try:
                for token in stream_agent_response(session, history, request.message):
                    raw_chunks.append(token)
                    yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"
            except Exception as exc:  # noqa: BLE001 - surfaced to the client below
                # The stream died mid-flight (API error, network failure, tool
                # blow-up). Terminate the SSE contract with an explicit `error`
                # event instead of just closing the connection, which would
                # leave the UI with a permanently empty assistant bubble and no
                # explanation. Deliberately no assistant Message row: a
                # truncated or empty answer is not something to replay as
                # history on the next page load. The user's own message stays
                # persisted — they did ask it. Rolling back first discards any
                # partial writes a failing tool may have staged on this session.
                session.rollback()
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
                return

            raw_text = "".join(raw_chunks)
            cleaned_text, citations = _resolve_citations(session, raw_text)

            session.add(
                Message(
                    role="assistant",
                    content=cleaned_text,
                    citations=citations,
                    conversation_id=request.conversation_id,
                )
            )
            session.commit()

            yield f"data: {json.dumps({'type': 'done', 'content': cleaned_text, 'citations': citations})}\n\n"
        finally:
            # Only closes once event_stream has been fully consumed by the
            # StreamingResponse — i.e. after stream_agent_response (and thus
            # every tool call that uses `session`) has actually run.
            session.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history")
def get_chat_history(conversation_id: int):
    session = db_session_module.get_session()
    try:
        messages = (
            session.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.id)
            .all()
        )
        return [
            {"id": m.id, "role": m.role, "content": m.content, "citations": m.citations}
            for m in messages
        ]
    finally:
        session.close()


@router.get("/conversations")
def list_conversations():
    # Raw SQL (not the ORM query builder) for the same reason as
    # app/retrieval/hybrid_search.py: a LATERAL join to pull just the
    # earliest message per conversation isn't expressible as a plain
    # SQLAlchemy ORM query. `conversation_id` and `content` are static
    # column names, not user input, so this is not a f-string/injection
    # concern.
    session = db_session_module.get_session()
    try:
        rows = session.execute(
            text(
                "SELECT c.id, c.created_at, "
                "COALESCE(LEFT(first_msg.content, 50), 'New conversation') AS title "
                "FROM conversations c "
                "LEFT JOIN LATERAL ("
                "    SELECT content FROM messages "
                "    WHERE messages.conversation_id = c.id "
                "    ORDER BY id ASC LIMIT 1"
                ") first_msg ON true "
                "ORDER BY c.created_at DESC, c.id DESC"
            )
        ).fetchall()
        return [{"id": row.id, "title": row.title, "created_at": row.created_at} for row in rows]
    finally:
        session.close()


@router.post("/conversations", status_code=201)
def create_conversation():
    session = db_session_module.get_session()
    try:
        conversation = Conversation()
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return {
            "id": conversation.id,
            "created_at": conversation.created_at,
            "title": "New conversation",
        }
    finally:
        session.close()
