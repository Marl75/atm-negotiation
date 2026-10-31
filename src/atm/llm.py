"""Thin wrapper: one independent Claude call per agent, output validated against a pydantic schema."""

from __future__ import annotations

from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import EFFORT, MODEL

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def ask_structured(system: str, user: str, schema: type[T]) -> T:
    response = client().messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": EFFORT},
        output_format=schema,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model refused: {response.stop_details}")
    return response.parsed_output
