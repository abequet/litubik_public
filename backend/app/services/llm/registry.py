# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
from app.services.llm.base import LLMError, LLMProvider
from app.services.llm.providers import (
    AnthropicProvider,
    GeminiProvider,
    GrokProvider,
    LocalProvider,
    MistralProvider,
    OpenAICompatibleProvider,
)

# Also the fallback ranking order of `credentials._ranked_candidates`.
PROVIDERS = ["anthropic", "openai", "gemini", "grok", "mistral", "local"]

# What the settings UI needs to draw a card: the label, whether a key is
# required (a self-hosted server usually has none) and whether the endpoint
# URL is the user's to give.
PROVIDER_META: dict[str, dict] = {
    "anthropic": {"label": "Anthropic (Claude)", "needs_key": True, "needs_url": False},
    "openai": {"label": "OpenAI (GPT)", "needs_key": True, "needs_url": False},
    "gemini": {"label": "Google (Gemini)", "needs_key": True, "needs_url": False},
    "grok": {"label": "xAI (Grok)", "needs_key": True, "needs_url": False},
    "mistral": {"label": "Mistral AI", "needs_key": True, "needs_url": False},
    "local": {"label": "Local / self-hosted (Ollama, LM Studio, vLLM…)",
              "needs_key": False, "needs_url": True},
}

# Defaults shown in the settings UI; the model string is always user-editable.
# A credential's `default_model` is what a provider answers with when the task
# being run has no tier model below (self-hosted servers, mostly).
DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-5",
    "gemini": "gemini-2.5-pro",
    "grok": "grok-4",
    "mistral": "mistral-large-latest",
    "local": "llama3.1:8b",
}

SUGGESTED_MODELS = {
    "anthropic": ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5",
                  "claude-fable-5-1"],
    "openai": ["gpt-5", "gpt-5-mini", "gpt-4.1"],
    "gemini": ["gemini-2.5-pro", "gemini-2.5-flash"],
    "grok": ["grok-4", "grok-3-mini"],
    "mistral": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest",
                "magistral-medium-latest"],
    "local": ["llama3.1:8b", "llama3.3:70b", "qwen2.5:14b", "qwen3:8b", "gemma3:12b",
              "mistral-small3.1", "gpt-oss:20b"],
}

# Two tiers of AI work (services/llm/tasks.py sorts every feature into one):
# "bulk" = many short calls where throughput and price matter (screening,
# triage, translation, extraction); "reasoning" = few long calls where
# judgement matters (protocol, equations, narrative, report). A task that has
# no explicit route runs on the tier model of whichever credential is picked;
# a provider missing here (local) falls back to the credential's default_model.
TIERS = ["bulk", "reasoning"]
TIER_MODELS: dict[str, dict[str, str]] = {
    "anthropic": {"bulk": "claude-sonnet-5-5", "reasoning": "claude-opus-5-5"},
    "openai": {"bulk": "gpt-5-mini", "reasoning": "gpt-5"},
    "gemini": {"bulk": "gemini-2.5-flash", "reasoning": "gemini-2.5-pro"},
    "grok": {"bulk": "grok-3-mini", "reasoning": "grok-4"},
    "mistral": {"bulk": "mistral-medium-latest", "reasoning": "mistral-large-latest"},
}

# Reasoning depth a route may ask for. Mapped onto Anthropic's
# `output_config.effort` and OpenAI's `reasoning_effort`; ignored by providers
# without such a knob. "medium" is the shipped default everywhere: enough for
# structured review work, and it keeps the hidden thinking from eating the
# output budget on bounded tasks.
EFFORTS = ["low", "medium", "high"]
DEFAULT_EFFORT = "medium"


def tier_model(provider: str, tier: str) -> str | None:
    return TIER_MODELS.get(provider, {}).get(tier)


DEFAULT_LOCAL_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible endpoint


def needs_key(provider: str) -> bool:
    return PROVIDER_META.get(provider, {}).get("needs_key", True)


def needs_url(provider: str) -> bool:
    return PROVIDER_META.get(provider, {}).get("needs_url", False)


def get_provider(provider: str, api_key: str, model: str | None = None,
                 base_url: str | None = None,
                 effort: str | None = None) -> LLMProvider:
    model = model or DEFAULT_MODELS.get(provider, "")
    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model, effort=effort)
    if provider == "openai":
        return OpenAICompatibleProvider(api_key=api_key, model=model, effort=effort)
    if provider == "gemini":
        return GeminiProvider(api_key=api_key, model=model, effort=effort)
    if provider == "grok":
        return GrokProvider(api_key=api_key, model=model, effort=effort)
    if provider == "mistral":
        return MistralProvider(api_key=api_key, model=model, effort=effort)
    if provider == "local":
        return LocalProvider(api_key=api_key, model=model, effort=effort,
                             base_url=base_url or DEFAULT_LOCAL_URL)
    raise LLMError(f"Unknown LLM provider: {provider}")
