# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider-agnostic LLM interface.

All providers expose the same generate() so pipeline modules (protocol
extraction, screening, extraction prefill...) never depend on a vendor SDK.
"""
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BilledAttempt:
    """A call the provider answered — and billed — without a usable reply
    (a refusal, an empty answer). The AI-use journal counts it all the same."""
    provider: str
    model: str
    tokens_input: int = 0
    tokens_output: int = 0


class LLMError(Exception):
    def __init__(self, *args, billed: list[BilledAttempt] | None = None):
        super().__init__(*args)
        # attempts that reached a provider and cost tokens before the failure
        self.billed: list[BilledAttempt] = list(billed or [])


@dataclass
class LLMResult:
    text: str
    tokens_input: int = 0
    tokens_output: int = 0
    data: dict | list | None = None  # parsed JSON when a schema was requested
    # the provider stopped at the output cap (max_tokens): the text is cut off
    truncated: bool = False
    # billed attempts on other keys that failed before this answer (failover)
    failed_attempts: list[BilledAttempt] = field(default_factory=list)


@dataclass
class LLMProvider(ABC):
    api_key: str
    model: str
    # reasoning depth asked by the task route (registry.EFFORTS); providers
    # without such a knob ignore it
    effort: str | None = None

    name: str = field(default="", init=False)
    # the model that actually produced the last answer when the provider
    # itself rerouted the call (Anthropic server-side fallback); None = `model`
    answered_model: str | None = field(default=None, init=False)

    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> LLMResult:
        """messages: [{"role": "user"|"assistant", "content": str}, ...]"""

    def _billed(self, tokens_input: int, tokens_output: int) -> list[BilledAttempt]:
        """The billing trace an LLMError carries when the model did answer."""
        return [BilledAttempt(self.name, self.answered_model or self.model,
                              tokens_input or 0, tokens_output or 0)]

    def generate_json(
        self,
        messages: list[dict],
        json_schema: dict,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> LLMResult:
        """Ask for JSON conforming to json_schema and parse the reply.

        Instruction-based (works identically across all four providers); the
        parsed object lands in result.data.
        """
        instruction = (
            "Reply with a single JSON object conforming exactly to this JSON Schema, "
            "with no markdown fences and no commentary:\n"
            + json.dumps(json_schema, ensure_ascii=False)
        )
        system_full = f"{system}\n\n{instruction}" if system else instruction
        result = self.generate(messages, system=system_full, max_tokens=max_tokens)
        try:
            result.data = _extract_json(result.text)
        except LLMError as e:
            if result.truncated:
                raise LLMError(
                    f"The model's answer was cut off at the output cap "
                    f"({result.tokens_output} output tokens, limit {max_tokens}): "
                    "the document is too long for one answer — shorten the "
                    "input, pick a model with a larger output window, or "
                    "lower the reasoning effort in AI Settings") from e
            raise
        return result

    def test_connection(self) -> LLMResult:
        # Budget must cover a reasoning model's hidden thinking, not just the
        # one-word reply: GPT-5 / o-series spend the token budget on reasoning
        # first and a tiny cap (e.g. 16) makes OpenAI reject the request with
        # "max_tokens ... reached". 256 is ample for "ok" and stays trivially
        # cheap for a one-off connectivity check.
        return self.generate([{"role": "user", "content": "Reply with the single word: ok"}],
                             max_tokens=256)


def _extract_json(text: str) -> dict | list:
    text = text.strip()
    # tolerate ```json fences despite the instruction
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        snippet = text[:150] if text else "(empty response)"
        raise LLMError(
            f"Model did not return valid JSON: {e} — response started with: "
            f"{snippet!r}") from e
