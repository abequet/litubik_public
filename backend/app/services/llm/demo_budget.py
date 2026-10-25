# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AI budget of demo visitors.

A demo instance lets its sandbox accounts try the AI features on the app-wide
key, within two caps (core/config.py):

- per sandbox account (`demo_ai_user_cap_usd`, $2 by default) — kept on the
  account row, so it goes with the account at the nightly purge;
- for all of them together per UTC day (`demo_ai_daily_cap_usd`, $1) and per
  calendar month (`demo_ai_monthly_cap_usd`, $10) — kept in `demo_ai_budget`,
  which holds no personal data and outlives the purge. The daily share keeps
  a bot (or one busy afternoon) from leaving the next visitors without AI for
  the rest of the month.

`DemoBudgetGuard` wraps the provider a sandbox project gets. Before each call
it prices the worst case (the prompt plus `max_tokens` of answer) and refuses
when that could cross either cap; after the call it adds what the call really
cost, failed attempts included. Batch jobs run a few calls at once, so the
caps can be overshot by the cost of the calls already in flight — a few cents.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.llm import pricing
from app.services.llm.base import (BilledAttempt, LLMError, LLMProvider,
                                   LLMResult)

logger = logging.getLogger(__name__)


def demo_ai_enabled() -> bool:
    settings = get_settings()
    return (settings.demo_ai_user_cap_usd > 0
            and settings.demo_ai_daily_cap_usd > 0
            and settings.demo_ai_monthly_cap_usd > 0)


