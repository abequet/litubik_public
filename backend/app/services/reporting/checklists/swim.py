"""The SWiM checklist, pre-filled from the review's synthesis declaration.

SWiM is an extension to PRISMA, not a replacement, and it has a scope: reviews
where meta-analysis of effect estimates was not possible for **at least some**
outcomes. So this checklist is offered when the review declared at least one
non-meta-analytic synthesis method, and stays out of the way otherwise — a
checklist shown to a review it does not apply to teaches people that checklists
are noise.

Reference: Campbell M, McKenzie JE, Sowden A, et al. Synthesis without
meta-analysis (SWiM) in systematic reviews: reporting guideline. BMJ
2020;368:l6890. The item wording is the authors' work, reproduced with
attribution under the article's licence (CC BY 4.0): it is NOT covered by the
AGPL licence of LitUbik (see NOTICE).
"""
from app.services.reporting.checklists.prisma2020 import (
    AUTHOR, EVIDENCED, NOT_DONE,
)

CITATION = ("Campbell M, McKenzie JE, Sowden A, et al. Synthesis without "
            "meta-analysis (SWiM) in systematic reviews: reporting guideline. "
            "BMJ 2020;368:l6890.")

# (number, section, text, dossier key on the synthesis block, per-outcome?)
_PLAN_ITEMS: tuple[tuple[str, str, str, str], ...] = (
    ("1a", "Methods",
     "Provide a description of, and rationale for, the groups used in the "
     "synthesis.", "grouping"),
    ("1b", "Methods",
     "Detail and provide rationale for any changes made subsequent to the "
     "protocol in the groups used in the synthesis.", "grouping_changes"),
    ("4", "Methods",
     "Where applicable, provide the criteria used, with supporting "
     "justification, to select the particular studies for the main synthesis "
     "or to draw conclusions from it.", "prioritisation"),
    ("5", "Methods",
     "State the method(s) used to examine heterogeneity in reported effects "
     "when it was not possible to undertake a meta-analysis.", "heterogeneity"),
    ("7", "Methods",
     "Describe the graphical and tabular methods used to present the effects, "
     "and the key study characteristics used to order the studies.",
     "presentation"),
    ("9", "Discussion",
     "Report the limitations of the synthesis methods and/or the groupings "
     "used, and how these affect the conclusions.", "limitations"),
)


def applies(dossier: dict) -> bool:
    return bool(dossier.get("synthesis", {}).get("swim_applies"))


def evaluate(dossier: dict) -> list[dict]:
    synthesis = dossier.get("synthesis", {})
    outcomes = synthesis.get("outcomes") or []
    rows = []

    def add(number, section, text, status, fact):
        rows.append({"number": number, "section": section, "text": text,
                     "status": status, "fact": fact})

    plan = {number: (section, text, key)
            for number, section, text, key in _PLAN_ITEMS}
    for number in ("1a", "1b"):
        section, text, key = plan[number]
        value = (synthesis.get(key) or "").strip()
        add(number, section, text,
            EVIDENCED if value else NOT_DONE,
            value[:400] if value else "Not declared in the synthesis plan.")

    # -- item 2: standardised metric, per outcome ----------------------------
    metrics = [f"{o['label']}: {o['metric']}" for o in outcomes if o.get("metric")]
    add("2", "Methods",
        "Describe the standardised metric for each outcome, why it was chosen, "
        "and any method used to transform the reported effects to it.",
        EVIDENCED if metrics else NOT_DONE,
        "; ".join(metrics) if metrics
        else "No outcome declares a standardised metric.")

    # -- item 3: synthesis method and its justification ----------------------
    described = [f"{o['label']}: {o['synthesis_method']}" for o in outcomes]
    unjustified = [o["label"] for o in outcomes
                   if not (o.get("method_rationale") or "").strip()]
    fact = "; ".join(described) if described else "No outcome declared."
    if described and unjustified:
        fact += (f" — no rationale recorded for: {', '.join(unjustified)} "
                 f"(SWiM asks for the method *and* its justification)")
    add("3", "Methods",
        "Describe and justify the methods used to synthesise the effects for "
        "each outcome when meta-analysis was not possible.",
        EVIDENCED if described and not unjustified
        else NOT_DONE if not described else AUTHOR,
        fact)

    for number in ("4", "5"):
        section, text, key = plan[number]
        value = (synthesis.get(key) or "").strip()
        add(number, section, text,
            EVIDENCED if value else NOT_DONE,
            value[:400] if value else "Not declared in the synthesis plan.")

    # -- item 6: certainty ----------------------------------------------------
    framework = synthesis.get("certainty_framework")
    add("6", "Methods",
        "Describe the methods used to assess the certainty of the synthesis "
        "findings.",
        NOT_DONE if framework in (None, "", "none") else EVIDENCED,
        "No certainty framework was applied."
        if framework in (None, "", "none")
        else f"{synthesis.get('certainty_framework_label', framework)}, "
             f"per outcome ({synthesis.get('n_outcomes_rated', 0)} of "
             f"{synthesis.get('n_outcomes', 0)} rated).")

    section, text, key = plan["7"]
    value = (synthesis.get(key) or "").strip()
    add("7", section, text, EVIDENCED if value else NOT_DONE,
        value[:400] if value else "Not declared in the synthesis plan.")

    # -- item 8: the findings, with their certainty and their studies --------
    rated = sum(1 for o in outcomes if o.get("certainty"))
    add("8", "Results",
        "For each comparison and outcome, describe the synthesised finding and "
        "the certainty of it, in language consistent with the question the "
        "synthesis addresses, indicating which studies contribute.",
        EVIDENCED if outcomes and rated == len(outcomes)
        else NOT_DONE if not outcomes else AUTHOR,
        "No outcome declared." if not outcomes
        else (f"{len(outcomes)} finding(s) in the Summary of Findings table, "
              f"{rated} with a certainty rating; contributing studies recorded "
              f"per outcome."))

    section, text, key = plan["9"]
    value = (synthesis.get(key) or "").strip()
    add("9", section, text, EVIDENCED if value else NOT_DONE,
        value[:400] if value else "Not declared in the synthesis plan.")

    return rows
