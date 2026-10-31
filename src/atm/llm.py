"""Thin wrapper: one independent Claude call per agent, output validated against a pydantic schema."""

from __future__ import annotations

import threading
from typing import TypeVar

import anthropic
from pydantic import BaseModel

from .config import EFFORT, MODEL

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None

# Running totals for the eval report. USD per million tokens, Claude Opus 5.5 list price.
PRICE_IN, PRICE_OUT = 4.00, 20.00
USAGE = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
_lock = threading.Lock()


def cost_usd() -> float:
    return (USAGE["input_tokens"] * PRICE_IN + USAGE["output_tokens"] * PRICE_OUT) / 1e6


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
    with _lock:
        USAGE["calls"] += 1
        USAGE["input_tokens"] += response.usage.input_tokens
        USAGE["output_tokens"] += response.usage.output_tokens
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model refused: {response.stop_details}")
    return response.parsed_output
