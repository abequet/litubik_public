# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What each AI feature does, in the terms a disclosure statement needs.

The activity grouping follows the structure DAISY validated for AI-use
disclosure (Ahmetoglu, Constantinides & Cox, CHIWORK '26,
doi:10.1145/3808045.3808056), re-cut for a systematic review: DAISY's writing
categories (drafting, figures, language editing) belong to the manuscript,
which LitUbik never sees, while the *methodology* is where the tool's AI
actually intervenes. So the six DAISY activities become seven review
activities, each with the input the model receives and the human control the
app enforces on it — the two things a reader needs to weigh the disclosure.
"""

# activity key -> label + the control LitUbik enforces (never author-declared:
# these are properties of the code, which is what makes them worth reporting)
ACTIVITIES: dict[str, dict] = {
    "protocol": {
        "label": "Protocol structuring and eligibility criteria",
        "control": "The extracted protocol and its I*/E* criteria must be "
                   "reviewed and validated by a human before any other stage "
                   "can use them.",
    },
    "search": {
        "label": "Search strategy design (concepts, keywords, strategy critique)",
        "control": "Proposals are added to an editable list; the reviewers "
                   "compose and freeze the final equation themselves.",
    },
    "screening": {
        "label": "Study selection support (title triage, screening suggestions)",
        "control": "AI output is stored as a suggestion, never as a reviewer "
                   "vote; bulk triage produces a proposal list that a human "
                   "reviews item by item before anything is excluded.",
    },
    "appraisal": {
        "label": "Critical appraisal support (study design, appraisal checklist)",
        "control": "Proposed answers are prefilled in the assessor's form and "
                   "saved only once the assessor submits them.",
    },
    "extraction": {
        "label": "Data extraction (table design, cell prefill)",
        "control": "Prefilled cells are marked as AI-origin and unvalidated; "
                   "they never overwrite a human value and count as extracted "
                   "data only after a human validates them.",
    },
    "synthesis": {
        "label": "Synthesis drafting (results narrative)",
        "control": "A draft written from the computed aggregates and the "
                   "consensus evidence table, edited by the authors.",
    },
    "reporting": {
        "label": "Reporting support (methods paragraph, AI disclosure)",
        "control": "Generated from the project's own audit trail and edited "
                   "by the authors before use.",
    },
}

# LLM feature key (see services/llm/prompts.py) -> where it sits and what it reads
FEATURES: dict[str, dict] = {
    "protocol_extract": {
        "activity": "protocol", "stage": "protocol",
        "label": "Protocol structure extraction",
        "inputs": "the uploaded protocol document",
    },
    "concepts_propose": {
        "activity": "search", "stage": "equations",
        "label": "Search-concept proposal",
        "inputs": "the protocol text and the concepts already listed by the "
                  "reviewers",
    },
    "concepts_suggest": {
        "activity": "search", "stage": "equations",
        "label": "Keyword and synonym suggestion",
        "inputs": "a concept name and its current keywords, with the protocol, "
                  "the research question and the other concept names as context",
    },
    "equations_advise": {
        "activity": "search", "stage": "equations",
        "label": "Search-strategy critique",
        "inputs": "the equation variants, their result counts per database "
                  "and the golden-set references",
    },
    "title_triage": {
        "activity": "screening", "stage": "screening",
        "label": "Bulk title triage",
        "inputs": "record titles and a protocol summary",
    },
    "screening_ta_suggest": {
        "activity": "screening", "stage": "screening",
        "label": "Title/abstract screening suggestion",
        "inputs": "one record's bibliographic data and abstract, with the "
                  "validated protocol",
    },
    "screening_ft_suggest": {
        "activity": "screening", "stage": "ft-screening",
        "label": "Full-text screening suggestion",
        "inputs": "the stored full text of one report, with the validated "
                  "protocol",
    },
    "translate_abstract": {
        "activity": "screening", "stage": "screening",
        "label": "Title/abstract translation (reading aid)",
        "inputs": "one record's title and abstract; the translation is shown "
                  "next to the original text, which stays the reference",
    },
    "extraction_columns": {
        "activity": "extraction", "stage": "extraction",
        "label": "Extraction column design",
        "inputs": "the validated protocol",
    },
    "extraction_design": {
        "activity": "appraisal", "stage": "extraction",
        "label": "Study-design classification",
        "inputs": "one report's title, abstract and full text",
    },
    "extraction_jbi": {
        "activity": "appraisal", "stage": "extraction",
        "label": "Appraisal prefill",
        "inputs": "the stored full text of one report",
    },
    "extraction_prefill": {
        "activity": "extraction", "stage": "extraction",
        "label": "Extraction row prefill",
        "inputs": "the stored full text of one report, with the protocol as "
                  "context",
    },
    "results_narrative": {
        "activity": "synthesis", "stage": "results",
        "label": "Results narrative synthesis",
        "inputs": "the computed aggregates and the consensus evidence table",
    },
    "results_topics": {
        "activity": "synthesis", "stage": "results",
        "label": "Thematic map cluster labelling",
        "inputs": "the salient terms and a few titles of each cluster",
    },
    "reporting_methods": {
        "activity": "reporting", "stage": "reporting",
        "label": "Methods paragraph drafting",
        "inputs": "the project's audit trail (settings and counts)",
    },
    "reporting_disclosure": {
        "activity": "reporting", "stage": "reporting",
        "label": "AI disclosure drafting",
        "inputs": "the project's AI-use journal",
    },
}

# order used everywhere the activities are listed
ACTIVITY_ORDER = ["protocol", "search", "screening", "appraisal", "extraction",
                  "synthesis", "reporting"]


def feature_label(key: str) -> str:
    return FEATURES.get(key, {}).get("label", key)


def activity_of(key: str) -> str | None:
    return FEATURES.get(key, {}).get("activity")
