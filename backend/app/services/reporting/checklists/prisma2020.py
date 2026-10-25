"""The PRISMA 2020 checklist, pre-filled from what the review actually did.

CREST_Triage lists, among the problems it flags, "self-declared compliance with
standard rather than analysis thereof" — an author who writes "we followed
PRISMA" and leaves it there. LitUbik is in an unusual position to answer that
better than a declaration: it recorded the work as it happened, so for a good
half of the checklist it can show the *fact* rather than a tick.

Each item resolves to one of four states:

- `evidenced`  — the pipeline recorded it; the fact is shown, and where it
                 came from.
- `author`     — outside the app by nature (funding, competing interests,
                 discussion). The author writes it and notes the page.
- `not_done`   — the app knows the stage never ran. This is the state that
                 makes the file worth having: an empty cell reads as an
                 oversight, "not done" reads as a finding.
- `n_a`        — the item does not apply to this review.

Nothing here judges the review. `evidenced` says "this is what happened", never
"this is adequate" — that judgement is the editor's, and manufacturing it would
be the same self-declaration the file is meant to replace.

Reference: Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 statement:
an updated guideline for reporting systematic reviews. BMJ 2021;372:n71. The
checklist item wording below is the PRISMA authors' work, reproduced with
attribution under CC BY 4.0: it is NOT covered by the AGPL licence of LitUbik
(see NOTICE).
"""
from dataclasses import dataclass
from typing import Callable

EVIDENCED = "evidenced"
AUTHOR = "author"
NOT_DONE = "not_done"
NOT_APPLICABLE = "n_a"


@dataclass(frozen=True)
class Item:
    number: str
    section: str
    text: str
    # (dossier) -> (status, fact). None means "always the author's".
    resolve: Callable[[dict], tuple[str, str]] | None = None


def _author(_: dict) -> tuple[str, str]:
    return AUTHOR, ""


def _n(value) -> int:
    return value if isinstance(value, int) else 0


# -- resolvers ----------------------------------------------------------------
# Each reads the dossier assembled by services/reporting/audit.py and returns
# what the review can show for that item. They are deliberately terse: the
# sentence lands in a spreadsheet cell a journal editor reads.

def _eligibility(d: dict) -> tuple[str, str]:
    protocol = d["protocol"]
    if not protocol.get("imported"):
        return NOT_DONE, "No protocol was imported into the app."
    n_in, n_ex = protocol.get("n_include", 0), protocol.get("n_exclude", 0)
    return EVIDENCED, (
        f"{n_in} inclusion and {n_ex} exclusion criteria, coded I*/E* and used "
        f"as the exclusion reasons at screening"
        + (f"; protocol version {protocol['version']} validated on "
           f"{(protocol.get('validated_at') or '')[:10]}"
           if protocol.get("validated") else "; protocol never validated"))


def _sources(d: dict) -> tuple[str, str]:
    imports = d["search"]["imports"]
    if not imports:
        return NOT_DONE, "No search results have been imported."
    names = sorted({i["source"] for i in imports if i["type"] == "database"})
    last = d["search"].get("last_import_at") or ""
    parts = [f"Databases searched: {', '.join(names)}" if names
             else "No database source recorded"]
    n_snow = d["snowballing"]["n_iterations"]
    if n_snow:
        parts.append(f"{n_snow} snowballing iteration(s)")
    if last:
        parts.append(f"last import {last[:10]}")
    return EVIDENCED, "; ".join(parts)


def _search_strategy(d: dict) -> tuple[str, str]:
    equations = d["search"]["equations"]
    if not equations:
        return NOT_DONE, "No search equation was built in the app."
    frozen = d["search"].get("frozen_equation")
    with_queries = [e for e in equations if e["queries_per_database"]]
    n_queries = sum(len(e["queries_per_database"]) for e in equations)
    hand = sorted({db for e in equations for db in e["hand_edited_queries"]})
    fact = (f"{n_queries} full query string(s) recorded verbatim across "
            f"{len(with_queries)} equation variant(s)")
    if frozen:
        fact += f"; the frozen variant is “{frozen}”"
    else:
        fact += "; no variant was frozen"
    if hand:
        fact += f"; hand-edited for {', '.join(hand)}"
    return EVIDENCED, fact


