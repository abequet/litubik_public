# SPDX-FileCopyrightText: 2026 Université Gustave Eiffel
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Effect sizes per study for one outcome (roadmap chantier 10) — the bridge
to a meta-analysis done elsewhere (R/metafor, RevMan Web).

Pure arithmetic, no pooling: LitUbik computes each study's estimate and
variance from the extraction cells an outcome's `effect_spec` maps to, and
hands the table over. The formulas follow metafor's `escalc()` so a reader
can reproduce every number: SMD = Hedges' g with the small-sample
correction, MD, log OR, log RR, Fisher's z (ZCOR). Missing or unusable cells
are reported per study rather than silently dropped.
"""
import math

from sqlalchemy.orm import Session

from app.models import ExtractionColumn, ExtractionValue, SynthesisOutcome
from app.services.results.compute import consensus_cell, first_author
from app.services.synthesis.core import contributing_studies

MEASURES = {
    "SMD": {"label": "Standardised mean difference (Hedges' g)",
            "roles": ("n_i", "mean_i", "sd_i", "n_c", "mean_c", "sd_c"),
            "kind": "continuous", "log": False},
    "MD": {"label": "Mean difference",
           "roles": ("n_i", "mean_i", "sd_i", "n_c", "mean_c", "sd_c"),
           "kind": "continuous", "log": False},
    "OR": {"label": "Odds ratio (log scale)",
           "roles": ("events_i", "n_i", "events_c", "n_c"),
           "kind": "dichotomous", "log": True},
    "RR": {"label": "Risk ratio (log scale)",
           "roles": ("events_i", "n_i", "events_c", "n_c"),
           "kind": "dichotomous", "log": True},
    "COR": {"label": "Correlation (Fisher's z)",
            "roles": ("r", "n"), "kind": "correlation", "log": False},
}
ROLE_LABELS = {
    "n_i": "N (intervention)", "mean_i": "Mean (intervention)",
    "sd_i": "SD (intervention)", "n_c": "N (control)", "mean_c": "Mean (control)",
    "sd_c": "SD (control)", "events_i": "Events (intervention)",
    "events_c": "Events (control)", "r": "Correlation r", "n": "N",
}
Z95 = 1.959963984540054


class EffectError(ValueError):
    pass


# ---- formulas (metafor escalc) ------------------------------------------------------

def smd(n_i, mean_i, sd_i, n_c, mean_c, sd_c) -> tuple[float, float]:
    if n_i < 2 or n_c < 2:
        raise EffectError("each group needs at least two participants")
    if sd_i < 0 or sd_c < 0:
        raise EffectError("a standard deviation cannot be negative")
    df = n_i + n_c - 2
    pooled = math.sqrt(((n_i - 1) * sd_i ** 2 + (n_c - 1) * sd_c ** 2) / df)
    if pooled == 0:
        raise EffectError("both standard deviations are zero")
    d = (mean_i - mean_c) / pooled
    j = 1 - 3 / (4 * df - 1)          # Hedges' small-sample correction
    g = j * d
    vi = 1 / n_i + 1 / n_c + g ** 2 / (2 * (n_i + n_c))
    return g, vi


def md(n_i, mean_i, sd_i, n_c, mean_c, sd_c) -> tuple[float, float]:
    if n_i < 1 or n_c < 1:
        raise EffectError("each group needs at least one participant")
    return mean_i - mean_c, sd_i ** 2 / n_i + sd_c ** 2 / n_c


def log_or(events_i, n_i, events_c, n_c) -> tuple[float, float]:
    a, b, c, d = events_i, n_i - events_i, events_c, n_c - events_c
    if min(a, b, c, d) < 0:
        raise EffectError("events exceed the group size")
    if 0 in (a, b, c, d):
        # metafor's default continuity correction (add 1/2 when a cell is 0)
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    return math.log((a * d) / (b * c)), 1 / a + 1 / b + 1 / c + 1 / d


def log_rr(events_i, n_i, events_c, n_c) -> tuple[float, float]:
    a, c = events_i, events_c
    if a > n_i or c > n_c or min(a, c, n_i, n_c) < 0:
        raise EffectError("events exceed the group size")
    if a == 0 or c == 0:
        a, c, n_i, n_c = a + 0.5, c + 0.5, n_i + 1, n_c + 1
    return (math.log((a / n_i) / (c / n_c)),
            1 / a - 1 / n_i + 1 / c - 1 / n_c)


def fisher_z(r, n) -> tuple[float, float]:
    if not -1 < r < 1:
        raise EffectError("r must lie strictly between -1 and 1")
    if n < 4:
        raise EffectError("n must be at least 4")
    return math.atanh(r), 1 / (n - 3)


FORMULAS = {"SMD": smd, "MD": md, "OR": log_or, "RR": log_rr, "COR": fisher_z}


def confidence(yi: float, vi: float, measure: str) -> dict:
    """95 % CI, plus the back-transformed values for the log-scale measures."""
    se = math.sqrt(vi)
    low, high = yi - Z95 * se, yi + Z95 * se
    out = {"yi": yi, "vi": vi, "se": se, "ci_low": low, "ci_high": high}
    if MEASURES[measure]["log"]:
        out.update({"estimate": math.exp(yi), "estimate_low": math.exp(low),
                    "estimate_high": math.exp(high)})
    elif measure == "COR":
        out.update({"estimate": math.tanh(yi), "estimate_low": math.tanh(low),
                    "estimate_high": math.tanh(high)})
    else:
        out.update({"estimate": yi, "estimate_low": low, "estimate_high": high})
    return out


# ---- spec + computation --------------------------------------------------------------

def clean_spec(db: Session, project_id: int, raw: dict | None) -> dict:
    """Validate {measure, mapping: {role: column_id}} against the project's
    numeric columns; an empty measure clears the spec."""
    if not raw or not raw.get("measure"):
        return {}
    measure = str(raw["measure"]).upper()
    if measure not in MEASURES:
        raise EffectError(f"Unknown measure {measure}")
    numeric = {c.id: c for c in db.query(ExtractionColumn)
               .filter_by(project_id=project_id, col_type="number")}
    mapping: dict[str, int] = {}
    for role in MEASURES[measure]["roles"]:
        cid = (raw.get("mapping") or {}).get(role)
        if cid in (None, ""):
            continue
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            raise EffectError(f"Column for {role} must be a column id")
        if cid not in numeric:
            raise EffectError(f"Column {cid} is not a numeric column of this project")
        mapping[role] = cid
    return {"measure": measure, "mapping": mapping}


def compute(db: Session, outcome: SynthesisOutcome) -> dict:
    """Per-study effect sizes of an outcome, from the consensus cells of the
    mapped columns. Studies whose inputs are missing or invalid are listed
    with the reason, never dropped."""
    spec = outcome.effect_spec or {}
    measure = spec.get("measure")
    mapping: dict[str, int] = spec.get("mapping") or {}
    studies = contributing_studies(db, outcome)
    roles = MEASURES[measure]["roles"] if measure else ()
    missing_roles = [r for r in roles if r not in mapping]
    column_ids = list(dict.fromkeys(mapping.values()))
    cells: dict[tuple[int, int], list[ExtractionValue]] = {}
    if column_ids and studies:
        for v in (db.query(ExtractionValue)
                  .filter(ExtractionValue.column_id.in_(column_ids),
                          ExtractionValue.study_id.in_([s.id for s, _, _ in studies]))):
            cells.setdefault((v.study_id, v.column_id), []).append(v)
    rows = []
    n_computed = 0
    for study, record, n_studies in studies:
        label = first_author(record) or record.title[:30]
        if record.year:
            label = f"{label} {record.year}"
        if n_studies > 1:
            label = f"{label} – {study.label}"
        raw: dict[str, float | None] = {}
        problems: list[str] = []
        for role in roles:
            cid = mapping.get(role)
            if cid is None:
                raw[role] = None
                continue
            value, status = consensus_cell(cells.get((study.id, cid), []))
            if status == "ok" and isinstance(value, (int, float)) \
                    and not isinstance(value, bool):
                # integral counts stay integers in the exports (123, not 123.0)
                raw[role] = int(value) if float(value).is_integer() else float(value)
            else:
                raw[role] = None
                problems.append(f"{ROLE_LABELS[role]}: "
                                + ("conflicting values" if status == "conflict"
                                   else "missing"))
        row = {"study_id": study.id, "record_id": record.id, "label": label,
               "doi": record.doi, "year": record.year,
               "design": study.study_design, "raw": raw, "problems": problems}
        if measure and not missing_roles and not problems:
            try:
                yi, vi = FORMULAS[measure](*[raw[r] for r in roles])
                row.update(confidence(yi, vi, measure))
                n_computed += 1
            except (EffectError, ValueError, ZeroDivisionError) as e:
                row["problems"] = [str(e)]
        rows.append(row)
    columns = {cid: name for cid, name in
               db.query(ExtractionColumn.id, ExtractionColumn.name)
               .filter(ExtractionColumn.id.in_(column_ids))} if column_ids else {}
    return {
        "outcome_id": outcome.id, "label": outcome.label,
        "comparison": outcome.comparison,
        "measure": measure, "measure_label": MEASURES[measure]["label"] if measure else "",
        "kind": MEASURES[measure]["kind"] if measure else "",
        "log_scale": bool(measure and MEASURES[measure]["log"]),
        "mapping": {role: {"column_id": cid, "column_name": columns.get(cid, "")}
                    for role, cid in mapping.items()},
        "roles": list(roles), "role_labels": {r: ROLE_LABELS[r] for r in roles},
        "missing_roles": missing_roles,
        "studies": rows, "n_studies": len(rows), "n_computed": n_computed,
    }


# ---- exports ----------------------------------------------------------------------------

def tidy_rows(result: dict) -> tuple[list[str], list[list]]:
    """Long/tidy table: one line per study with the raw inputs and yi/vi —
    what `rma(yi, vi, data=...)` reads."""
    roles = result["roles"]
    header = ["outcome_id", "outcome", "comparison", "measure", "study_id",
              "study_label", "record_id", "doi", "year", "design",
              *roles, "yi", "vi", "ci_low", "ci_high", "problems"]
    body = []
    for s in result["studies"]:
        body.append([result["outcome_id"], result["label"], result["comparison"],
                     result["measure"] or "", s["study_id"], s["label"],
                     s["record_id"], s["doi"] or "", s["year"] or "", s["design"] or "",
                     *[("" if s["raw"].get(r) is None else s["raw"][r]) for r in roles],
                     s.get("yi", ""), s.get("vi", ""), s.get("ci_low", ""),
                     s.get("ci_high", ""), "; ".join(s["problems"])])
    return header, body


def r_script(result: dict) -> str:
    """analysis.R: reads data.csv, recomputes the effects with escalc() when
    the raw inputs are there (a check against LitUbik's numbers), fits a
    random-effects model, draws the forest and funnel plots."""
    measure = result["measure"] or "SMD"
    roles = result["roles"]
    esc = {
        "SMD": "escalc(measure = \"SMD\", m1i = mean_i, sd1i = sd_i, n1i = n_i, "
               "m2i = mean_c, sd2i = sd_c, n2i = n_c, data = d)",
        "MD": "escalc(measure = \"MD\", m1i = mean_i, sd1i = sd_i, n1i = n_i, "
              "m2i = mean_c, sd2i = sd_c, n2i = n_c, data = d)",
        "OR": "escalc(measure = \"OR\", ai = events_i, n1i = n_i, ci = events_c, "
              "n2i = n_c, data = d)",
        "RR": "escalc(measure = \"RR\", ai = events_i, n1i = n_i, ci = events_c, "
              "n2i = n_c, data = d)",
        "COR": "escalc(measure = \"ZCOR\", ri = r, ni = n, data = d)",
    }[measure]
    label = result["label"].replace('"', "'")
    return f'''# LitUbik → metafor bridge — outcome "{label}"
# Generated by LitUbik: one row per study, effect sizes computed as metafor's
# escalc() does ({measure}). No pooling was done in LitUbik; the model below is
# yours to choose and justify.
library(metafor)

d <- read.csv("data.csv", stringsAsFactors = FALSE)
d <- d[!is.na(d$yi) & d$yi != "", ]
d$yi <- as.numeric(d$yi)
d$vi <- as.numeric(d$vi)

# Recompute from the raw inputs ({", ".join(roles)}) and compare with LitUbik's yi/vi
if (all(c({", ".join(f'"{r}"' for r in roles)}) %in% names(d))) {{
  check <- {esc}
  print(cbind(study = d$study_label, litubik_yi = d$yi, escalc_yi = check$yi))
}}

# Random-effects model (REML); switch to method = "FE" for a fixed-effect model
res <- rma(yi, vi, data = d, slab = study_label, method = "REML")
print(res)

forest(res, header = TRUE{", atransf = exp" if result["log_scale"] else ""})
funnel(res)
'''


def revman_rows(result: dict) -> tuple[list[str], list[list]]:
    """RevMan Web study-results layout: one row per arm per study, the Study
    ID matching the review's included studies. RevMan Web generates its own
    template per review (the header row must not change), so this file is
    laid out like that template and renamed/mapped on import; correlations
    have no arm layout and yield no row."""
    header = ["Study ID", "Outcome", "Arm", "Total", "Events", "Mean", "SD"]
    body: list[list] = []
    kind = result["kind"]
    for s in result["studies"]:
        raw = s["raw"]
        if kind == "continuous":
            body.append([s["label"], result["label"], "Intervention",
                         raw.get("n_i", ""), "", raw.get("mean_i", ""), raw.get("sd_i", "")])
            body.append([s["label"], result["label"], "Control",
                         raw.get("n_c", ""), "", raw.get("mean_c", ""), raw.get("sd_c", "")])
        elif kind == "dichotomous":
            body.append([s["label"], result["label"], "Intervention",
                         raw.get("n_i", ""), raw.get("events_i", ""), "", ""])
            body.append([s["label"], result["label"], "Control",
                         raw.get("n_c", ""), raw.get("events_c", ""), "", ""])
    return header, [[("" if v is None else v) for v in row] for row in body]
