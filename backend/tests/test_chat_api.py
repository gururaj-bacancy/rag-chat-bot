import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import session as db_session_module
from app.db.models import Chunk, Conversation, Document, Message
from app.main import app


@pytest.fixture
def client(db_session):
    """A TestClient whose routes resolve their DB session to the exact same
    `db_session` fixture object, per Task 10's pattern (see
    test_documents_api.py / conftest.py). This patches the session-factory
    lookup (`db_session_module.get_session`), not a bare `SessionLocal`
    import, so it can't go stale relative to `session.py`'s guidance.
    """
    with patch.object(db_session_module, "get_session", return_value=db_session):
        yield TestClient(app)


def _seed_conversation(db_session):
    conversation = Conversation()
    db_session.add(conversation)
    db_session.commit()
    return conversation


def _seed_chunk(db_session):
    document = Document(doc_type="policy", filename="policy.pdf", status="indexed")
    db_session.add(document)
    db_session.commit()

    chunk = Chunk(
        document_id=document.id,
        chunk_text="Room rent is capped at 1% of sum insured per day.",
        contextual_text="This chunk describes the room rent sub-limit clause.",
        page_number=4,
    )
    db_session.add(chunk)
    db_session.commit()
    return document, chunk


def _consume_sse(response):
    events = []
    for line in response.iter_lines():
        if not line:
            continue
        assert line.startswith("data: ")
        events.append(json.loads(line[len("data: ") :]))
    return events


def test_post_chat_message_resolves_citations_and_persists(client, db_session):
    document, chunk = _seed_chunk(db_session)
    raw_tokens = ["The room rent limit is capped. ", f"[[{chunk.id}]]", " That's the clause."]

    def fake_stream(session, history, user_message):
        assert session is db_session
        assert history == []
        assert user_message == "Is the room rent capped?"
        yield from raw_tokens

    with patch("app.api.chat.stream_agent_response", side_effect=fake_stream) as mock_stream:
        with client.stream(
            "POST", "/chat/message", json={"message": "Is the room rent capped?"}
        ) as response:
            assert response.status_code == 200
            events = _consume_sse(response)

    mock_stream.assert_called_once()

    token_events = [e for e in events if e["type"] == "token"]
    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    done = done_events[0]

    # Tokens are streamed verbatim (pre-citation-cleanup) as they arrive.
    assert [e["text"] for e in token_events] == raw_tokens

    # The done event has the [[chunk_id]] marker replaced with a renumbered [1].
    assert "[[" not in done["content"]
    assert done["content"] == "The room rent limit is capped. [1] That's the clause."

    expected_citations = [
        {
            "number": 1,
            "chunk_id": chunk.id,
            "doc_type": "policy",
            "filename": "policy.pdf",
            "page_number": 4,
        }
    ]
    assert done["citations"] == expected_citations

    # Two messages persisted: user then assistant, in order.
    messages = db_session.query(Message).order_by(Message.id).all()
    assert len(messages) == 2
    user_msg, assistant_msg = messages
    assert user_msg.role == "user"
    assert user_msg.content == "Is the room rent capped?"
    assert user_msg.citations is None
    assert assistant_msg.role == "assistant"
    assert assistant_msg.content == done["content"]
    assert assistant_msg.citations == done["citations"]


def test_second_message_includes_prior_turns_as_history(client, db_session):
    conversation = _seed_conversation(db_session)
    db_session.add_all(
        [
            Message(role="user", content="first question", conversation_id=conversation.id),
            Message(
                role="assistant",
                content="first answer",
                citations=[],
                conversation_id=conversation.id,
            ),
        ]
    )
    db_session.commit()

    def fake_stream(session, history, user_message):
        assert history == [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]
        assert user_message == "second question"
        yield "second answer"

    with patch("app.api.chat.stream_agent_response", side_effect=fake_stream):
        with client.stream(
            "POST", "/chat/message", json={"message": "second question"}
        ) as response:
            events = _consume_sse(response)

    done = [e for e in events if e["type"] == "done"][0]
    assert done["content"] == "second answer"
    assert done["citations"] == []

    messages = db_session.query(Message).order_by(Message.id).all()
    assert len(messages) == 4