def _selection_process(d: dict) -> tuple[str, str]:
    rounds = d["screening"]["ta"] + d["screening"]["ft"]
    active = [r for r in rounds if r["status"] == "active"]
    if not active:
        return NOT_DONE, "No screening round was run in the app."
    parts = []
    for r in active:
        kappa = r["agreement"].get("kappa")
        bit = (f"{r['n_reviewers']} reviewer(s), allocation “{r['allocation']}”, "
               f"conflicts settled by {r['conflict_resolution']}")
        if kappa is not None:
            bit += (f", κ = {kappa:.2f} on "
                    f"{r['agreement'].get('n_double_screened', 0)} "
                    f"double-screened records")
            if r["agreement"].get("maybe_counted_as_include"):
                bit += " (“maybe” counted with “include”)"
        if r["n_excluded_by_validated_ai_triage"]:
            bit += (f", {r['n_excluded_by_validated_ai_triage']} excluded via "
                    f"human-validated AI title triage")
        parts.append(bit)
    return EVIDENCED, ("Votes are hidden from other reviewers until cast "
                       "(enforced server-side). " + " | ".join(parts))


def _data_collection(d: dict) -> tuple[str, str]:
    extraction = d["extraction"]
    if not extraction["started"]:
        return NOT_DONE, "Extraction has not been started in the app."
    cells = extraction["cells"]
    return EVIDENCED, (
        f"{extraction['n_extractors']} extractor(s), "
        + ("each report extracted twice" if extraction["double_extraction"]
           else "one extraction per report")
        + f"; {extraction['n_columns']} extraction columns; "
        + f"{cells['ai_prefilled']} AI-prefilled cells of which "
          f"{cells['ai_prefilled_validated']} validated by a human")


def _data_items_outcomes(d: dict) -> tuple[str, str]:
    synthesis = d["synthesis"]
    if not synthesis.get("declared") or not synthesis.get("outcomes"):
        return NOT_DONE, ("No outcome was declared in the synthesis stage, so "
                          "the app cannot say which outcomes were sought.")
    labels = [o["label"] for o in synthesis["outcomes"]]
    return EVIDENCED, f"{len(labels)} outcome(s) declared: {', '.join(labels)}"


def _data_items_other(d: dict) -> tuple[str, str]:
    columns = d["extraction"]["columns"]
    if not columns:
        return NOT_DONE, "No extraction column was defined."
    return EVIDENCED, ("Variables collected: "
                       + ", ".join(c["name"] for c in columns))


def _risk_of_bias_method(d: dict) -> tuple[str, str]:
    appraisal = d["extraction"].get("appraisal") or d["extraction"]["jbi"]
    if not appraisal["n_appraised"]:
        return NOT_DONE, ("No study was critically appraised. Editorial triage "
                          "treats a missing appraisal as a prohibitive gap.")
    return EVIDENCED, (
        f"{appraisal['instrument']}, applied to {appraisal['n_appraised']} "
        f"study(ies). {appraisal['note']}")


def _effect_measures(d: dict) -> tuple[str, str]:
    outcomes = d["synthesis"].get("outcomes") or []
    metrics = sorted({o["metric"] for o in outcomes if o.get("metric")})
    if not metrics:
        return NOT_DONE, ("No standardised metric was declared for any "
                          "outcome (SWiM item 2).")
    return EVIDENCED, "Effect measures: " + ", ".join(metrics)


