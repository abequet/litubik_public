# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The critical-appraisal instrument registry.

CREST_Triage judges an appraisal on three things: that an instrument was
applied at all, that it *fits* the studies being appraised, and that it was
applied correctly. The second is why this module exists: JBI covers health
research designs, and a review of driving simulators or interface design has no
business forcing its studies through a prevalence-study checklist.

An instrument is a catalogue of checklists, one per study design, each a list of
questions grouped in domains. Two sources:

- **built-in** — the JBI checklists (see jbi.py) and the MMAT 2018 (see
  mmat.py), each embedded from the user's own source files and each with a
  stated licence to be here;
- **project-declared** — an `AppraisalInstrument` row, where a team writes the
  instrument it actually uses. LitUbik ships no other third-party catalogue
  on purpose: redistributing someone else's appraisal tool is a licensing
  decision, not a packaging one.

An instrument also says what its answers *mean*: whether an overall
include/exclude judgement exists (JBI yes, MMAT no), whether counting the
criteria met is a figure worth showing (JBI yes, MMAT no — the guide
discourages any score), and how an answer is labelled (MMAT's "can't tell" is
stored as `unclear`). The consumers read those flags; none of them names an
instrument.

Both are read through the same shape, so every consumer — the appraisal form,
the Results aggregates, the audit trail — stays blind to where a checklist
came from.
"""
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.services.appraisal import jbi, mmat

# The shared study-design vocabulary. `Record.study_design` stores one of these
# keys, independently of which instrument the project uses — the design of a
# study is a property of the study, not of the tool used to appraise it.
# "other" is a real answer (a design no key covers), distinct from NULL (not
# qualified yet).
DESIGNS: dict[str, str] = {
    "rct": "Randomized controlled trial (RCT)",
    "quasi_experimental": "Quasi-experimental study",
    "cohort": "Cohort study",
    "case_control": "Case-control study",
    "cross_sectional": "Cross-sectional / prevalence study",
    "qualitative": "Qualitative research",
    "case_report": "Case report",
    "systematic_review": "Systematic review / research synthesis",
    "mixed_methods": "Mixed-methods study",
    "other": "Other / not covered",
}

BUILTIN_KEY = "jbi"


@dataclass(frozen=True)
class Instrument:
    key: str
    label: str
    citation: str
    url: str
    # Why the app is allowed to ship this text at all. Empty for a
    # project-declared instrument: the team wrote it, the team owns it.
    licence: str
    builtin: bool
    # Does the assessor conclude with an overall include/exclude judgement?
    overall: bool = True
    # Is the count of criteria met a figure worth showing at all?
    score: bool = True
    # design key -> {key, label, options, option_labels?, domains:
    #   [{label, optional?, questions: [{id, text}]}]}
    checklists: dict[str, dict] = field(default_factory=dict)

    def covers(self, design: str | None) -> bool:
        return bool(design) and design in self.checklists


_JBI = Instrument(
    key=BUILTIN_KEY,
    label="JBI critical appraisal checklists",
    citation="Joanna Briggs Institute",
    url="https://jbi.global/critical-appraisal-tools",
    licence="JBI checklists, reproduced from the tools JBI publishes for "
            "reviewers to use.",
    builtin=True,
    checklists={c["key"]: c for c in jbi.CHECKLISTS},
)

_MMAT = Instrument(
    key="mmat",
    label="Mixed Methods Appraisal Tool (MMAT) 2018",
    citation="Hong et al., 2018",
    url="http://mixedmethodsappraisaltoolpublic.pbworks.com",
    licence="MMAT criteria, reproduced from the user guide, which states the "
            "tool is free and its use open for any education and research "
            "activity.",
    builtin=True,
    overall=False,
    score=False,
    checklists={c["key"]: c for c in mmat.CHECKLISTS},
)

BUILTIN: dict[str, Instrument] = {_JBI.key: _JBI, _MMAT.key: _MMAT}

# What an assessor concludes overall, whatever the instrument.
OVERALL_OPTIONS = jbi.OVERALL_OPTIONS

# Answer vocabularies a project-declared instrument may pick from. Free-form
# option lists were tempting, but every consumer (the % agreement, the
# per-domain chart, the GRADE risk-of-bias prefill) has to know which answers
# mean "the study did the right thing" — so the sets are closed.
OPTION_SETS: dict[str, list[str]] = {
    "ynu": ["yes", "no", "unclear"],
    "ynun": ["yes", "no", "unclear", "na"],
}
# The answer that counts as "criterion met" — the only semantic the app needs.
POSITIVE_ANSWER = "yes"


def _from_row(row) -> Instrument:
    """An AppraisalInstrument row as an Instrument.

    Tolerant on purpose: a row written by a newer version, or hand-edited in a
    snapshot, degrades to whatever it can offer rather than breaking the
    appraisal screen of every record.
    """
    checklists = {}
    for design, spec in (row.checklists or {}).items():
        if design not in DESIGNS or not isinstance(spec, dict):
            continue
        options = OPTION_SETS.get(spec.get("options", ""), OPTION_SETS["ynun"])
        domains = []
        for d in spec.get("domains") or []:
            questions = [{"id": str(q.get("id", "")), "text": str(q.get("text", ""))}
                         for q in (d.get("questions") or [])
                         if str(q.get("id", "")) and str(q.get("text", ""))]
            if questions:
                domains.append({"label": str(d.get("label", "")),
                                "questions": questions})
        if domains:
            checklists[design] = {"key": design, "label": DESIGNS[design],
                                  "options": options, "domains": domains}
    return Instrument(key=row.key, label=row.label, citation=row.citation,
                      url=row.url, licence="", builtin=False,
                      checklists=checklists)


def project_instruments(db: Session, project_id: int) -> dict[str, Instrument]:
    """Every instrument this project can choose from: the built-in ones plus
    its own declarations."""
    from app.models import AppraisalInstrument
    out = dict(BUILTIN)
    for row in (db.query(AppraisalInstrument).filter_by(project_id=project_id)
                .order_by(AppraisalInstrument.id)):
        out[row.key] = _from_row(row)
    return out


def instrument(db: Session, project_id: int, key: str | None) -> Instrument:
    """The instrument a project appraises with.

    Never raises: a project whose custom instrument was deleted, or a snapshot
    naming an instrument this version does not know, falls back to JBI rather
    than losing access to its own appraisals — the stored answers are keyed by
    question id and survive the swap.
    """
    return project_instruments(db, project_id).get(key or "", BUILTIN[BUILTIN_KEY])


def checklist_for(inst: Instrument, design: str | None) -> dict | None:
    return inst.checklists.get(design or "")


def question_ids(inst: Instrument, design: str | None) -> list[str]:
    checklist = checklist_for(inst, design) or {}
    return [q["id"] for d in checklist.get("domains", [])
            for q in d["questions"]]


def domains_of(inst: Instrument, design: str | None) -> list[dict]:
    return (checklist_for(inst, design) or {}).get("domains", [])


def score(inst: Instrument, design: str | None, answers: dict | None) -> dict | None:
    """Count of criteria met over the design's checklist.

    Deliberately NOT a quality score: JBI and the Cochrane Handbook both advise
    against collapsing an appraisal into a number, and the Results page reports
    per-domain judgements. This count survives as a completeness indicator and
    for the per-record export, where the raw answers are what matter.
    """
    qids = question_ids(inst, design)
    if not qids:
        return None
    entries = {qid: (answers or {}).get(qid) or {} for qid in qids}
    return {
        "n_yes": sum(1 for e in entries.values()
                     if e.get("answer") == POSITIVE_ANSWER),
        "n_questions": len(qids),
        "n_answered": sum(1 for e in entries.values() if e.get("answer")),
    }


def required_question_ids(inst: Instrument, design: str | None) -> list[str]:
    """The questions an appraisal has to answer to count as complete: those
    of the non-optional domains. MMAT's screening questions and the component
    domains of its mixed-methods checklist are optional by the guide."""
    return [q["id"] for d in domains_of(inst, design) if not d.get("optional")
            for q in d["questions"]]


def is_complete(inst: Instrument, design: str | None, answers: dict | None,
                overall: str | None) -> bool:
    """Whether one assessor is done with one study.

    With an overall judgement (JBI), the judgement is the signature: an
    assessor who concluded is done, whatever they left blank on the way.
    Without one (MMAT), done means every required criterion is answered.
    """
    if inst.overall:
        return bool(overall)
    required = required_question_ids(inst, design)
    if not required:
        return False
    return all(((answers or {}).get(qid) or {}).get("answer")
               for qid in required)


def as_catalogue(inst: Instrument) -> dict:
    """Wire shape for the frontend and the audit trail."""
    return {
        "key": inst.key, "label": inst.label, "citation": inst.citation,
        "url": inst.url, "builtin": inst.builtin,
        "overall": inst.overall, "score": inst.score,
        "designs": sorted(inst.checklists),
        "checklists": [inst.checklists[d] for d in sorted(inst.checklists)],
    }


def summary(inst: Instrument) -> dict:
    """The few fields a consumer needs to render answers correctly."""
    return {"key": inst.key, "label": inst.label, "citation": inst.citation,
            "url": inst.url, "builtin": inst.builtin,
            "overall": inst.overall, "score": inst.score}
