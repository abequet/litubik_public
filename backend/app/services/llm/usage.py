# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AI-use journal: every LLM call a project makes is recorded.

Why a journal at all — the app already stores AI *outputs* (suggestions as
`is_ai` votes, prefilled cells as `origin='ai'`). But a suggestion that a
reviewer rejected leaves no vote, an edited keyword list looks hand-written,
and a strategy critique lives only in the reviewer's head. Reconstructing that
from memory months later is exactly the task authors are known to get wrong,
so the AI disclosure statement is written from this journal instead.

Recording is deliberately *aggregated* per (project, feature, provider/model,
author, UTC day): a 5 000-title triage is one row, and nothing about the
content of a call is stored — only that it happened, for which feature, and
what it cost.

Writes go through a private session: the caller is usually mid-transaction
(a screening suggestion is flushed but not committed when the call runs) and
the journal must never commit someone else's half-finished work. A journal
failure is swallowed — losing a usage row is bad, failing the reviewer's
screening suggestion because of it would be worse.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.services.llm import pricing
from app.services.llm.base import (BilledAttempt, LLMError, LLMProvider,
                                   LLMResult)

logger = logging.getLogger(__name__)


def record_usage(project_id: int | None, feature: str, provider: str,
                 model: str, user_id: int | None, tokens_in: int,
                 tokens_out: int) -> None:
    """Add one call to its (feature, model, author, day) bucket."""
    from app.core.db import SessionLocal
    from app.models import AiUsage

    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    cost = pricing.cost_usd(provider, model, tokens_in, tokens_out)
    db = SessionLocal()
    try:
        for attempt in (1, 2):
            row = (db.query(AiUsage)
                   .filter_by(project_id=project_id, feature=feature,
                              provider=provider, model=model, user_id=user_id,
                              day=day).first())
            if row is None:
                db.add(AiUsage(project_id=project_id, feature=feature,
                               provider=provider, model=model, user_id=user_id,
                               day=day, n_calls=1, tokens_in=tokens_in,
                               tokens_out=tokens_out, cost_usd=cost,
                               first_at=now, last_at=now))
            else:
                row.n_calls += 1
                row.tokens_in += tokens_in
                row.tokens_out += tokens_out
                row.cost_usd += cost
                row.last_at = now
            try:
                db.commit()
                return
            except IntegrityError:
                # another thread created the same bucket between the SELECT and
                # the INSERT (batch jobs run concurrently) — reread and add to it
                db.rollback()
                if attempt == 2:
                    raise
    except Exception:  # never fail an AI feature because of its own bookkeeping
        logger.warning("Could not record AI usage for %s", feature,
                       exc_info=True)
    finally:
        db.close()


class UsageLogger(LLMProvider):
    """Wraps a provider so every billed call lands in the journal — answers,
    refusals and empty replies, and failed attempts before a failover.

    Sits *outside* the fallback chain on purpose: it records the provider and
    model that actually answered, which is not necessarily the first key.
    """

    def __init__(self, inner: LLMProvider, feature: str,
                 project_id: int | None, user_id: int | None):
        self._inner = inner
        self._feature = feature
        self._project_id = project_id
        self._user_id = user_id
        self.api_key = getattr(inner, "api_key", "")
        self.model = inner.model
        self.name = getattr(inner, "name", "")

    def generate(self, messages, system=None, max_tokens=4096) -> LLMResult:
        try:
            result = self._inner.generate(messages, system=system,
                                          max_tokens=max_tokens)
        except LLMError as e:
            # a refusal or an empty answer is billed all the same
            self._record_billed(e.billed)
            raise
        self._record_billed(result.failed_attempts)
        # the chain reports who answered only after the call
        self.model = getattr(self._inner, "answered_model", None) or self._inner.model
        self.name = getattr(self._inner, "name", "")
        record_usage(self._project_id, self._feature, self.name, self.model,
                     self._user_id, result.tokens_input, result.tokens_output)
        return result

    def _record_billed(self, attempts: list[BilledAttempt]) -> None:
        for a in attempts:
            record_usage(self._project_id, self._feature, a.provider, a.model,
                         self._user_id, a.tokens_input, a.tokens_output)
