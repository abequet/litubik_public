# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AI tasks a reviewer can route to a (provider, model, effort).

Every `feature` key passed to `open_provider_chain()` (the prompt keys of
services/llm/prompts.py) belongs to exactly one task below. A task is what the
settings UI shows one row for; its tier (registry.TIERS) decides the default
model when no explicit route is stored.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSpec:
    key: str
    label: str
    description: str
    tier: str                 # "bulk" | "reasoning"
    features: tuple[str, ...]  # prompt keys / usage-journal features


TASKS: list[TaskSpec] = [
    TaskSpec("screening_ta", "Screening — title/abstract",
             "Per-record and batch suggestions during title/abstract screening.",
             "bulk", ("screening_ta_suggest",)),
    TaskSpec("screening_ft", "Screening — full text",
             "Suggestions against the full text during full-text screening.",
             "bulk", ("screening_ft_suggest",)),
    TaskSpec("triage", "Title triage",
             "Ranking of imported records by relevance before screening.",
             "bulk", ("title_triage",)),
    TaskSpec("translation", "Abstract translation",
             "Translation of non-English titles and abstracts.",
             "bulk", ("translate_abstract",)),
    TaskSpec("topics", "Thematic map labels",
             "Naming of the clusters on the corpus topic map.",
             "bulk", ("results_topics",)),
    TaskSpec("extraction", "Data extraction",
             "Column proposals, study design, JBI appraisal and pre-filled "
             "extraction from the full text.",
             "bulk", ("extraction_columns", "extraction_design",
                      "extraction_jbi", "extraction_prefill")),
    TaskSpec("protocol", "Protocol drafting",
             "Structured extraction of the protocol (PICO, criteria…) from "
             "the uploaded document.",
             "reasoning", ("protocol_extract",)),
    TaskSpec("equations", "Search equations",
             "Translation of a search equation between databases and "
             "advice on a draft equation.",
             "reasoning", ("equation_translate", "equations_advise")),
    TaskSpec("concepts", "Concepts and synonyms",
             "Proposals of search concepts and of synonyms for them.",
             "reasoning", ("concepts_propose", "concepts_suggest")),
    TaskSpec("narrative", "Results narrative",
             "Draft of the narrative synthesis from the evidence tables.",
             "reasoning", ("results_narrative",)),
    TaskSpec("reporting", "PRISMA report",
             "Methods section and AI-disclosure statement of the manuscript.",
             "reasoning", ("reporting_methods", "reporting_disclosure")),
]

TASK_BY_KEY: dict[str, TaskSpec] = {t.key: t for t in TASKS}
_TASK_OF_FEATURE: dict[str, TaskSpec] = {
    f: t for t in TASKS for f in t.features}


def task_for_feature(feature: str | None) -> TaskSpec | None:
    """The task a call-site feature key belongs to (None for calls that are
    not review work, e.g. connectivity tests)."""
    if not feature:
        return None
    return _TASK_OF_FEATURE.get(feature)


def tier_for_feature(feature: str | None) -> str:
    task = task_for_feature(feature)
    return task.tier if task else "reasoning"
