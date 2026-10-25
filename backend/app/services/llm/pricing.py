# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Approximate per-model token pricing, used only to show the user a cost
*estimate* for AI usage (never billed against). Rates are USD per 1M tokens.

These are hand-maintained public list prices (Oct 2026) — edit here when a
provider changes pricing. Unknown models fall back to a per-provider default so
a never-seen model id still yields a sane order of magnitude rather than 0.
"""

# provider -> {model_id: (input_per_mtok, output_per_mtok)}
MODEL_PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "anthropic": {
        "claude-fable-5-1": (10.0, 50.0),
        "claude-fable-5": (10.0, 50.0),
        "claude-opus-5-5": (4.0, 20.0),
        "claude-opus-5": (5.0, 25.0),
        "claude-opus-4-8": (5.0, 25.0),
        "claude-opus-4-7": (5.0, 25.0),
        "claude-opus-4-6": (5.0, 25.0),
        "claude-sonnet-5-5": (2.0, 10.0),
        "claude-sonnet-5": (2.0, 10.0),
        "claude-sonnet-4-6": (3.0, 15.0),
        "claude-sonnet-4-5": (3.0, 15.0),
        # up to 100k-token prompts; beyond that the rate is (0.5, 2.5)
        "claude-haiku-5-5": (0.10, 0.50),
        "claude-haiku-4-5": (1.0, 5.0),
    },
    "openai": {
        "gpt-6-astra": (10.0, 50.0),  # up to 272k-token prompts
        "gpt-5.6-sol": (4.0, 20.0),
        "gpt-5.6-terra": (2.0, 12.0),
        "gpt-5.6-luna": (0.20, 1.20),
        "gpt-5": (1.25, 10.0),
        "gpt-5-mini": (0.25, 2.0),
        "gpt-4.1": (2.0, 8.0),
    },
    "gemini": {
        "gemini-2.5-pro": (1.25, 10.0),
        "gemini-2.5-flash": (0.30, 2.5),
    },
    "grok": {
        "grok-4": (3.0, 15.0),
        "grok-3-mini": (0.30, 0.50),
    },
    "mistral": {
        "mistral-large-latest": (2.0, 6.0),
        "mistral-medium-latest": (0.40, 2.0),
        "mistral-small-latest": (0.10, 0.30),
        "magistral-medium-latest": (2.0, 5.0),
    },
    # A self-hosted model costs electricity, not tokens: every call is $0.
    "local": {},
}

# Used when the exact model id is not in the table above.
PROVIDER_FALLBACK: dict[str, tuple[float, float]] = {
    "anthropic": (4.0, 20.0),
    "openai": (1.25, 10.0),
    "gemini": (1.25, 10.0),
    "grok": (3.0, 15.0),
    "mistral": (2.0, 6.0),
    "local": (0.0, 0.0),
}

# Providers whose calls are free by construction (the model runs on the
# user's own hardware) — the UI labels their estimates accordingly.
FREE_PROVIDERS = {"local"}


def is_free(provider: str) -> bool:
    return provider in FREE_PROVIDERS


def rates_for(provider: str, model: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for a provider/model, with fallback."""
    by_model = MODEL_PRICING.get(provider, {})
    if model in by_model:
        return by_model[model]
    return PROVIDER_FALLBACK.get(provider, (3.0, 15.0))


def cost_usd(provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
    in_rate, out_rate = rates_for(provider, model)
    return (tokens_in / 1_000_000) * in_rate + (tokens_out / 1_000_000) * out_rate


def chars_to_tokens(chars: int) -> int:
    """Rough char->token conversion (~4 chars/token for English prose)."""
    return round(chars / 4)


def format_usd(amount: float) -> str:
    """Human string for a small dollar amount (never rounds a real cost to $0)."""
    if amount <= 0:
        return "$0.00"
    if amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"


def call_cost(provider, result) -> dict:
    """Actual cost of a completed LLM call, from a provider + LLMResult. The
    payload every on-demand AI endpoint returns so the UI can show what it cost.
    Robust to test doubles that omit `name`/`model`."""
    return {**cost_breakdown(getattr(provider, "name", ""),
                             getattr(provider, "model", ""),
                             result.tokens_input, result.tokens_output),
            "estimated": False}


def cost_breakdown(provider: str, model: str, tokens_in: int,
                   tokens_out: int) -> dict:
    """The payload every AI endpoint returns so the UI can show what a call
    actually cost (or, with estimated token counts, what it would cost)."""
    amount = cost_usd(provider, model, tokens_in, tokens_out)
    return {
        "provider": provider,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": amount,
        "cost_label": format_usd(amount),
        "free": is_free(provider),
    }
