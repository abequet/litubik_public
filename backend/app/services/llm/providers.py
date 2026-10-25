# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Concrete providers: Anthropic, OpenAI, Gemini, Grok (x.ai), Mistral and any
local / self-hosted server speaking the OpenAI chat-completions dialect
(Ollama, LM Studio, vLLM, llama.cpp, OpenRouter...)."""
from dataclasses import dataclass

from app.services.llm.base import LLMError, LLMProvider, LLMResult


# Claude 5.x models think before answering and the hidden thinking is counted
# in `max_tokens`: a cap sized for the visible JSON alone (1500-4000 at some
# call sites) can be spent entirely on thinking, which surfaces as "Model
# returned no text". Output tokens are only billed when generated, so a
# generous floor costs nothing on a short answer.
ANTHROPIC_MIN_OUTPUT_TOKENS = 8192

# Server-side fallback on a safety-classifier refusal: the API re-runs the
# same request on a fallback model inside the same call ("default" = routed by
# refusal category, no model list to maintain). Beta, hence the header.
ANTHROPIC_FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Which request options a model id accepts, learnt from a 400 and remembered
# for the process: {"effort": bool, "fallbacks": bool}. Older models (4.5 and
# before) reject `output_config.effort`; a proxy or an old deployment may
# reject the fallback beta.
_ANTHROPIC_OPTS: dict[str, dict[str, bool]] = {}


@dataclass
class AnthropicProvider(LLMProvider):
    def __post_init__(self):
        self.name = "anthropic"

    def _opts(self) -> dict[str, bool]:
        return _ANTHROPIC_OPTS.setdefault(self.model, {"effort": True, "fallbacks": True})

    def generate(self, messages, system=None, max_tokens=4096) -> LLMResult:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        base: dict = {
            "model": self.model,
            "max_tokens": max(max_tokens, ANTHROPIC_MIN_OUTPUT_TOKENS),
            "messages": messages,
        }
        if system:
            base["system"] = system
        opts = self._opts()
        response = None
        for _ in range(3):
            kwargs = dict(base)
            if self.effort and opts["effort"]:
                kwargs["output_config"] = {"effort": self.effort}
            if opts["fallbacks"]:
                kwargs["betas"] = [ANTHROPIC_FALLBACK_BETA]
                kwargs["fallbacks"] = "default"
            try:
                response = client.beta.messages.create(**kwargs)
                break
            except anthropic.BadRequestError as e:
                msg = str(e)
                if "output_config" in kwargs and ("effort" in msg or "output_config" in msg):
                    opts["effort"] = False  # model predates the effort knob
                    continue
                if "fallbacks" in kwargs and ("fallback" in msg or "beta" in msg):
                    opts["fallbacks"] = False
                    continue
                raise LLMError(msg) from e
            except anthropic.APIError as e:
                raise LLMError(str(e)) from e
        if response is None:  # three rejections in a row: report the last shape
            raise LLMError("Anthropic rejected the request options for this model")
        self.answered_model = getattr(response, "model", None) or self.model
        billed = self._billed(response.usage.input_tokens,
                              response.usage.output_tokens)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            why = getattr(details, "explanation", None) or "safety classifier"
            raise LLMError(f"The model declined this request ({why}) — "
                           "try another model for this task in AI Settings",
                           billed=billed)
        text = "".join(b.text for b in response.content if b.type == "text")
        if not text.strip():
            # e.g. the whole budget went into non-text (thinking) blocks
            raise LLMError(
                f"Model returned no text (stop_reason={response.stop_reason}, "
                f"{response.usage.output_tokens} output tokens used) — try again "
                "or raise max_tokens", billed=billed)
        return LLMResult(
            text=text,
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
            truncated=response.stop_reason == "max_tokens",
        )


# What reasoning_effort a model id accepts, once the API has told us. The
# vocabulary drifts between model generations ("minimal" on GPT-5, refused by
# later GPT-5.x variants, which want "none"), so the value below is discovered
# by being rejected — remembering it keeps that to one probe per model per
# process. None means: this model takes no reasoning_effort at all.
_EFFORT_MEMO: dict[str, str | None] = {}
_UNKNOWN = object()  # sentinel: None is itself a memorisable answer


def _rejects_effort(exc: Exception) -> bool:
    """A 400 naming reasoning_effort: wrong value for this model, or the model
    does not take the parameter at all. Either way, retry differently."""
    return "reasoning_effort" in str(exc)


@dataclass
class OpenAICompatibleProvider(LLMProvider):
    base_url: str | None = None
    # Which request field carries the output cap. OpenAI retired `max_tokens`
    # for its reasoning models in favour of `max_completion_tokens`; most other
    # servers only know the original name (Mistral rejects unknown fields with
    # a 422, Ollama silently drops them — and then runs unbounded). A class
    # attribute rather than an error-driven probe, because "silently dropped"
    # never raises.
    token_param = "max_completion_tokens"

    def __post_init__(self):
        if not self.name:
            self.name = "openai"

    def _effort_candidates(self) -> list[str | None]:
        """Reasoning models (GPT-5, o-series) spend `max_completion_tokens` on
        hidden reasoning first; on a bounded classification task like triage
        that can eat the whole budget and leave no text. Cap the reasoning so
        the model actually emits the JSON.

        Several values, cheapest first, because the accepted vocabulary depends
        on the exact model; the trailing None is the last resort for a model
        (or a non-reasoning one, and Grok, whose names don't match) that rejects
        the parameter outright. A memorised value goes first but does not
        replace the ladder, so a stale memo still has somewhere to fall back."""
        m = self.model.lower()
        if m.startswith("gpt-5"):
            ladder: list[str | None] = ["minimal", "none", "low", None]
        elif m.startswith(("o1", "o3", "o4")):
            ladder = ["low", "minimal", None]
        else:
            ladder = [None]
        if self.effort and ladder != [None]:
            # the task route asked for a depth: try it first, keep the ladder
            # behind it for models that do not know the word
            ladder = [self.effort] + [e for e in ladder if e != self.effort]
        known = _EFFORT_MEMO.get(self._memo_key(), _UNKNOWN)
        if known is not _UNKNOWN:
            ladder = [known] + [e for e in ladder if e != known]
        return ladder

    def _memo_key(self) -> str:
        return f"{self.base_url or ''}|{self.model.lower()}|{self.effort or ''}"

    def generate(self, messages, system=None, max_tokens=4096) -> LLMResult:
        import openai

        client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        full_messages = ([{"role": "system", "content": system}] if system else []) + messages
        response = None
        rejected: Exception | None = None
        for effort in self._effort_candidates():
            kwargs = {"reasoning_effort": effort} if effort is not None else {}
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    **{self.token_param: max_tokens},
                    **kwargs,
                )
            except openai.OpenAIError as e:
                if effort is not None and _rejects_effort(e):
                    rejected = e  # wrong effort word here — try the next one
                    continue
                raise LLMError(str(e)) from e
            _EFFORT_MEMO[self._memo_key()] = effort
            break
        if response is None:
            raise LLMError(str(rejected)) from rejected
        usage = response.usage
        choice = response.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            # e.g. a reasoning model spent the whole budget on hidden reasoning
            raise LLMError(
                f"Model returned no text (finish_reason={choice.finish_reason}, "
                f"{usage.completion_tokens if usage else 0} completion tokens used) "
                "— try again or raise max_tokens",
                billed=self._billed(usage.prompt_tokens if usage else 0,
                                    usage.completion_tokens if usage else 0))
        return LLMResult(
            text=text,
            tokens_input=usage.prompt_tokens if usage else 0,
            tokens_output=usage.completion_tokens if usage else 0,
            truncated=choice.finish_reason == "length",
        )


@dataclass
class GrokProvider(OpenAICompatibleProvider):
    def __post_init__(self):
        self.name = "grok"
        self.base_url = "https://api.x.ai/v1"


@dataclass
class MistralProvider(OpenAICompatibleProvider):
    """Mistral's hosted API (La Plateforme) — OpenAI-compatible endpoint."""
    token_param = "max_tokens"

    def __post_init__(self):
        self.name = "mistral"
        self.base_url = "https://api.mistral.ai/v1"


@dataclass
class LocalProvider(OpenAICompatibleProvider):
    """A server the user runs themselves (Ollama, LM Studio, vLLM, llama.cpp
    server...) or any other OpenAI-compatible gateway, reached at a base URL
    stored with the credential. No API key is required: Ollama ignores the
    header, so an empty key becomes a placeholder the SDK accepts.

    Nothing leaves the machine the server runs on, which is the point — the
    AI-use journal records the provider as "local" so the disclosure
    statement can say so."""
    token_param = "max_tokens"

    def __post_init__(self):
        self.name = "local"
        if not self.api_key:
            self.api_key = "none"
        if not self.base_url:
            self.base_url = "http://localhost:11434/v1"


@dataclass
class GeminiProvider(LLMProvider):
    def __post_init__(self):
        self.name = "gemini"

    def generate(self, messages, system=None, max_tokens=4096) -> LLMResult:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        contents = [
            types.Content(
                role="user" if m["role"] == "user" else "model",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in messages
        ]
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                ),
            )
        except Exception as e:  # google-genai raises assorted exception types
            raise LLMError(str(e)) from e
        usage = response.usage_metadata
        text = response.text or ""
        finish = response.candidates[0].finish_reason if response.candidates else None
        if not text.strip():
            raise LLMError(
                f"Model returned no text (finish_reason={finish}, "
                f"{(usage.candidates_token_count or 0) if usage else 0} output tokens "
                "used) — try again or raise max_tokens",
                billed=self._billed(
                    (usage.prompt_token_count or 0) if usage else 0,
                    (usage.candidates_token_count or 0) if usage else 0))
        return LLMResult(
            text=text,
            tokens_input=(usage.prompt_token_count or 0) if usage else 0,
            tokens_output=(usage.candidates_token_count or 0) if usage else 0,
            truncated="MAX_TOKENS" in str(finish or ""),
        )