def _synthesis_methods(d: dict) -> tuple[str, str]:
    synthesis = d["synthesis"]
    if not synthesis.get("declared"):
        return NOT_DONE, (
            "The synthesis was not declared in the app. "
            f"“{synthesis.get('method_default', '')}” is the method typical of "
            f"this review type, not a record of what was done.")
    methods = synthesis.get("methods_declared") or []
    fact = "Synthesis methods declared: " + ", ".join(methods)
    if synthesis.get("grouping"):
        fact += "; grouping and its rationale recorded (SWiM 1a)"
    if synthesis.get("grouping_changes"):
        fact += "; changes since the protocol recorded (SWiM 1b)"
    return EVIDENCED, fact


def _reporting_bias_method(d: dict) -> tuple[str, str]:
    """PRISMA 14 asks how the risk of bias *due to missing results* was
    assessed. The app holds the publication-bias domain of GRADE, which is the
    closest thing it records."""
    if d["synthesis"].get("certainty_framework") in (None, "", "none"):
        return NOT_DONE, ("No certainty framework was applied, so no "
                          "publication-bias judgement was recorded.")
    return EVIDENCED, ("Assessed as the publication-bias domain of the "
                       "certainty rating, per outcome.")


def _certainty_method(d: dict) -> tuple[str, str]:
    synthesis = d["synthesis"]
    framework = synthesis.get("certainty_framework")
    if framework in (None, "", "none"):
        return NOT_DONE, ("The certainty of the evidence was not formally "
                          "assessed. This is a methodological expectation of "
                          "Cochrane reviews and a domain editors triage on.")
    return EVIDENCED, (
        f"{synthesis.get('certainty_framework_label', framework)}, rated per "
        f"outcome over the studies contributing to that outcome "
        f"({synthesis.get('n_outcomes_rated', 0)} of "
        f"{synthesis.get('n_outcomes', 0)} outcomes rated).")


def _study_selection_results(d: dict) -> tuple[str, str]:
    prisma = d["prisma"]
    identified = _n(prisma.get("n_databases")) + _n(prisma.get("n_other"))
    if not identified:
        return NOT_DONE, "No record has been imported."
    return EVIDENCED, (
        f"PRISMA flow computed live from the tables: {identified} identified, "
        f"{_n(prisma.get('duplicates_removed'))} duplicates removed, "
        f"{_n(prisma.get('studies_included'))} studies included.")


def _excluded_reports(d: dict) -> tuple[str, str]:
    ft = [r for r in d["screening"]["ft"] if r["status"] == "active"]
    reasons = [x for r in ft for x in r.get("excluded_by_reason", [])]
    if not reasons:
        return NOT_DONE, "No full-text exclusion reason was recorded."
    return EVIDENCED, "; ".join(f"{r['label']} (n={r['n']})" for r in reasons)


def _study_characteristics(d: dict) -> tuple[str, str]:
    if not d["extraction"]["started"]:
        return NOT_DONE, "The extraction table is empty."
    return EVIDENCED, ("The extraction table is the characteristics table; "
                       "exportable as CSV/XLSX from the Extraction page.")


def _rob_results(d: dict) -> tuple[str, str]:
    appraisal = d["extraction"].get("appraisal") or d["extraction"]["jbi"]
    if not appraisal["n_appraised"]:
        return NOT_DONE, "No appraisal was performed."
    return EVIDENCED, (f"Per-domain judgements for {appraisal['n_appraised']} "
                       f"study(ies), on the Results page and in the appraisal "
                       f"export.")


def _synthesis_results(d: dict) -> tuple[str, str]:
    outcomes = d["synthesis"].get("outcomes") or []
    if not outcomes:
        return NOT_DONE, "No outcome was declared, so no synthesis result exists."
    return EVIDENCED, (f"{len(outcomes)} result(s) in the Summary of Findings "
                       f"table, each with its contributing studies.")


def _certainty_results(d: dict) -> tuple[str, str]:
    synthesis = d["synthesis"]
    rated = synthesis.get("n_outcomes_rated", 0)
    total = synthesis.get("n_outcomes", 0)
    if not total:
        return NOT_DONE, "No outcome was declared."
    if not rated:
        return NOT_DONE, f"None of the {total} declared outcomes was rated."
    return EVIDENCED, (f"{rated} of {total} outcomes carry a certainty rating "
                       f"and a plain-language statement.")


