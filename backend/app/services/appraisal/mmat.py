"""Mixed Methods Appraisal Tool (MMAT), version 2018.

Hong, Q. N., Pluye, P., Fàbregues, S., Bartlett, G., Boardman, F., Cargo, M.,
Dagenais, P., Gagnon, M.-P., Griffiths, F., Nicolau, B., O'Cathain, A.,
Rousseau, M.-C., & Vedel, I. (2018). *Mixed Methods Appraisal Tool (MMAT),
version 2018. User guide.* McGill University. The French edition (2020-09-18)
is the one transcribed in the French translations.

The user guide states the tool is free and its use is open for any education
and research activity, which is what lets LitUbik embed the criteria the way
it embeds JBI's. The criteria wording is the MMAT authors' work, reproduced
with attribution: it is NOT covered by the AGPL licence of LitUbik (see
NOTICE).

How the tool maps onto the shared design vocabulary (instruments.DESIGNS):

- category 1 (qualitative)                      <- qualitative
- category 2 (quantitative randomized)          <- rct
- category 3 (quantitative non-randomized)      <- quasi_experimental, cohort,
                                                   case_control
- category 4 (quantitative descriptive)         <- cross_sectional, case_report
- category 5 (mixed methods)                    <- mixed_methods

Systematic reviews and "other" have no MMAT category: the guide says the tool
cannot appraise literature reviews, commentaries or theoretical papers.

Three things differ from JBI and are declared on the instrument rather than
special-cased in the consumers:

- the two screening questions (S1, S2) open every category, in a domain marked
  optional — the guide lets a review whose eligibility criteria already
  exclude non-empirical papers skip them;
- answers are yes / no / can't tell. "Can't tell" is stored as `unclear` so
  that every aggregate (per-domain chart, % of criteria met, consensus)
  treats it as JBI's "unclear"; only the label differs;
- there is no overall score and no include/exclude judgement: the guide
  discourages collapsing the ratings into a number and asks for a detailed
  presentation per criterion. A mixed-methods study is appraised on 5.1–5.5
  *and* on the qualitative and quantitative component criteria (5.5 is rated
  from them), so its checklist carries all four component domains and the
  assessor fills the quantitative one that applies.
"""

OPTIONS = ["yes", "no", "unclear"]
OPTION_LABELS = {"unclear": "Can't tell"}


def _q(i: str, text: str) -> dict:
    return {"id": i, "text": text}


SCREENING = {
    "label": "Screening questions (for all types)",
    "optional": True,
    "questions": [
        _q("S1", "Are there clear research questions?"),
        _q("S2", "Do the collected data allow to address the research questions?"),
    ],
}

QUALITATIVE = {
    "label": "1. Qualitative studies",
    "questions": [
        _q("1.1", "Is the qualitative approach appropriate to answer the research question?"),
        _q("1.2", "Are the qualitative data collection methods adequate to address the research question?"),
        _q("1.3", "Are the findings adequately derived from the data?"),
        _q("1.4", "Is the interpretation of results sufficiently substantiated by data?"),
        _q("1.5", "Is there coherence between qualitative data sources, collection, analysis and interpretation?"),
    ],
}

RANDOMIZED = {
    "label": "2. Quantitative randomized controlled trials",
    "questions": [
        _q("2.1", "Is randomization appropriately performed?"),
        _q("2.2", "Are the groups comparable at baseline?"),
        _q("2.3", "Are there complete outcome data?"),
        _q("2.4", "Are outcome assessors blinded to the intervention provided?"),
        _q("2.5", "Did the participants adhere to the assigned intervention?"),
    ],
}

NON_RANDOMIZED = {
    "label": "3. Quantitative non-randomized studies",
    "questions": [
        _q("3.1", "Are the participants representative of the target population?"),
        _q("3.2", "Are measurements appropriate regarding both the outcome and intervention (or exposure)?"),
        _q("3.3", "Are there complete outcome data?"),
        _q("3.4", "Are the confounders accounted for in the design and analysis?"),
        _q("3.5", "During the study period, is the intervention administered (or exposure occurred) as intended?"),
    ],
}

DESCRIPTIVE = {
    "label": "4. Quantitative descriptive studies",
    "questions": [
        _q("4.1", "Is the sampling strategy relevant to address the research question?"),
        _q("4.2", "Is the sample representative of the target population?"),
        _q("4.3", "Are the measurements appropriate?"),
        _q("4.4", "Is the risk of nonresponse bias low?"),
        _q("4.5", "Is the statistical analysis appropriate to answer the research question?"),
    ],
}

MIXED = {
    "label": "5. Mixed methods studies",
    "questions": [
        _q("5.1", "Is there an adequate rationale for using a mixed methods design to address the research question?"),
        _q("5.2", "Are the different components of the study effectively integrated to answer the research question?"),
        _q("5.3", "Are the outputs of the integration of qualitative and quantitative components adequately interpreted?"),
        _q("5.4", "Are divergences and inconsistencies between quantitative and qualitative results adequately addressed?"),
        _q("5.5", "Do the different components of the study adhere to the quality criteria of each tradition of the methods involved?"),
    ],
}

# Category -> the designs of the shared vocabulary it appraises.
CATEGORY_DESIGNS: dict[str, list[str]] = {
    "1": ["qualitative"],
    "2": ["rct"],
    "3": ["quasi_experimental", "cohort", "case_control"],
    "4": ["cross_sectional", "case_report"],
    "5": ["mixed_methods"],
}

_CATEGORY_DOMAIN = {"1": QUALITATIVE, "2": RANDOMIZED, "3": NON_RANDOMIZED,
                    "4": DESCRIPTIVE, "5": MIXED}


def _component(domain: dict, note: str) -> dict:
    """A category's criteria as a component domain of the mixed-methods
    checklist: same question ids (an answer to 1.3 means the same thing
    whether the study is qualitative or mixed), optional, and labelled for
    what the assessor is expected to do with it."""
    return {"label": f"{domain['label']} — {note}", "optional": True,
            "questions": domain["questions"]}


def _checklist(design: str, label: str, domains: list[dict]) -> dict:
    return {"key": design, "label": label, "options": OPTIONS,
            "option_labels": OPTION_LABELS, "domains": domains,
            "source_file": "MMAT_2018_criteria-manual_2020-09-18-FR.pdf"}


def _build() -> list[dict]:
    out = []
    for category, designs in CATEGORY_DESIGNS.items():
        domain = _CATEGORY_DOMAIN[category]
        if category == "5":
            domains = [
                SCREENING, MIXED,
                _component(QUALITATIVE, "qualitative component"),
                _component(RANDOMIZED,
                           "quantitative component, if randomized"),
                _component(NON_RANDOMIZED,
                           "quantitative component, if non-randomized"),
                _component(DESCRIPTIVE,
                           "quantitative component, if descriptive"),
            ]
        else:
            domains = [SCREENING, domain]
        for design in designs:
            out.append(_checklist(design, f"MMAT {domain['label']}", domains))
    return out


CHECKLISTS: list[dict] = _build()

BY_KEY: dict[str, dict] = {c["key"]: c for c in CHECKLISTS}
