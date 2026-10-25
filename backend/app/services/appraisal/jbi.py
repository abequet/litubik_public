"""JBI critical-appraisal checklists, transcribed once from the JBI source
documents (the app never parses them at runtime).

The checklist wording is © JBI (Joanna Briggs Institute), made available for
research purposes. It is reproduced here with attribution and is NOT covered by
the AGPL licence of LitUbik — see NOTICE. JBI is a registered trademark of the
Joanna Briggs Institute; LitUbik is not affiliated with, nor endorsed by, JBI.

Each checklist: {key, label, source_file, options, domains: [{label,
questions: [{id, text}]}]}. The revised 2023/2024 tools (RCT,
quasi-experimental) group questions under bias domains and add per-question
comments; the classic tools are a flat list (single unnamed domain).
Answers are recorded per question as yes | no | unclear | na (+ comment), plus
an overall appraisal include | exclude | seek_info with a free comment.
"""

_YNU = ["yes", "no", "unclear"]
_YNUN = ["yes", "no", "unclear", "na"]


def _q(prefix: str, i: int, text: str) -> dict:
    return {"id": f"{prefix}{i}", "text": text}


CHECKLISTS: list[dict] = [
    {
        "key": "rct",
        "label": "Randomized controlled trial (RCT)",
        "source_file": "Revised Checklist for RCTs_updated_1.docx",
        "options": _YNUN,
        "domains": [
            {"label": "Bias related to selection and allocation", "questions": [
                _q("q", 1, "Was true randomization used for assignment of participants to treatment groups?"),
                _q("q", 2, "Was allocation to treatment groups concealed?"),
                _q("q", 3, "Were treatment groups similar at the baseline?"),
            ]},
            {"label": "Bias related to administration of intervention/exposure", "questions": [
                _q("q", 4, "Were participants blind to treatment assignment?"),
                _q("q", 5, "Were those delivering the treatment blind to treatment assignment?"),
                _q("q", 6, "Were treatment groups treated identically other than the intervention of interest?"),
            ]},
            {"label": "Bias related to assessment, detection and measurement of the outcome", "questions": [
                _q("q", 7, "Were outcome assessors blind to treatment assignment?"),
                _q("q", 8, "Were outcomes measured in the same way for treatment groups?"),
                _q("q", 9, "Were outcomes measured in a reliable way?"),
            ]},
            {"label": "Bias related to participant retention", "questions": [
                _q("q", 10, "Was follow up complete and if not, were differences between groups in terms of their follow up adequately described and analysed?"),
            ]},
            {"label": "Statistical conclusion validity", "questions": [
                _q("q", 11, "Were participants analysed in the groups to which they were randomized?"),
                _q("q", 12, "Was appropriate statistical analysis used?"),
                _q("q", 13, "Was the trial design appropriate and any deviations from the standard RCT design (individual randomization, parallel groups) accounted for in the conduct and analysis of the trial?"),
            ]},
        ],
    },
    {
        "key": "quasi_experimental",
        "label": "Quasi-experimental study",
        "source_file": "2_JBI checklist for quasi-experimental studies.docx",
        "options": _YNUN,
        "domains": [
            {"label": "Bias related to temporal precedence", "questions": [
                _q("q", 1, "Is it clear in the study what is the “cause” and what is the “effect” (i.e. there is no confusion about which variable comes first)?"),
            ]},
            {"label": "Bias related to selection and allocation", "questions": [
                _q("q", 2, "Was there a control group?"),
            ]},
            {"label": "Bias related to confounding factors", "questions": [
                _q("q", 3, "Were participants included in any comparisons similar?"),
            ]},
            {"label": "Bias related to administration of intervention/exposure", "questions": [
                _q("q", 4, "Were the participants included in any comparisons receiving similar treatment/care, other than the exposure or intervention of interest?"),
            ]},
            {"label": "Bias related to assessment, detection and measurement of the outcome", "questions": [
                _q("q", 5, "Were there multiple measurements of the outcome, both pre and post the intervention/exposure?"),
                _q("q", 6, "Were the outcomes of participants included in any comparisons measured in the same way?"),
                _q("q", 7, "Were outcomes measured in a reliable way?"),
            ]},
            {"label": "Bias related to participant retention", "questions": [
                _q("q", 8, "Was follow-up complete and if not, were differences between groups in terms of their follow-up adequately described and analyzed?"),
            ]},
            {"label": "Statistical conclusion validity", "questions": [
                _q("q", 9, "Was appropriate statistical analysis used?"),
            ]},
        ],
    },
    {
        "key": "cohort",
        "label": "Cohort study",
        "source_file": "Checklist_for_Cohort_Studies.docx",
        "options": _YNUN,
        "domains": [{"label": "", "questions": [
            _q("q", 1, "Were the two groups similar and recruited from the same population?"),
            _q("q", 2, "Were the exposures measured similarly to assign people to both exposed and unexposed groups?"),
            _q("q", 3, "Was the exposure measured in a valid and reliable way?"),
            _q("q", 4, "Were confounding factors identified?"),
            _q("q", 5, "Were strategies to deal with confounding factors stated?"),
            _q("q", 6, "Were the groups/participants free of the outcome at the start of the study (or at the moment of exposure)?"),
            _q("q", 7, "Were the outcomes measured in a valid and reliable way?"),
            _q("q", 8, "Was the follow up time reported and sufficient to be long enough for outcomes to occur?"),
            _q("q", 9, "Was follow up complete, and if not, were the reasons to loss to follow up described and explored?"),
            _q("q", 10, "Were strategies to address incomplete follow up utilized?"),
            _q("q", 11, "Was appropriate statistical analysis used?"),
        ]}],
    },
    {
        "key": "case_control",
        "label": "Case-control study",
        "source_file": "Checklist_for_Case_Control_Studies.docx",
        "options": _YNUN,
        "domains": [{"label": "", "questions": [
            _q("q", 1, "Were the groups comparable other than the presence of disease in cases or the absence of disease in controls?"),
            _q("q", 2, "Were cases and controls matched appropriately?"),
            _q("q", 3, "Were the same criteria used for identification of cases and controls?"),
            _q("q", 4, "Was exposure measured in a standard, valid and reliable way?"),
            _q("q", 5, "Was exposure measured in the same way for cases and controls?"),
            _q("q", 6, "Were confounding factors identified?"),
            _q("q", 7, "Were strategies to deal with confounding factors stated?"),
            _q("q", 8, "Were outcomes assessed in a standard, valid and reliable way for cases and controls?"),
            _q("q", 9, "Was the exposure period of interest long enough to be meaningful?"),
            _q("q", 10, "Was appropriate statistical analysis used?"),
        ]}],
    },
    {
        "key": "cross_sectional",
        "label": "Cross-sectional / prevalence study",
        "source_file": "Checklist_for_Prevalence_Studies.docx",
        "options": _YNUN,
        "domains": [{"label": "", "questions": [
            _q("q", 1, "Was the sample frame appropriate to address the target population?"),
            _q("q", 2, "Were study participants sampled in an appropriate way?"),
            _q("q", 3, "Was the sample size adequate?"),
            _q("q", 4, "Were the study subjects and the setting described in detail?"),
            _q("q", 5, "Was the data analysis conducted with sufficient coverage of the identified sample?"),
            _q("q", 6, "Were valid methods used for the identification of the condition?"),
            _q("q", 7, "Was the condition measured in a standard, reliable way for all participants?"),
            _q("q", 8, "Was there appropriate statistical analysis?"),
            _q("q", 9, "Was the response rate adequate, and if not, was the low response rate managed appropriately?"),
        ]}],
    },
    {
        "key": "qualitative",
        "label": "Qualitative research",
        "source_file": "2024_Checklist_for_Qualitative_Research_1.docx",
        "options": _YNU,
        "domains": [{"label": "", "questions": [
            _q("q", 1, "Is there congruity between the philosophical or theoretical positioning of the study and the methodological approach that has been adopted?"),
            _q("q", 2, "Is there congruity between the research methodology and the research question or objectives?"),
            _q("q", 3, "Is there congruity between the research methodology and the methods used to collect data?"),
            _q("q", 4, "Is there congruity between the research methodology and the representation and analysis of data?"),
            _q("q", 5, "Is there congruity between the research methodology and the interpretation of results?"),
            _q("q", 6, "Is there a statement locating the researcher culturally or theoretically?"),
            _q("q", 7, "Is the influence of the researcher on the research, and vice-versa, addressed?"),
            _q("q", 8, "Are participants, and where appropriate, their voices, adequately represented?"),
            _q("q", 9, "Is the research ethical according to current criteria, and for recent studies, is there evidence of ethical approval by an appropriate body?"),
            _q("q", 10, "Do the conclusions drawn in the research report flow from the analysis, or interpretation, of the data?"),
        ]}],
    },
    {
        "key": "case_report",
        "label": "Case report",
        "source_file": "Checklist_for_Case_Reports.docx",
        "options": _YNUN,
        "domains": [{"label": "", "questions": [
            _q("q", 1, "Were patient's demographic characteristics clearly described?"),
            _q("q", 2, "Was the patient's history clearly described and presented as a timeline?"),
            _q("q", 3, "Was the current clinical condition of the patient on presentation clearly described?"),
            _q("q", 4, "Were diagnostic tests or assessment methods and the results clearly described?"),
            _q("q", 5, "Was the intervention(s) or treatment procedure(s) clearly described?"),
            _q("q", 6, "Was the post-intervention clinical condition clearly described?"),
            _q("q", 7, "Were adverse events (harms) or unanticipated events identified and described?"),
            _q("q", 8, "Does the case report provide takeaway lessons?"),
        ]}],
    },
    {
        "key": "systematic_review",
        "label": "Systematic review / research synthesis",
        "source_file": "Checklist_for_Systematic_Reviews_and_Research_Syntheses.docx",
        "options": _YNUN,
        "domains": [{"label": "", "questions": [
            _q("q", 1, "Is the review question clearly and explicitly stated?"),
            _q("q", 2, "Were the inclusion criteria appropriate for the review question?"),
            _q("q", 3, "Was the search strategy appropriate?"),
            _q("q", 4, "Were the sources and resources used to search for studies adequate?"),
            _q("q", 5, "Were the criteria for appraising studies appropriate?"),
            _q("q", 6, "Was critical appraisal conducted by two or more reviewers independently?"),
            _q("q", 7, "Were there methods to minimize errors in data extraction?"),
            _q("q", 8, "Were the methods used to combine studies appropriate?"),
            _q("q", 9, "Was the likelihood of publication bias assessed?"),
            _q("q", 10, "Were recommendations for policy and/or practice supported by the reported data?"),
            _q("q", 11, "Were the specific directives for new research appropriate?"),
        ]}],
    },
]

BY_KEY: dict[str, dict] = {c["key"]: c for c in CHECKLISTS}

OVERALL_OPTIONS = ["include", "exclude", "seek_info"]


def checklist_for(design: str) -> dict | None:
    return BY_KEY.get(design)


def question_ids(design: str) -> list[str]:
    checklist = BY_KEY.get(design) or {}
    return [q["id"] for d in checklist.get("domains", [])
            for q in d["questions"]]


def score(design: str, answers: dict | None) -> dict | None:
    """JBI quality score: 1 point per 'yes' over the design's checklist.
    None when the design has no checklist; n_answered says how far along
    the appraisal is (a partial appraisal still gets a provisional score)."""
    qids = question_ids(design)
    if not qids:
        return None
    entries = {qid: (answers or {}).get(qid) or {} for qid in qids}
    return {
        "n_yes": sum(1 for e in entries.values() if e.get("answer") == "yes"),
        "n_questions": len(qids),
        "n_answered": sum(1 for e in entries.values() if e.get("answer")),
    }