def test_citation_numbering_starts_at_one_and_dedupes_repeats(client, db_session):
    _, chunk_a = _seed_chunk(db_session)
    document_b = Document(doc_type="bill", filename="bill.pdf", status="indexed")
    db_session.add(document_b)
    db_session.commit()
    chunk_b = Chunk(
        document_id=document_b.id,
        chunk_text="Second chunk text.",
        contextual_text="Second chunk contextual text.",
        page_number=2,
    )
    db_session.add(chunk_b)
    db_session.commit()

    def fake_stream(session, history, user_message):
        yield f"First [[{chunk_b.id}]] then repeat [[{chunk_a.id}]] "
        yield f"and repeat first again [[{chunk_b.id}]]."

    with patch("app.api.chat.stream_agent_response", side_effect=fake_stream):
        with client.stream(
            "POST", "/chat/message", json={"message": "q"}
        ) as response:
            events = _consume_sse(response)

    done = [e for e in events if e["type"] == "done"][0]
    # chunk_b appears first -> numbered [1]; chunk_a appears second -> [2];
    # the repeat of chunk_b reuses [1] rather than allocating a new number.
    assert done["content"] == "First [1] then repeat [2] and repeat first again [1]."
    assert done["citations"] == [
        {
            "number": 1,
            "chunk_id": chunk_b.id,
            "doc_type": "bill",
            "filename": "bill.pdf",
            "page_number": 2,
        },
        {
            "number": 2,
            "chunk_id": chunk_a.id,
            "doc_type": "policy",
            "filename": "policy.pdf",
            "page_number": 4,
        },
    ]


def test_unresolvable_citation_marker_is_dropped(client, db_session):
    def fake_stream(session, history, user_message):
        yield "Some answer "
        yield "[[999999]]"
        yield " with an unresolved citation."

    with patch("app.api.chat.stream_agent_response", side_effect=fake_stream):
        with client.stream(
            "POST", "/chat/message", json={"message": "test"}
        ) as response:
            events = _consume_sse(response)

    done = [e for e in events if e["type"] == "done"][0]
    assert "[[" not in done["content"]
    assert done["content"] == "Some answer  with an unresolved citation."
    assert done["citations"] == []


def test_get_chat_history_returns_persisted_messages_in_order(client, db_session):
    conversation = _seed_conversation(db_session)
    db_session.add_all(
        [
            Message(role="user", content="hello", conversation_id=conversation.id),
            Message(
                role="assistant",
                content="hi there",
                citations=[],
                conversation_id=conversation.id,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/chat/history")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["role"] == "user"
    assert body[0]["content"] == "hello"
    assert body[0]["citations"] is None
    assert body[1]["role"] == "assistant"
    assert body[1]["content"] == "hi there"
    assert body[1]["citations"] == []


def test_stream_failure_emits_error_event_and_persists_only_the_user_message(client, db_session):
    """If the agent stream dies mid-flight, the SSE contract must terminate
    with an explicit `error` event rather than silently closing — otherwise the
    UI is left with an empty assistant bubble and no explanation. The user's
    own message stays persisted (they did ask it); no assistant row is written
    for the broken answer."""

    def failing_stream(session, history, user_message):
        yield "Let me check your policy"
        raise RuntimeError("upstream API error: connection reset")

    with patch("app.api.chat.stream_agent_response", side_effect=failing_stream):
        with client.stream(
            "POST", "/chat/message", json={"message": "Why was my claim reduced?"}
        ) as response:
            assert response.status_code == 200
            events = _consume_sse(response)

    # Tokens streamed before the failure are still delivered, then exactly one
    # terminal error event — and no `done`.
    assert [e["text"] for e in events if e["type"] == "token"] == ["Let me check your policy"]
    assert [e["type"] for e in events if e["type"] == "done"] == []
    error_events = [e for e in events if e["type"] == "error"]
    assert len(error_events) == 1
    assert events[-1]["type"] == "error"
    assert "upstream API error: connection reset" in error_events[0]["message"]

    messages = db_session.query(Message).order_by(Message.id).all()
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Why was my claim reduced?"


def test_stream_failure_before_any_token_still_emits_error_event(client, db_session):
    """The failure can also happen before a single token arrives (e.g. the very
    first API call is rejected); the stream must still be a well-formed SSE
    response ending in an error event, not an empty body."""

    def failing_stream(session, history, user_message):
        raise RuntimeError("rate limited")
        yield  # pragma: no cover - makes this a generator function

    with patch("app.api.chat.stream_agent_response", side_effect=failing_stream):
        with client.stream("POST", "/chat/message", json={"message": "hi"}) as response:
            assert response.status_code == 200
            events = _consume_sse(response)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "rate limited" in events[0]["message"]

    messages = db_session.query(Message).order_by(Message.id).all()
    assert [m.role for m in messages] == ["user"]
