"""Thin OpenAI wrapper: JSON chat calls, retries, and a running cost estimate."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

log = logging.getLogger("llm")

# USD per 1M tokens (input, output). VERIFY against https://openai.com/api/pricing
# before trusting the footer number. Unknown models log a warning and count as 0.
PRICES_PER_M: dict[str, tuple[float, float]] = {
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
}
# USD per minute of audio. VERIFY as above.
TRANSCRIBE_PRICE_PER_MIN: dict[str, float] = {
    "gpt-4o-mini-transcribe": 0.003,
    "gpt-4o-transcribe": 0.006,
    "whisper-1": 0.006,
}

_EM_DASH_RE = re.compile(r"\s*[\u2014\u2015]\s*")
_EN_DASH_RE = re.compile(r"\s+–\s+")


def no_dashes(text: str) -> str:
    """Hard guard: em dashes never survive, whatever the model was told."""
    text = _EM_DASH_RE.sub(", ", text or "")
    return _EN_DASH_RE.sub(", ", text)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    audio_minutes: float = 0.0
    cost_usd: float = 0.0
    calls: int = 0
    unpriced: list[str] = field(default_factory=list)

    def add_tokens(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += prompt_tokens
        self.output_tokens += completion_tokens
        price = _lookup(PRICES_PER_M, model)
        if price is None:
            self._unpriced(model)
            return
        self.cost_usd += prompt_tokens / 1e6 * price[0] + completion_tokens / 1e6 * price[1]

    def add_audio(self, model: str, minutes: float) -> None:
        self.calls += 1
        self.audio_minutes += minutes
        price = _lookup(TRANSCRIBE_PRICE_PER_MIN, model)
        if price is None:
            self._unpriced(model)
            return
        self.cost_usd += minutes * price

    def _unpriced(self, model: str) -> None:
        """A model the price table does not know. The cost shown is then too low."""
        if model not in self.unpriced:
            log.warning("no price known for %s, its tokens are missing from the cost", model)
            self.unpriced.append(model)


def _lookup(table: dict, model: str):
    if model in table:
        return table[model]
    # Dated snapshots like gpt-5-nano-2025-08-07 share the base price.
    for key in sorted(table, key=len, reverse=True):
        if model.startswith(key + "-"):
            return table[key]
    return None


def _client():
    from openai import OpenAI  # imported lazily so --no-llm needs no key

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI()


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("model returned JSON that is not an object")
    return data


def chat_json(
    model: str,
    system: str,
    user: str,
    usage: Usage,
    max_output_tokens: int = 4000,
    reasoning_effort: str | None = None,
    attempts: int = 2,
) -> dict:
    """One JSON-mode chat call. Retries once on transport or parse failure."""
    client = _client()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        kwargs = dict(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            max_completion_tokens=max_output_tokens,
        )
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        try:
            resp = client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001, we log and retry once
            message = str(exc)
            if reasoning_effort and "reasoning_effort" in message:
                log.info("%s rejects reasoning_effort, retrying without it", model)
                reasoning_effort = None
                continue
            last_error = exc
            log.warning("%s call failed (attempt %d/%d): %s: %s", model, attempt, attempts, type(exc).__name__, exc)
            continue
        if resp.usage:
            usage.add_tokens(model, resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)
        choice = resp.choices[0] if resp.choices else None
        content = (choice.message.content if choice else "") or ""
        finish = getattr(choice, "finish_reason", None)
        if finish == "length" or not content.strip():
            # Reasoning models spend the completion budget on thinking first. An
            # empty or cut-off answer means the budget was too small: double it.
            last_error = ValueError(f"empty or truncated answer (finish_reason={finish}, {len(content)} chars)")
            log.warning("%s: %s, attempt %d/%d, raising budget %d -> %d", model, last_error, attempt, attempts, max_output_tokens, max_output_tokens * 2)
            max_output_tokens *= 2
            continue
        try:
            return _extract_json(content)
        except ValueError as exc:
            last_error = exc
            log.warning("%s returned invalid JSON (attempt %d/%d): %s", model, attempt, attempts, exc)
    raise RuntimeError(f"{model} failed after {attempts} attempts: {last_error}")
