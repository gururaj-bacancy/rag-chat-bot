from typing import Iterator

import anthropic
from sqlalchemy.orm import Session

from app.agent.tools import make_reconcile_claim_tool, make_search_docs_tool
from app.config import settings

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SYSTEM_PROMPT = """You help someone understand their Indian mediclaim health \
insurance claim. You have two tools: `search_docs` to find relevant text in \
their uploaded bill, policy, and settlement letter, and `reconcile_claim` to \
recompute whether the settlement math is correct.

Rules:
- Always call `search_docs` with a complete, standalone query — never a bare \
  pronoun or fragment like "that one"; resolve it from the conversation \
  yourself first.
- When the user asks why a deduction happened or whether it's correct, call \
  `reconcile_claim`.
- Every factual claim sourced from a retrieved chunk must be followed by \
  `[[chunk_id]]` using the chunk_id from that search_docs result.
- If neither tool grounds an answer, say so plainly and suggest contacting \
  the insurer directly. Never guess or fabricate a figure or clause."""


def stream_agent_response(
    session: Session, history: list[dict], user_message: str
) -> Iterator[str]:
    """Run one agent turn and yield the assistant's text token by token.

    With `stream=True` the SDK's Tool Runner returns a
    `BetaStreamingToolRunner`. Iterating it yields one `BetaMessageStream` per
    API round trip, and the runner executes the `@beta_tool` functions and
    feeds their results back between round trips itself — so a turn that calls
    `search_docs` and then answers surfaces here as two streams whose text
    simply continues. Each `BetaMessageStream.text_stream` yields only
    `text_delta` content, so thinking blocks and tool-call JSON never leak into
    what the caller streams to the user.

    This is a generator: nothing is requested until the first token is pulled,
    and each token is yielded as it arrives rather than accumulated.
    """
    tools = [make_search_docs_tool(session), make_reconcile_claim_tool(session)]
    messages = history + [{"role": "user", "content": user_message}]

    runner = _client.beta.messages.tool_runner(
        model="claude-opus-5",
        # Hitting max_tokens is a *terminal, silent* stop reason for the Tool
        # Runner (see _STOP_REASON_STEPS in anthropic/lib/tools/_beta_runner.py:
        # "max_tokens" -> "stop"), so a truncated turn reaches the user as a
        # short answer with no error — potentially cut off mid-`[[chunk_id]]`.
        # Anthropic's guidance for streaming requests is a large budget for
        # exactly this reason; timeouts aren't a concern when streaming.
        max_tokens=64000,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,
        # Without server-side fallbacks, a safety-classifier refusal on Opus 5
        # is also terminal (stop_reason "refusal" -> "stop") and yields zero
        # tokens — an unexplained dead end. "default" routes by refusal
        # category, so there is no fallback model list to maintain.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        stream=True,
    )
    for stream in runner:
        for text in stream.text_stream:
            yield text
