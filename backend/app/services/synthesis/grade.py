# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""GRADE: rating the certainty of the evidence, one outcome at a time.

Follows the five steps of Brignardello-Petersen & Guyatt (Am J Epidemiol
2025;194:1681-6):

1. clarify the intent of the question — causation or association;
2. define the target of the rating and pre-specify its thresholds;
3. choose a starting point from the study designs available;
4. judge the five domains that can lower certainty and the three that can
   raise it;
5. settle the final level, transparently.

Two things this module deliberately does **not** do. It never applies its own
arithmetic: `suggest_final()` proposes, the assessor stores what they decided,
and the two are shown side by side when they differ — the paper is explicit
that concerns are often not serious enough for a full level, that two
half-concerns can cost one level between them, and that the point is for
reviewers "to be transparent about their decisions". And it says nothing about
qualitative synthesis: GRADE rates certainty in quantitative estimates, and
GRADE-CERQual is the instrument for qualitative findings.
"""
from dataclasses import dataclass

# -- the certainty frameworks a project can pick ------------------------------
# A registry rather than a boolean: a review framed on SPIDER or SPICE is
# synthesising qualitative findings, where GRADE does not apply and CERQual
# does. Shipping the registry now means adding CERQual later is a catalogue
# entry, not a redesign.
FRAMEWORKS: dict[str, dict] = {
    "none": {
        "label": "No certainty framework",
        "description": "The review does not rate the certainty of its "
                       "findings. Editorial triage tools treat this as a "
                       "gap, so it is worth stating why.",
    },
    "grade": {
        "label": "GRADE",
        "description": "Rates the certainty of a quantitative estimate of "
                       "effect or association, per outcome. A methodological "
                       "expectation of Cochrane reviews.",
    },
}
DEFAULT_FRAMEWORK = "none"

# Question frameworks whose reviews synthesise qualitative findings, where
# GRADE is the wrong instrument (CERQual is the right one). Used to warn, never
# to forbid: the team knows its own evidence better than a mapping does.
QUALITATIVE_FRAMEWORKS = {"spider", "spice"}

# -- step 1 -------------------------------------------------------------------
INTENTS: dict[str, str] = {
    "causation": "Causation — does the intervention or exposure cause the "
                 "outcome?",
    "association": "Association — is the exposure associated with the "
                   "outcome, without claiming it causes it?",
}
DEFAULT_INTENT = "association"

# -- step 2 -------------------------------------------------------------------
TARGETS: dict[str, str] = {
    "any_effect": "An effect of any magnitude (the null value is the "
                  "threshold)",
    "important_effect": "An effect large enough to matter (a minimally "
                        "important difference is the threshold)",
    "magnitude": "A particular magnitude — trivial, small, moderate or large "
                 "(two thresholds delimit the range)",
}
DEFAULT_TARGET = "any_effect"

# -- step 3 -------------------------------------------------------------------
STARTING_POINTS: dict[str, str] = {
    "high": "High — the available designs are the most appropriate ones for "
            "this question",
    "low": "Low — the question would be better answered by another design "
           "than the one available",
}

# Designs that answer a causation question without an inherent design penalty.
# Everything else starts at "low" for causation, per GRADE guidelines 18 and
# the ROB instrument guidance for non-randomised studies of exposures.
_RANDOMISED_DESIGNS = {"rct"}

# -- step 4 -------------------------------------------------------------------
JUDGEMENTS: dict[str, int] = {"none": 0, "serious": 1, "very_serious": 2}
# Spelled out for the interface: "none" alone reads as "no answer" rather than
# as the judgement it is.
JUDGEMENT_LABELS: dict[str, str] = {
    "none": "No serious concern",
    "serious": "Serious concern",
    "very_serious": "Very serious concern",
}

DOWNGRADE_DOMAINS: tuple[tuple[str, str, str], ...] = (
    ("risk_of_bias", "Risk of bias",
     "Aspects of the design and conduct of the contributing studies that "
     "could bias the estimate. Depends on the study-level appraisal actually "
     "having been done, with a fitting instrument."),
    ("inconsistency", "Inconsistency",
     "The contributing studies disagree, and the review cannot explain why — "
     "non-overlapping confidence intervals, effects in opposite directions, "
     "high statistical heterogeneity."),
    ("imprecision", "Imprecision",
     "The confidence interval crosses a threshold you pre-specified, leaving "
     "more than one conclusion open."),
    ("indirectness", "Indirectness",
     "The evidence found only partly addresses the question asked — a "
     "narrower population, a surrogate outcome, an adjacent intervention."),
    ("publication_bias", "Publication bias",
     "Reason to suspect relevant studies were never published or could not "
     "be found. A comprehensive search across databases, registries and grey "
     "literature is what supports a judgement of no serious concern."),
)

UPGRADE_DOMAINS: tuple[tuple[str, str, str], ...] = (
    ("large_effect", "Large magnitude of effect",
     "An effect large enough that plausible confounding is unlikely to "
     "explain it."),
    ("dose_response", "Dose-response gradient",
     "More exposure, more outcome — across studies or within them."),
    ("opposing_confounding", "Residual confounding acting the other way",
     "The confounders that remain would, if anything, have pushed the "
     "estimate towards the null."),
)

# -- step 5 -------------------------------------------------------------------
LEVELS: tuple[str, ...] = ("high", "moderate", "low", "very_low")
LEVEL_LABELS: dict[str, str] = {
    "high": "High certainty",
    "moderate": "Moderate certainty",
    "low": "Low certainty",
    "very_low": "Very low certainty",
}


@dataclass(frozen=True)
class StartingPointProposal:
    """What the designs of the contributing studies suggest, and why."""
    starting_point: str
    rationale: str
    design_counts: dict[str, int]


def suggest_starting_point(intent: str,
                           designs: list[str | None]) -> StartingPointProposal:
    """Step 3, proposed from the qualified designs of the contributing studies.

    Never applied on its own: the panel shows the design counts that motivate
    the proposal, and the assessor stores what they decided. The rule follows
    the paper's own worked example — observational evidence answering a
    causation question starts at low; the same evidence answering an
    association question starts at high, because observational designs are the
    appropriate ones there.
    """
    counts: dict[str, int] = {}
    for design in designs:
        key = design or "unqualified"
        counts[key] = counts.get(key, 0) + 1
    n_total = sum(counts.values())
    n_randomised = sum(n for d, n in counts.items() if d in _RANDOMISED_DESIGNS)

    if n_total == 0:
        return StartingPointProposal(
            "low", "No contributing study is listed yet, so nothing supports "
                   "a starting point.", counts)
    if intent == "association":
        return StartingPointProposal(
            "high",
            f"The question is about association, which observational designs "
            f"answer appropriately: {n_total} contributing studies.", counts)
    if n_randomised == n_total:
        return StartingPointProposal(
            "high",
            f"All {n_total} contributing studies are randomised trials, the "
            f"most appropriate design for a causation question.", counts)
    if n_randomised == 0:
        return StartingPointProposal(
            "low",
            f"None of the {n_total} contributing studies is a randomised "
            f"trial, and the question is about causation — the design "
            f"available is not the one the question calls for.", counts)
    return StartingPointProposal(
        "low",
        f"{n_randomised} of {n_total} contributing studies are randomised "
        f"trials; the rest are observational, and the question is about "
        f"causation. Consider whether the non-randomised evidence carries "
        f"enough weight to start lower.", counts)


def suggest_final(starting_point: str, domains: dict, upgrades: dict) -> str:
    """Arithmetic proposal for step 5 — high/moderate/low/very_low.

    A convenience, not a verdict. GRADE explicitly allows rating down one level
    for two half-serious concerns across different domains, which no formula
    reproduces; the stored `final` is whatever the assessor decided, and the UI
    flags a divergence rather than silencing one.
    """
    index = 0 if starting_point == "high" else 2
    for key, _, _ in DOWNGRADE_DOMAINS:
        entry = (domains or {}).get(key) or {}
        index += JUDGEMENTS.get(str(entry.get("judgement", "none")), 0)
    # GRADE only rates up when no serious limitation was found; proposing an
    # upgrade on top of a downgrade would suggest they cancel out, which they
    # do not.
    if index == (0 if starting_point == "high" else 2):
        for key, _, _ in UPGRADE_DOMAINS:
            entry = (upgrades or {}).get(key) or {}
            if entry.get("applied"):
                index -= 1
    return LEVELS[max(0, min(index, len(LEVELS) - 1))]


# -- informative statements (GRADE guidelines 26) -----------------------------
# Wording follows Santesso et al., J Clin Epidemiol 2020;119:126-35: the
# certainty of the evidence is carried by the verb, not by a parenthesis.

_VERBS = {
    "causation": {
        "decrease": ("reduces", "probably reduces", "may reduce"),
        "increase": ("increases", "probably increases", "may increase"),
        "no_effect": ("results in little to no difference in",
                      "probably results in little to no difference in",
                      "may result in little to no difference in"),
    },
    "association": {
        "decrease": ("is associated with a lower",
                     "is probably associated with a lower",
                     "may be associated with a lower"),
        "increase": ("is associated with a higher",
                     "is probably associated with a higher",
                     "may be associated with a higher"),
        "no_effect": ("is associated with little to no difference in",
                      "is probably associated with little to no difference in",
                      "may be associated with little to no difference in"),
    },
}


def informative_statement(intent: str, direction: str, final: str,
                          outcome_label: str, comparison: str = "") -> str:
    """The sentence GRADE guideline 26 asks for, as a starting draft.

    Returned for the author to edit, never stored behind their back: only they
    know how the intervention and the outcome should be named in their own
    prose.
    """
    subject = comparison.strip() or "The intervention"
    outcome = outcome_label.strip() or "the outcome"
    if final == "very_low" or direction == "unclear":
        if intent == "association":
            return (f"The evidence is very uncertain about the association "
                    f"between {subject.lower()} and {outcome}.")
        return (f"The evidence is very uncertain about the effect of "
                f"{subject.lower()} on {outcome}.")
    verbs = _VERBS.get(intent, _VERBS["association"]).get(direction)
    if verbs is None:
        return ""
    verb = {"high": verbs[0], "moderate": verbs[1], "low": verbs[2]}[final]
    if intent == "association":
        return f"{subject} {verb} {outcome}."
    return f"{subject} {verb} {outcome}."


def as_catalogue() -> dict:
    """Everything the certainty form needs to render, in one payload."""
    return {
        "frameworks": [{"key": k, **v} for k, v in FRAMEWORKS.items()],
        "intents": [{"key": k, "label": v} for k, v in INTENTS.items()],
        "targets": [{"key": k, "label": v} for k, v in TARGETS.items()],
        "starting_points": [{"key": k, "label": v}
                            for k, v in STARTING_POINTS.items()],
        "downgrade_domains": [{"key": k, "label": lab, "help": h}
                              for k, lab, h in DOWNGRADE_DOMAINS],
        "upgrade_domains": [{"key": k, "label": lab, "help": h}
                            for k, lab, h in UPGRADE_DOMAINS],
        "judgements": [{"key": k, "label": JUDGEMENT_LABELS[k]}
                       for k in JUDGEMENTS],
        "levels": [{"key": k, "label": LEVEL_LABELS[k]} for k in LEVELS],
    }