def _registration(d: dict) -> tuple[str, str]:
    reg = d["registration"]
    if reg["state"] == "registered":
        return EVIDENCED, (
            f"{reg['registry_label']} {reg['identifier']}"
            + (f", registered {reg['registered_at'][:10]}"
               if reg.get("registered_at") else "")
            + (f" — {reg['url']}" if reg.get("url") else ""))
    if reg["state"] == "not_registered":
        return EVIDENCED, "The team declared that the review was not registered."
    return NOT_DONE, ("Nobody answered whether the review was registered. "
                      "PRISMA requires the register and number, or an explicit "
                      "statement that it was not registered.")


def _protocol_access(d: dict) -> tuple[str, str]:
    reg = d["registration"]
    if reg.get("protocol_url"):
        return EVIDENCED, f"Protocol available at {reg['protocol_url']}"
    if d["protocol"].get("validated"):
        return AUTHOR, ("A protocol was validated in the app on "
                        f"{(d['protocol'].get('validated_at') or '')[:10]}, but "
                        f"no public URL was recorded — say where it can be "
                        f"read, or that it is not public.")
    return NOT_DONE, "No protocol was validated in the app."


def _amendments(d: dict) -> tuple[str, str]:
    dev = d["deviations"]
    if dev["n_declared"]:
        return EVIDENCED, (f"{dev['n_declared']} amendment(s) declared with "
                           f"their reasons.")
    if dev["n_detected_unanswered"]:
        return NOT_DONE, (
            f"{dev['n_detected_unanswered']} change(s) the pipeline noticed "
            f"are still unanswered — say whether they were amendments.")
    return AUTHOR, ("No amendment was declared and none was detected. State "
                    "that the review followed its protocol, rather than "
                    "leaving the item blank.")


