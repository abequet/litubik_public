# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the appraisal of a corpus looks like, summarised for the Results page.

The headline is deliberately **per bias domain**, not a score. JBI's own
guidance and the Cochrane Handbook both advise against collapsing an appraisal
into a number: a study that fails randomisation and one that fails blinding can
score the same and mean entirely different things. So the summary answers "how
did this corpus do on allocation bias?" and keeps the count of met criteria as
a secondary, per-study figure.

Checklists whose questions sit in a single unnamed domain (the classic JBI
tools) have no domains to group by; those fall back to one row per question,
which is the same figure at a finer grain rather than an empty chart.

Everything is computed **per study** and only then folded. The Results page
cross-filters on the client (year range, designs, countries), so it has to be
able to re-fold the same rows over a subset without asking the server again —
`fold()` here and its twin in components/results/filtering.ts are the same
operation, and both start from the per-study rows.
"""
from sqlalchemy.orm import Session

from app.services.appraisal import core, instruments

ANSWERS = ("yes", "no", "unclear", "na")


def _blank() -> dict[str, int]:
    return {a: 0 for a in ANSWERS}


def _rows_spec(inst: instruments.Instrument, design: str | None) -> tuple[list[dict], str]:
    """The rows a design's checklist contributes, and at which grain."""
    domains = instruments.domains_of(inst, design)
    if not domains:
        return [], "domain"
    # A checklist with one unnamed domain carries no grouping to report; one
    # row per question says the same thing without inventing labels.
    if len(domains) == 1 and not (domains[0].get("label") or "").strip():
        return ([{"label": q["text"], "qids": [q["id"]]}
                 for q in domains[0]["questions"]], "question")
    return ([{"label": d["label"], "qids": [q["id"] for q in d["questions"]]}
             for d in domains], "domain")


def per_study(db: Session, project_id: int, record_ids: list[int],
              designs: dict[int, str | None]) -> dict[int, dict]:
    """{record_id: {design, granularity, rows: [{label, counts, answered}]}}.

    `answered` says whether this study said anything about the row at all — a
    study that skipped a domain must not be counted among those assessed on it.
    """
    inst = core.instrument_of(db, project_id)
    effective = core.effective_appraisals(db, record_ids)
    out: dict[int, dict] = {}
    for record_id, appraisal in effective.items():
        design = appraisal.get("design") or designs.get(record_id) or ""
        specs, granularity = _rows_spec(inst, design)
        if not specs:
            continue
        # a consensus has one set of answers; individual appraisals are pooled
        answer_sets = appraisal.get("all_answers") or [appraisal["answers"]]
        rows = []
        for spec in specs:
            counts = _blank()
            for answers in answer_sets:
                for qid in spec["qids"]:
                    entry = (answers or {}).get(qid)
                    answer = (str((entry or {}).get("answer", ""))
                              if isinstance(entry, dict) else "")
                    if answer in counts:
                        counts[answer] += 1
            rows.append({"label": spec["label"], "counts": counts,
                         "answered": sum(counts.values()) > 0,
                         "n_questions": len(spec["qids"])})
        out[record_id] = {"design": design, "granularity": granularity,
                          "rows": rows}
    return out


def fold(blocks: list[dict]) -> list[dict]:
    """Per-study rows -> one block per study design, answers pooled.

    Kept free of any database access so the client can run the same fold over
    a filtered subset; `blocks` is just the values of `per_study()`.
    """
    by_design: dict[str, list[dict]] = {}
    for block in blocks:
        by_design.setdefault(block["design"], []).append(block)

    out = []
    for design, studies in by_design.items():
        merged: dict[str, dict] = {}
        order: list[str] = []
        for study in studies:
            for row in study["rows"]:
                target = merged.get(row["label"])
                if target is None:
                    order.append(row["label"])
                    target = merged[row["label"]] = {
                        "label": row["label"], "counts": _blank(),
                        "n_questions": row["n_questions"], "n_studies": 0}
                for answer, n in row["counts"].items():
                    target["counts"][answer] += n
                if row["answered"]:
                    target["n_studies"] += 1
        out.append({
            "design": design,
            "design_label": instruments.DESIGNS.get(design, design),
            "granularity": studies[0]["granularity"],
            "n_studies": len(studies),
            "rows": [merged[label] for label in order],
        })
    out.sort(key=lambda b: -b["n_studies"])
    return out
