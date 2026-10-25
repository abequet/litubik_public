# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthesis methods, and the question each of them actually answers.

Straight from table 2 of the SWiM guideline (Campbell et al., BMJ
2020;368:l6890, abbreviated from McKenzie & Brennan 2019). It is reproduced
here rather than left to prose because SWiM item 9 asks authors to report the
limitations the *choice of method* imposes, and the commonest failure is
answering a different question from the one the method supports: vote counting
tells you whether there is any evidence of an effect, never what the average
effect is.

The UI shows the question next to the method for exactly that reason — the
declaration and its consequence are one decision, not two.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SynthesisMethod:
    key: str
    label: str
    # The question this method can answer, in SWiM's own words.
    question: str
    # What each study must report for the method to be applicable.
    minimum_data: str
    # True for the methods SWiM was written for (no meta-analysis of effect
    # estimates), which is what makes the SWiM checklist relevant to a review.
    without_meta_analysis: bool


_METHODS: tuple[SynthesisMethod, ...] = (
    SynthesisMethod(
        key="meta_analysis",
        label="Meta-analysis of effect estimates (and its extensions)",
        question="What is the common intervention effect? What is the average "
                 "effect? Which of several interventions is most effective? "
                 "What modifies the magnitude of the effect?",
        minimum_data="An effect estimate and its variance, per study",
        without_meta_analysis=False,
    ),
    SynthesisMethod(
        key="summarising_effects",
        label="Summarising effect estimates",
        question="What is the range and distribution of the observed effects?",
        minimum_data="An effect estimate per study",
        without_meta_analysis=True,
    ),
    SynthesisMethod(
        key="combining_p",
        label="Combining P values",
        question="Is there evidence of an effect in at least one study?",
        minimum_data="Direction of effect and a precise P value, per study",
        without_meta_analysis=True,
    ),
    SynthesisMethod(
        key="vote_counting",
        label="Vote counting based on the direction of effect",
        question="Is there any evidence of an effect?",
        minimum_data="Direction of effect per study — nothing more",
        without_meta_analysis=True,
    ),
    SynthesisMethod(
        key="narrative",
        label="Structured narrative synthesis",
        question="How do the findings relate to one another, and what pattern "
                 "do they form? A narrative synthesis does not estimate an "
                 "effect — describe the structure you applied, not the label.",
        minimum_data="Study findings as reported, grouped explicitly",
        without_meta_analysis=True,
    ),
    SynthesisMethod(
        key="thematic",
        label="Thematic or framework synthesis (qualitative findings)",
        question="What themes account for the findings across studies? Note "
                 "that neither SWiM nor GRADE covers qualitative synthesis — "
                 "ENTREQ, eMERGe and GRADE-CERQual do.",
        minimum_data="Qualitative findings and, for a framework synthesis, "
                     "the a priori framework",
        without_meta_analysis=True,
    ),
    SynthesisMethod(
        key="other",
        label="Another method — describe it",
        question="Whatever your rationale states. SWiM item 3 asks for the "
                 "method *and* its justification.",
        minimum_data="",
        without_meta_analysis=True,
    ),
)

METHODS: dict[str, SynthesisMethod] = {m.key: m for m in _METHODS}
DEFAULT_METHOD = "narrative"

# What the effect looks like, needed to phrase a GRADE informative statement
# ("reduces" vs "increases"). "unclear" is a real answer, not a missing one.
DIRECTIONS: dict[str, str] = {
    "decrease": "Decrease / reduction",
    "increase": "Increase",
    "no_effect": "No effect, or an effect too small to matter",
    "unclear": "Unclear or inconsistent across studies",
}
DEFAULT_DIRECTION = "unclear"


def method(key: str | None) -> SynthesisMethod:
    """Never raises: an unknown key (older or newer instance, hand-edited
    snapshot) degrades to the default rather than breaking the page."""
    return METHODS.get(key or "", METHODS[DEFAULT_METHOD])


def as_catalogue() -> list[dict]:
    return [{"key": m.key, "label": m.label, "question": m.question,
             "minimum_data": m.minimum_data,
             "without_meta_analysis": m.without_meta_analysis}
            for m in _METHODS]


def uses_meta_analysis(keys) -> bool:
    return any(method(k).key == "meta_analysis" for k in keys)


def swim_applies(keys) -> bool:
    """Whether the SWiM checklist is relevant to this review.

    SWiM exists for reviews where meta-analysis of effect estimates is not
    possible for *at least some* outcomes — so one non-meta-analytic outcome
    is enough, and a review that meta-analysed everything is out of scope.
    """
    return any(method(k).without_meta_analysis for k in keys)
