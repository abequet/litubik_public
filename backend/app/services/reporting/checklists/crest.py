# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Editorial triage triggers — the problems CREST_Triage looks for, not its
scores.

CREST_Triage asks a handling editor to rate six domains from 1 to 5, where 1 or
2 usually means rejection. Reproducing that scoring here would turn an editor's
tool into an author's, and self-awarding a 4 is precisely the self-declared
compliance the tool exists to catch. A score is a judgement; it is not a
property of the project.

What *is* a property of the project is the list of concrete problems CREST
enumerates under each domain: no appraisal instrument applied, no certainty
framework, a single assessor, a search strategy that was never frozen. Those
are checkable, and checking them before submission is worth more than a
self-assigned grade.

Reference: Whaley P. CREST_Triage: Appraisal Tool for Systematic Reviews.
2022. https://osf.io/u4j5m/
"""
from dataclasses import dataclass
from typing import Callable

CITATION = ("Whaley P. CREST_Triage: Appraisal Tool for Systematic Reviews "
            "(Word Version). 2022. https://osf.io/u4j5m/")

# How loudly to say it. "blocking" marks the problems CREST describes as
# usually prohibitive of publication; "worth checking" marks the rest.
BLOCKING = "blocking"
ADVISORY = "advisory"


@dataclass(frozen=True)
class Trigger:
    key: str
    domain: str
    severity: str
    # (dossier) -> message when the problem is present, "" when it is not
    check: Callable[[dict], str]


def _has_corpus(d: dict) -> bool:
    """Whether the review has studies to appraise, characterise or synthesise.

    A project that has not finished screening is not *failing* to appraise; it
    has not got there. Firing on it would train people to ignore the panel,
    which is the one thing a pre-submission check cannot afford.
    """
    return bool(d["prisma"].get("studies_included"))


def _no_appraisal(d: dict) -> str:
    if not _has_corpus(d):
        return ""
    appraisal = d["extraction"].get("appraisal") or d["extraction"]["jbi"]
    if appraisal["n_appraised"]:
        return ""
    return ("No study was critically appraised. CREST lists “no critical "
            "appraisal instrument was applied” among the problems that "
            "usually prevent publication.")


def _single_assessor(d: dict) -> str:
    appraisal = d["extraction"].get("appraisal") or d["extraction"]["jbi"]
    if not appraisal["n_appraised"] or appraisal.get("dual_assessment"):
        return ""
    return ("Studies were appraised by a single assessor. CREST looks for "
            "safeguards against assessor error; state this as a limitation, or "
            "run a duplicate appraisal.")


def _no_certainty(d: dict) -> str:
    if d["synthesis"].get("certainty_framework") not in (None, "", "none"):
        return ""
    if not d["synthesis"].get("n_outcomes"):
        return ""
    return ("Outcomes are declared but no certainty framework was applied. "
            "CREST's sixth domain opens on “no framework was used for "
            "certainty assessment”.")


def _synthesis_undeclared(d: dict) -> str:
    if d["synthesis"].get("declared") or not _has_corpus(d):
        return ""
    return ("The synthesis method was never declared, so the manuscript would "
            "have to name one from memory. CREST flags self-declared "
            "compliance rather than a described method.")


def _equation_never_frozen(d: dict) -> str:
    if not d["search"]["equations"] or d["search"].get("frozen_equation"):
        return ""
    return ("No search equation was frozen. The reproducibility of the search "
            "is CREST's second domain, and an unfrozen equation leaves no "
            "single query to quote.")


def _search_not_validated(d: dict) -> str:
    if not d["search"]["equations"]:
        return ""
    if any(e.get("golden") for e in d["search"]["equations"]):
        return ""
    return ("The search strategy was never checked against a set of known "
            "references. CREST asks about “the validation of the search "
            "strategy”; a relative-recall check on a golden set answers it.")


def _no_registration(d: dict) -> str:
    if d["registration"]["state"] != "undeclared":
        return ""
    return ("Nobody said whether the review was registered. State the register "
            "and number, or that it was not registered — the omission itself "
            "is what gets queried.")


def _unanswered_deviations(d: dict) -> str:
    n = d["deviations"]["n_detected_unanswered"]
    if not n:
        return ""
    return (f"{n} change(s) the pipeline noticed have not been answered. CREST "
            f"checks a review that references a protocol for consistency "
            f"between planned and applied methods.")


def _no_characteristics_table(d: dict) -> str:
    if d["extraction"]["started"] or not _has_corpus(d):
        return ""
    return ("No extraction table was built, so the review has no key study "
            "characteristics table — an item CREST lists explicitly.")


def _screening_single_reviewer(d: dict) -> str:
    rounds = [r for r in d["screening"]["ta"] + d["screening"]["ft"]
              if r["status"] == "active"]
    if not rounds:
        return ""
    solo = [r for r in rounds if r["n_reviewers"] < 2]
    if not solo:
        return ""
    return (f"{len(solo)} screening round(s) ran with a single reviewer. "
            f"CREST's third domain is about safeguards against reviewer error "
            f"in the screening process.")


TRIGGERS: tuple[Trigger, ...] = (
    Trigger("no_appraisal", "Critical appraisal", BLOCKING, _no_appraisal),
    Trigger("no_certainty", "Certainty assessment", BLOCKING, _no_certainty),
    Trigger("synthesis_undeclared", "Synthesis", BLOCKING,
            _synthesis_undeclared),
    Trigger("equation_never_frozen", "Search strategy", BLOCKING,
            _equation_never_frozen),
    Trigger("single_assessor", "Critical appraisal", ADVISORY,
            _single_assessor),
    Trigger("screening_single_reviewer", "Selection and screening", ADVISORY,
            _screening_single_reviewer),
    Trigger("search_not_validated", "Search strategy", ADVISORY,
            _search_not_validated),
    Trigger("no_registration", "Other", ADVISORY, _no_registration),
    Trigger("unanswered_deviations", "Other", ADVISORY, _unanswered_deviations),
    Trigger("no_characteristics_table", "Other", ADVISORY,
            _no_characteristics_table),
)


def evaluate(dossier: dict) -> list[dict]:
    """Only the problems that are actually present — a clean review gets an
    empty list, not a wall of green ticks nobody reads."""
    out = []
    for trigger in TRIGGERS:
        try:
            message = trigger.check(dossier)
        except (KeyError, TypeError):
            continue
        if message:
            out.append({"key": trigger.key, "domain": trigger.domain,
                        "severity": trigger.severity, "message": message})
    out.sort(key=lambda t: (t["severity"] != BLOCKING, t["domain"]))
    return out