ITEMS: tuple[Item, ...] = (
    Item("1", "Title", "Identify the report as a systematic review."),
    Item("2", "Abstract", "See the PRISMA 2020 for Abstracts checklist."),
    Item("3", "Introduction",
         "Describe the rationale for the review in the context of existing "
         "knowledge."),
    Item("4", "Introduction",
         "Provide an explicit statement of the objective(s) or question(s) "
         "the review addresses."),
    Item("5", "Methods",
         "Specify the inclusion and exclusion criteria for the review and how "
         "studies were grouped for the syntheses.", _eligibility),
    Item("6", "Methods",
         "Specify all databases, registers, websites, organisations, "
         "reference lists and other sources searched, and the date each was "
         "last searched.", _sources),
    Item("7", "Methods",
         "Present the full search strategies for all databases, registers and "
         "websites, including any filters and limits used.", _search_strategy),
    Item("8", "Methods",
         "Specify the methods used to decide whether a study met the "
         "inclusion criteria, including how many reviewers screened each "
         "record and whether they worked independently.", _selection_process),
    Item("9", "Methods",
         "Specify the methods used to collect data from reports, including "
         "how many reviewers collected data from each report and whether they "
         "worked independently.", _data_collection),
    Item("10a", "Methods",
         "List and define all outcomes for which data were sought.",
         _data_items_outcomes),
    Item("10b", "Methods",
         "List and define all other variables for which data were sought.",
         _data_items_other),
    Item("11", "Methods",
         "Specify the methods used to assess risk of bias in the included "
         "studies, including details of the tool(s) used and how many "
         "reviewers assessed each study.", _risk_of_bias_method),
    Item("12", "Methods",
         "Specify for each outcome the effect measure(s) used in the "
         "synthesis or presentation of results.", _effect_measures),
    Item("13a", "Methods",
         "Describe the processes used to decide which studies were eligible "
         "for each synthesis.", _synthesis_methods),
    Item("13b", "Methods",
         "Describe any methods required to prepare the data for presentation "
         "or synthesis.", _synthesis_methods),
    Item("13c", "Methods",
         "Describe any methods used to tabulate or visually display results "
         "of individual studies and syntheses.", _synthesis_methods),
    Item("13d", "Methods",
         "Describe any methods used to synthesise results and provide a "
         "rationale for the choice(s).", _synthesis_methods),
    Item("13e", "Methods",
         "Describe any methods used to explore possible causes of "
         "heterogeneity among study results.", _synthesis_methods),
    Item("13f", "Methods",
         "Describe any sensitivity analyses conducted to assess robustness of "
         "the synthesised results.", _author),
    Item("14", "Methods",
         "Describe any methods used to assess risk of bias due to missing "
         "results in a synthesis.", _reporting_bias_method),
    Item("15", "Methods",
         "Describe any methods used to assess certainty (or confidence) in "
         "the body of evidence for an outcome.", _certainty_method),
    Item("16a", "Results",
         "Describe the results of the search and selection process, ideally "
         "using a flow diagram.", _study_selection_results),
    Item("16b", "Results",
         "Cite studies that met many but not all inclusion criteria and "
         "explain why they were excluded.", _excluded_reports),
    Item("17", "Results",
         "Cite each included study and present its characteristics.",
         _study_characteristics),
    Item("18", "Results",
         "Present assessments of risk of bias for each included study.",
         _rob_results),
    Item("19", "Results",
         "For all outcomes, present for each study a summary statistic and "
         "its precision, and effect estimates.", _author),
    Item("20a", "Results",
         "For each synthesis, briefly summarise the characteristics and risk "
         "of bias among contributing studies.", _synthesis_results),
    Item("20b", "Results",
         "Present results of all statistical syntheses conducted.",
         _synthesis_results),
    Item("20c", "Results",
         "Present results of all investigations of possible causes of "
         "heterogeneity among study results.", _author),
    Item("20d", "Results",
         "Present results of all sensitivity analyses conducted.", _author),
    Item("21", "Results",
         "Present assessments of risk of bias due to missing results for each "
         "synthesis assessed.", _reporting_bias_method),
    Item("22", "Results",
         "Present assessments of certainty (or confidence) in the body of "
         "evidence for each outcome assessed.", _certainty_results),
    Item("23a", "Discussion",
         "Provide a general interpretation of the results in the context of "
         "other evidence."),
    Item("23b", "Discussion", "Discuss any limitations of the evidence."),
    Item("23c", "Discussion",
         "Discuss any limitations of the review processes used."),
    Item("23d", "Discussion",
         "Discuss implications of the results for practice, policy and future "
         "research."),
    Item("24a", "Other information",
         "Provide registration information for the review, including register "
         "name and registration number, or state that the review was not "
         "registered.", _registration),
    Item("24b", "Other information",
         "Indicate where the review protocol can be accessed, or state that a "
         "protocol was not prepared.", _protocol_access),
    Item("24c", "Other information",
         "Describe and explain any amendments to information provided at "
         "registration or in the protocol.", _amendments),
    Item("25", "Other information",
         "Describe sources of financial or non-financial support for the "
         "review, and the role of the funders."),
    Item("26", "Other information",
         "Declare any competing interests of review authors."),
    Item("27", "Other information",
         "Report which of the following are publicly available and where: "
         "template data collection forms; data extracted; data used for all "
         "analyses; analytic code; any other materials."),
)

CITATION = ("Page MJ, McKenzie JE, Bossuyt PM, et al. The PRISMA 2020 "
            "statement: an updated guideline for reporting systematic "
            "reviews. BMJ 2021;372:n71.")


def evaluate(dossier: dict) -> list[dict]:
    """The checklist, resolved against one review's audit trail."""
    rows = []
    for item in ITEMS:
        if item.resolve is None:
            status, fact = AUTHOR, ""
        else:
            try:
                status, fact = item.resolve(dossier)
            except (KeyError, TypeError):
                # A dossier from a stage this version does not know about must
                # not take the whole checklist down with it.
                status, fact = AUTHOR, ""
        rows.append({"number": item.number, "section": item.section,
                     "text": item.text, "status": status, "fact": fact})
    return rows
