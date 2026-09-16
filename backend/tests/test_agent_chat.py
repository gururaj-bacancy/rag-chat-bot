from unittest.mock import patch

from app.agent.chat import SYSTEM_PROMPT, stream_agent_response

# NOTE on the fake runner's shape: with `stream=True`, the real
# `client.beta.messages.tool_runner(...)` returns an
# `anthropic.lib.tools._beta_runner.BetaStreamingToolRunner`. Iterating it
# yields one `anthropic.lib.streaming._beta_messages.BetaMessageStream` per
# API round trip (the runner executes the tool calls between round trips
# itself), and each of those exposes a `text_stream` *instance* attribute —
# assigned in `BetaMessageStream.__init__` as `self.text_stream =
# self.__stream_text__()`, a generator over `content_block_delta` /
# `text_delta` events. `FakeStream`/`FakeRunner` below mimic exactly that
# shape: an iterable of objects each carrying an iterable `.text_stream`.


class FakeStream:
    def __init__(self, chunks):
        self.text_stream = iter(chunks)


class FakeRunner:
    """Mimics BetaStreamingToolRunner: iterating yields one stream per round
    trip. Lazily constructs each FakeStream so the test can observe that
    consumption is incremental rather than pre-materialised."""

    def __init__(self, chunk_groups):
        self._chunk_groups = chunk_groups
        self.streams_started = 0

    def __iter__(self):
        for chunks in self._chunk_groups:
            self.streams_started += 1
            yield FakeStream(chunks)


def test_stream_agent_response_concatenates_chunks_across_round_trips(db_session):
    # Two "streams" = two round trips in one turn: text before a tool call,
    # then the grounded answer after the tool result came back.
    fake_runner = FakeRunner([
        ["Let me ", "check your ", "policy."],
        ["Room rent is capped at ", "Rs 5,000/day ", "[[42]]."],
    ])

    with patch("app.agent.chat._client") as mock_client:
        mock_client.beta.messages.tool_runner.return_value = fake_runner
        tokens = list(stream_agent_response(db_session, [], "Why was my claim reduced?"))

    assert tokens == [
        "Let me ", "check your ", "policy.",
        "Room rent is capped at ", "Rs 5,000/day ", "[[42]].",
    ]
    assert "".join(tokens) == (
        "Let me check your policy."
        "Room rent is capped at Rs 5,000/day [[42]]."
    )


def test_stream_agent_response_passes_expected_tool_runner_params(db_session):
    with patch("app.agent.chat._client") as mock_client:
        mock_client.beta.messages.tool_runner.return_value = FakeRunner([["ok"]])
        list(stream_agent_response(db_session, [], "Why was my claim reduced?"))

    mock_client.beta.messages.tool_runner.assert_called_once()
    kwargs = mock_client.beta.messages.tool_runner.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["stream"] is True
    assert len(kwargs["tools"]) == 2
    assert kwargs["system"] == SYSTEM_PROMPT
    assert kwargs["max_tokens"] == 8192


def test_stream_agent_response_appends_user_message_to_history(db_session):
    history = [
        {"role": "user", "content": "What did the insurer approve?"},
        {"role": "assistant", "content": "Rs 70,000 [[7]]."},
    ]

    with patch("app.agent.chat._client") as mock_client:
        mock_client.beta.messages.tool_runner.return_value = FakeRunner([["ok"]])
        list(stream_agent_response(db_session, history, "Why not the full amount?"))

    kwargs = mock_client.beta.messages.tool_runner.call_args.kwargs
    assert kwargs["messages"] == [
        {"role": "user", "content": "What did the insurer approve?"},
        {"role": "assistant", "content": "Rs 70,000 [[7]]."},
        {"role": "user", "content": "Why not the full amount?"},
    ]
    # The caller's history list must not be mutated — Task 16 persists it.
    assert len(history) == 2


def test_stream_agent_response_yields_lazily(db_session):
    """The return value must be a generator that streams: nothing is requested
    until the first token is pulled, and the second round trip must not start
    before the first stream's tokens have been yielded. If this ever became an
    eager function returning a prebuilt list, SSE in Task 16 would deliver the
    whole answer in one burst instead of token by token."""
    fake_runner = FakeRunner([["a", "b"], ["c"]])

    with patch("app.agent.chat._client") as mock_client:
        mock_client.beta.messages.tool_runner.return_value = fake_runner
        generator = stream_agent_response(db_session, [], "Why was my claim reduced?")

        # Nothing has run yet — not even the tool_runner call.
        mock_client.beta.messages.tool_runner.assert_not_called()

        assert next(generator) == "a"
        assert fake_runner.streams_started == 1
        assert next(generator) == "b"
        assert fake_runner.streams_started == 1
        assert next(generator) == "c"
        assert fake_runner.streams_started == 2
        assert list(generator) == []


def test_system_prompt_states_the_grounding_rules():
    assert "search_docs" in SYSTEM_PROMPT
    assert "reconcile_claim" in SYSTEM_PROMPT
    assert "[[chunk_id]]" in SYSTEM_PROMPT
    assert "standalone" in SYSTEM_PROMPT
    # Abstention rather than fabrication is the product's trust story.
    assert "Never guess or fabricate" in SYSTEM_PROMPT


def test_installed_sdk_still_matches_what_the_mock_assumes():
    """Guards the seam the mocks above paper over: every other test here fakes
    the runner, so none of them would notice if the installed SDK moved
    `tool_runner`, dropped `stream=`, or stopped handing back `text_stream`
    objects. Pure introspection — no API call, no network."""
    import inspect

    from anthropic.lib.streaming._beta_messages import BetaMessageStream
    from anthropic.lib.tools._beta_runner import BetaStreamingToolRunner
    from anthropic.resources.beta.messages.messages import Messages

    from app.agent import chat

    # The call path chat.py uses, and the `stream=True` it passes. (SDK
    # annotations are strings — it uses `from __future__ import annotations`.)
    assert callable(Messages.tool_runner)
    assert "stream" in inspect.signature(Messages.tool_runner).parameters
    assert "BetaStreamingToolRunner" in str(
        inspect.signature(Messages.tool_runner).return_annotation
    )
    # A real (unpatched) client exposes that path.
    assert callable(chat._client.beta.messages.tool_runner)

    # Iterating a streaming runner yields BetaMessageStreams, one per round trip.
    assert "BetaMessageStream" in str(
        inspect.signature(BetaStreamingToolRunner._handle_request).return_annotation
    )
    # `text_stream` is an *instance* attribute assigned in __init__ (the class
    # body only annotates it), which is why `hasattr(BetaMessageStream,
    # "text_stream")` is False and the fakes above set it on the instance.
    assert "text_stream" in BetaMessageStream.__annotations__
    assert not hasattr(BetaMessageStream, "text_stream")
    assert "self.text_stream" in inspect.getsource(BetaMessageStream.__init__)
