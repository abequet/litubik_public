# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How a project frames its review: its type, and the framework its question
is built on.

Two project-level settings — `Project.review_type` and
`Project.question_framework` — drive the *vocabulary* of the app: the slots the
protocol extraction looks for, the concept-block labels, the extraction
template offered, the framing the AI is told about, and what the Methods draft
claims the review is. They change nothing in the pipeline itself: the same
search, screening, PRISMA and snowballing run whatever is chosen here. That
limit is stated to the user through `ReviewType.tooling_note`.

The module is deliberately flat and stateless: protocol, extraction, reporting,
concepts and equations all read it, so it must not live inside any one of them.

Unknown keys fall back to the defaults rather than raising — a sync snapshot
written by a newer version must not break an older instance.
"""
from dataclasses import dataclass

DEFAULT_REVIEW_TYPE = "systematic"
DEFAULT_FRAMEWORK = "picos"


@dataclass(frozen=True)
class Slot:
    """One element of a question framework (the "P" of PICO, the "S" of
    SPIDER…). `hint` is written for the extraction model, not for the UI."""
    key: str
    letter: str
    label: str
    hint: str


@dataclass(frozen=True)
class Framework:
    key: str
    short: str        # SPIDER, PICO… shown in the UI next to the concepts
    label: str
    citation: str     # "" for the frameworks that have no canonical paper
    slots: tuple[Slot, ...]

    def slot_labels(self) -> list[str]:
        return [s.label for s in self.slots]


@dataclass(frozen=True)
class ReviewType:
    key: str
    label: str
    citation: str
    default_framework: str
    default_template: str      # key in services.extraction.service.TEMPLATES
    context_line: str          # one line of framing given to the AI
    guideline: str             # reporting guideline recorded in the audit trail
    synthesis_method: str      # cited verbatim by the Methods draft
    tooling_note: str          # what the software does NOT do for this type


_FRAMEWORKS: tuple[Framework, ...] = (
    Framework(
        key="pico", short="PICO", label="PICO", citation="",
        slots=(
            Slot("population", "P", "Population",
                 "Population or participants the review is about"),
            Slot("intervention", "I", "Intervention",
                 "Intervention or exposure studied"),
            Slot("comparison", "C", "Comparison",
                 "Comparator or control condition, if the review defines one"),
            Slot("outcome", "O", "Outcome",
                 "Outcomes the review looks for"),
        ),
    ),
    Framework(
        key="picos", short="PICOS", label="PICOS", citation="",
        slots=(
            Slot("population", "P", "Population",
                 "Population or participants the review is about"),
            Slot("intervention", "I", "Intervention",
                 "Intervention or exposure studied"),
            Slot("comparison", "C", "Comparison",
                 "Comparator or control condition, if the review defines one"),
            Slot("outcome", "O", "Outcome",
                 "Outcomes the review looks for"),
            Slot("study_design", "S", "Study design",
                 "Study designs the review admits"),
        ),
    ),
    Framework(
        key="spider", short="SPIDER",
        label="SPIDER (Sample, Phenomenon of Interest, Design, Evaluation, "
              "Research type)",
        citation="Cooke, Smith & Booth, 2012",
        slots=(
            Slot("sample", "S", "Sample",
                 "The group studied — smaller and not meant to be "
                 "generalised, unlike a PICO population"),
            Slot("phenomenon_of_interest", "PI", "Phenomenon of interest",
                 "The behaviour, decision, experience or intervention the "
                 "review is about"),
            Slot("design", "D", "Design",
                 "Research design and theoretical framing of the studies "
                 "sought (interviews, focus groups, case studies…)"),
            Slot("evaluation", "E", "Evaluation",
                 "The outcome constructs, including subjective ones: views, "
                 "attitudes, perceptions, experiences"),
            Slot("research_type", "R", "Research type",
                 "Qualitative, quantitative or mixed methods"),
        ),
    ),
    Framework(
        key="spice", short="SPICE",
        label="SPICE (Setting, Perspective, Intervention, Comparison, "
              "Evaluation)",
        citation="Booth, 2006",
        slots=(
            Slot("setting", "S", "Setting", "Where the studies take place"),
            Slot("perspective", "P", "Perspective",
                 "Whose point of view the review takes"),
            Slot("intervention", "I", "Intervention",
                 "Intervention, exposure or service studied"),
            Slot("comparison", "C", "Comparison",
                 "Comparator, if the review defines one"),
            Slot("evaluation", "E", "Evaluation",
                 "How the effect or the experience is judged"),
        ),
    ),
    Framework(
        key="peo", short="PEO", label="PEO (Population, Exposure, Outcome)",
        citation="",
        slots=(
            Slot("population", "P", "Population",
                 "Population or participants the review is about"),
            Slot("exposure", "E", "Exposure",
                 "Exposure, determinant or phenomenon studied — no "
                 "intervention is implied"),
            Slot("outcome", "O", "Outcome",
                 "Outcomes or effects the review looks for"),
        ),
    ),
    # One pseudo-slot rather than none, so the schema builder and the renderer
    # stay branch-free.
    Framework(
        key="free", short="free", label="Free / adapted framing", citation="",
        slots=(
            Slot("framing_notes", "", "Framing",
                 "How the protocol frames its question and its perimeter, in "
                 "its own words"),
        ),
    ),
)


_REVIEW_TYPES: tuple[ReviewType, ...] = (
    ReviewType(
        key="systematic",
        label="Systematic review",
        citation="PRISMA 2020, Page et al., 2021",
        default_framework="picos",
        default_template="evidence_pico",
        context_line="Its findings are aggregated and reported against "
                     "pre-registered eligibility criteria.",
        guideline="PRISMA 2020",
        synthesis_method="narrative synthesis (Popay et al., 2006)",
        tooling_note="",
    ),
    ReviewType(
        key="best_fit",
        label="“Best fit” framework synthesis",
        citation="Carroll & Booth, 2013",
        default_framework="spider",
        default_template="best_fit",
        context_line="It codes the evidence against an a priori framework of "
                     "themes drawn from existing models or theories, and adds "
                     "new themes inductively for whatever the framework "
                     "cannot accommodate.",
        guideline="PRISMA 2020",
        synthesis_method="“best fit” framework synthesis "
                         "(Carroll, Booth, Leaviss & Rick, 2013), combining "
                         "framework synthesis with secondary thematic "
                         "analysis",
        tooling_note="The software ran one search strand and has no tool for "
                     "the a priori framework or for coding data against it; "
                     "that part of the method was carried out outside it and "
                     "recorded in the extraction table.",
    ),
)


FRAMEWORKS: dict[str, Framework] = {f.key: f for f in _FRAMEWORKS}
REVIEW_TYPES: dict[str, ReviewType] = {r.key: r for r in _REVIEW_TYPES}


def framework(key: str | None) -> Framework:
    """Never raises: an unknown key (older/newer instance, hand-edited
    snapshot) degrades to the default rather than breaking the project."""
    return FRAMEWORKS.get(key or "", FRAMEWORKS[DEFAULT_FRAMEWORK])


def review_type(key: str | None) -> ReviewType:
    return REVIEW_TYPES.get(key or "", REVIEW_TYPES[DEFAULT_REVIEW_TYPE])


def resolve(project) -> tuple[ReviewType, Framework]:
    """(review type, question framework) of a project — accepts None so call
    sites without a loaded project still get the defaults."""
    if project is None:
        return REVIEW_TYPES[DEFAULT_REVIEW_TYPE], FRAMEWORKS[DEFAULT_FRAMEWORK]
    return (review_type(getattr(project, "review_type", None)),
            framework(getattr(project, "question_framework", None)))


def review_context(project) -> str:
    """Framing block appended to an AI feature's instructions.

    It is deliberately *appended*, never merged into the editable instruction
    text: the shipped prompts (and any project override of them) speak PICO,
    and the last line of this block is what makes them defer to the project's
    own framing without either being rewritten.
    """
    rt, fw = resolve(project)
    type_line = f"- Review type: {rt.label} ({rt.citation})."
    if rt.context_line:
        type_line += f" {rt.context_line}"
    fw_line = f"- Question framework: {fw.short}"
    if fw.citation:
        fw_line += f" ({fw.citation})"
    fw_line += " — " + ", ".join(fw.slot_labels()) + "."
    return (
        "\n\nReview framing (set by this project):\n"
        f"{type_line}\n{fw_line}\n"
        "Where the instructions above use PICO vocabulary, use this framing's "
        "vocabulary instead."
    )