def current_period(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def current_day(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def month_spent(db: Session, period: str | None = None) -> tuple[float, int]:
    """(USD spent, calls) by all sandbox accounts this month (or `period`,
    a month "YYYY-MM" or a day "YYYY-MM-DD")."""
    from app.models import DemoAiBudget
    row = db.query(DemoAiBudget).filter_by(period=period or current_period()).first()
    return (row.spent_usd, row.n_calls) if row else (0.0, 0)


def budget_status(db: Session, user_id: int | None) -> dict:
    """What is left for one sandbox account, and for the month."""
    from app.models import User
    settings = get_settings()
    spent_month, calls = month_spent(db)
    spent_day, _ = month_spent(db, current_day())
    user = db.get(User, user_id) if user_id is not None else None
    spent_user = (user.demo_ai_spent_usd or 0.0) if user is not None else 0.0
    user_left = max(0.0, settings.demo_ai_user_cap_usd - spent_user)
    day_left = max(0.0, settings.demo_ai_daily_cap_usd - spent_day)
    month_left = max(0.0, settings.demo_ai_monthly_cap_usd - spent_month)
    return {
        "enabled": demo_ai_enabled(),
        "user_cap_usd": settings.demo_ai_user_cap_usd,
        "daily_cap_usd": settings.demo_ai_daily_cap_usd,
        "monthly_cap_usd": settings.demo_ai_monthly_cap_usd,
        "user_spent_usd": round(spent_user, 4),
        "day_spent_usd": round(spent_day, 4),
        "month_spent_usd": round(spent_month, 4),
        "month_calls": calls,
        "user_left_usd": round(user_left, 4),
        "day_left_usd": round(day_left, 4),
        "month_left_usd": round(month_left, 4),
        "left_usd": round(min(user_left, day_left, month_left), 4),
        "period": current_period(),
    }


def charge(user_id: int, cost: float) -> None:
    """Add one call's cost to the account and to the month, atomically (the
    increments run in SQL, so concurrent calls of a batch job never lose one).
    Own session, like the AI-use journal: the caller is often mid-transaction."""
    from app.core.db import SessionLocal
    from app.models import DemoAiBudget, User

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user_id).update(
            {User.demo_ai_spent_usd: User.demo_ai_spent_usd + cost},
            synchronize_session=False)
        if db.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        for period in (current_period(now), current_day(now)):
            stmt = insert(DemoAiBudget).values(period=period, spent_usd=cost,
                                               n_calls=1, updated_at=now)
            stmt = stmt.on_conflict_do_update(
                index_elements=["period"],
                set_={"spent_usd": DemoAiBudget.spent_usd
                      + stmt.excluded.spent_usd,
                      "n_calls": DemoAiBudget.n_calls + 1,
                      "updated_at": now})
            db.execute(stmt)
        db.commit()
    except Exception:
        # the guard refuses on the NEXT call anyway once the caps are crossed;
        # failing this one because of the bookkeeping would only hide the answer
        logger.warning("Could not record demo AI spending", exc_info=True)
    finally:
        db.close()


def reset_month(db: Session) -> None:
    """The superadmin's reset: this month and today start from zero again."""
    from app.models import DemoAiBudget
    db.query(DemoAiBudget).filter(
        DemoAiBudget.period.in_((current_period(), current_day()))).delete(
        synchronize_session=False)
    db.commit()


def prune_days(db: Session, keep_days: int = 40) -> None:
    """Drop the daily rows older than `keep_days` (monthly rows are kept)."""
    from datetime import timedelta

    from app.models import DemoAiBudget
    cutoff = current_day(datetime.now(timezone.utc) - timedelta(days=keep_days))
    db.query(DemoAiBudget).filter(DemoAiBudget.period.like("____-__-__"),
                                  DemoAiBudget.period < cutoff).delete(
        synchronize_session=False)
    db.commit()


def _prompt_chars(messages: list[dict], system: str | None) -> int:
    total = len(system or "")
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += len(content)
        else:  # content blocks: count their text, or their serialised size
            for block in content or []:
                text = block.get("text") if isinstance(block, dict) else None
                total += len(text) if isinstance(text, str) else len(
                    json.dumps(block, default=str))
    return total


class DemoBudgetGuard(LLMProvider):
    """Keeps a sandbox project's AI calls inside the demo budget (see the
    module docstring). Sits inside the AI-use journal's UsageLogger, around
    the single app-wide key a sandbox runs on."""

    def __init__(self, inner: LLMProvider, user_id: int):
        self._inner = inner
        self._user_id = user_id
        self.api_key = getattr(inner, "api_key", "")
        self.model = inner.model
        self.name = getattr(inner, "name", "")

    def generate(self, messages, system=None, max_tokens=4096) -> LLMResult:
        from app.core.db import SessionLocal
        with SessionLocal() as db:
            status = budget_status(db, self._user_id)
        left = status["left_usd"]
        if left <= 0 and status["day_left_usd"] <= 0 < min(
                status["user_left_usd"], status["month_left_usd"]):
            raise LLMError(
                "Today's demo AI budget is used up "
                f"(${status['daily_cap_usd']:.2f} a day for all visitors) — "
                "it starts again tomorrow (UTC).")
        if left <= 0:
            raise LLMError(
                "The demo AI budget is used up "
                f"(${status['user_cap_usd']:.2f} per visitor, "
                f"${status['monthly_cap_usd']:.2f} a month for all visitors). "
                "Install LitUbik to use your own AI key.")
        worst = pricing.cost_usd(
            self.name, self.model,
            pricing.chars_to_tokens(_prompt_chars(messages, system)), max_tokens)
        if worst > left:
            raise LLMError(
                f"This AI action could cost up to {pricing.format_usd(worst)}, "
                f"more than the {pricing.format_usd(left)} left in the demo AI "
                "budget.")
        try:
            result = self._inner.generate(messages, system=system,
                                          max_tokens=max_tokens)
        except LLMError as e:
            self._charge(e.billed)
            raise
        # pass on who answered: the journal (UsageLogger) reads it from here
        self.answered_model = getattr(self._inner, "answered_model", None)
        self.model = self._inner.model
        self.name = getattr(self._inner, "name", "")
        self._charge(result.failed_attempts + [BilledAttempt(
            self.name, self.answered_model or self.model,
            result.tokens_input, result.tokens_output)])
        return result

    def _charge(self, attempts: list[BilledAttempt]) -> None:
        cost = sum(pricing.cost_usd(a.provider, a.model, a.tokens_input,
                                    a.tokens_output) for a in attempts)
        if cost > 0:
            charge(self._user_id, cost)
