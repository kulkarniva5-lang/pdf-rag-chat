"""Answer generation with Claude, grounded on retrieved chunks."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import anthropic

from .ingest import Chunk

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

SYSTEM_PROMPT = """You answer questions about the user's PDF documents.

You are given numbered source excerpts retrieved from those documents. Base your answer \
only on these excerpts. Cite every claim with the bracketed source number it came from, \
like [1] or [2][4]. If the excerpts do not contain the answer, say so plainly and suggest \
what the user could ask or upload instead; do not fill gaps from general knowledge.

Keep answers concise and well structured. Use Markdown for lists or emphasis when it helps."""

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


def format_sources(chunks: list[Chunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, start=1):
        parts.append(
            f'<source id="{i}" document="{c.doc_name}" page="{c.page}">\n{c.text}\n</source>'
        )
    return "\n\n".join(parts)


async def stream_answer(
    question: str, chunks: list[Chunk], history: list[dict]
) -> AsyncIterator[str]:
    """Yield answer text deltas."""
    context = format_sources(chunks) if chunks else "(no matching excerpts were found)"
    user_turn = f"<sources>\n{context}\n</sources>\n\nQuestion: {question}"

    # Prior turns are kept as plain text (without their old sources) so follow-up
    # questions like "tell me more" still have conversational context.
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-10:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages.append({"role": "user", "content": user_turn})

    async with client().beta.messages.stream(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=messages,
        output_config={"effort": "low"},
        # If the model declines on a safety classifier, the API re-runs the
        # request on a fallback model inside the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()
        if final.stop_reason == "refusal":
            yield "\n\n_The model declined to answer this question._"
        elif final.stop_reason == "max_tokens":
            yield "\n\n_(answer truncated)_"
