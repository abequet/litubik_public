# Extraction, results and PRISMA

## Data extraction

The **Extraction** step is a structured table over the included papers. The
project admin defines the columns (free text, numbers, single/multiple
choice…); AI can suggest the column set from your protocol, and prefill
cells from the PDFs — every AI-prefilled value stays marked until a human
validates it. Critical appraisal has its own tab (see below).

**Starter templates.** *Column helpers* offers three ready-made column sets:
the standard **evidence table (PICO)**, an **evidence table (qualitative /
SPIDER)** for reviews of views, experiences and determinants, and a **"best
fit" framework synthesis** set that adds the columns keeping such a synthesis
traceable (which *a priori* theme a finding was coded against, whether the
framework accommodated it, the emergent theme when it did not, and where the
finding came from). The one your review type suggests is highlighted, but any
of them can be picked and mixed — a template only ever adds the columns whose
name is not already used.

**Several studies in one article.** An article sometimes reports more than
one study (two experiments, two cohorts, a pilot and a trial). Click **+
study** under the article's title to add a row per study: each has its own
label, design, cells and critical appraisal, and the exports write one line
per study (a *Study* column tells them apart). The first study cannot be
removed; the others can, with their values. The Results page then counts
articles and studies separately, synthesis outcomes pick contributing
*studies*, and the PRISMA figure shows both "studies included" and "reports
of included studies". An imported extraction table can carry a *Study*
column; without one, several rows matching the same article become its
successive studies. The AI prefill answers one entry per study it finds in
the PDF and only ever adds studies, never removes one.

## Critical appraisal

The **Critical appraisal** tab appraises each included study against a
checklist chosen by its study design — so qualify the design first (by hand,
or with the AI suggestion, from the Table tab).

**Which instrument.** LitUbik ships two instruments whose terms allow it:
the **JBI** critical-appraisal checklists and the **MMAT 2018** (Mixed
Methods Appraisal Tool, Hong et al., free for education and research). Pick
one in *Project settings → Appraisal*. Redistributing any other
organisation's tool is a licensing decision, not a packaging one, so a team
using another declares **its own instrument** there — a name, a citation, and
one checklist per study design whose questions are grouped in domains. The
appraisal form, the per-domain chart, the exports and the Methods draft read
every instrument the same way, and the Methods draft cites the one actually
in use.

**MMAT specifics.** The MMAT rates each study on the five criteria of its
category — qualitative, randomized, non-randomized (quasi-experimental,
cohort, case-control), descriptive (cross-sectional, case report) or mixed
methods — preceded by two optional screening questions. Answers are *yes*,
*no* or *can't tell*. There is **no overall score and no include/exclude
judgement**: the tool's guide discourages collapsing the ratings into a
number, so LitUbik shows no score, the Results page keeps the per-criterion
view only, and an appraisal counts as complete once the five criteria are
rated. A mixed-methods study is rated on criteria 5.1–5.5 *and* on the
qualitative and quantitative component criteria (criterion 5.5 is judged
from them): the form lists the component blocks as optional; fill the
quantitative one that applies. The criteria are reproduced without the
guide's explanations — read the user guide before appraising. Systematic
reviews and "other" designs have no MMAT category.

**One assessor or two.** By default any member appraises any study and nothing
is compared. In *Project settings → Appraisal* you can require **two
independent assessors**, choose what counts as a disagreement (the overall
judgement only, or any individual question) and who settles it (the assessors
by consensus, or a project admin as arbiter). A **Disagreements** tab then
lists the studies where the two diverge, side by side.

Settling a disagreement never overwrites what either assessor said: the
agreed appraisal is stored as its own record, and both individual appraisals
stay visible. That matters beyond bookkeeping — a reader is entitled to know
that two assessors read a study differently. The agreed appraisal is the one
the Results page and the exports count.

Independent duplicate appraisal, or its absence, goes into the Methods draft
either way. Editorial triage tools look for it explicitly, so an appraisal by
a single assessor is stated as a limitation rather than left unsaid.

## Synthesis and certainty

The **Synthesis & certainty** tab is where the review says how it synthesised
its evidence, and how certain it is of what it found. It is off by default; a
project that never opens it behaves exactly as before.

### Declaring the synthesis (SWiM)

Reviews that do not meta-analyse are routinely faulted for the same thing: the
label "narrative synthesis" with no description of what was actually done. The
SWiM guideline (Campbell et al., *BMJ* 2020;368:l6890) turns that into nine
reporting items, and this tab holds them — how studies were grouped and why,
what changed since the protocol and for what reason, the criteria that
prioritised some studies over others, how heterogeneity was examined, how the
data is presented, and what the synthesis cannot support.

Until you declare something, LitUbik will **not** put a method in your mouth.
Each review type carries a plausible default method, but the Methods draft
treats it as a default, not as a record of what you did: it writes a visible
`[TO COMPLETE]` instead of attributing it to you.

### Results, and the method that fits them

A review reports *results*, and each one is synthesised its own way. Declare
them one by one: the studies that contribute to it, the standardised metric,
the synthesis method, and what the synthesis found.

The method matters more than it looks. SWiM's table 2 pairs each method with
the question it can actually answer, and the app shows the pairing as you
choose: vote counting answers "is there any evidence of an effect?", never
"what is the average effect?". Reporting the second from the first is the
mismatch SWiM item 9 asks reviews to declare as a limitation — easier to avoid
than to confess.

### Certainty of the evidence (GRADE)

Rating the certainty of the evidence is a methodological expectation of
Cochrane reviews and one of the six domains editors triage on. LitUbik walks
the five steps of Brignardello-Petersen & Guyatt (*Am J Epidemiol*
2025;194:1681-6), **per result** — over the studies contributing to that
result, not over the corpus.

1. **Intent.** Causation or association? The same evidence rates differently:
   observational studies answering a causation question start low; answering
   an association question, they start high, because there they are the
   appropriate design.
2. **Target and thresholds.** Are you rating certainty in an effect of any
   size, or in one large enough to matter? Pre-specify the thresholds — GRADE
   asks for them before the rating, not after.
3. **Starting point.** Proposed from the qualified designs of the contributing
   studies, with the counts that motivate the proposal shown. You decide.
4. **The eight domains.** Five that lower certainty (risk of bias,
   inconsistency, imprecision, indirectness, publication bias), three that can
   raise it. For risk of bias, the appraisals of exactly those studies are put
   in front of you — including "none of them has been appraised", which is
   what makes a "no serious concern" judgement checkable. For publication
   bias, the search that was actually run.
5. **The level.** The app computes what its arithmetic gives and shows it
   beside your decision. When the two differ it says so rather than silencing
   one: GRADE explicitly allows two less-than-serious concerns in different
   domains to cost one level between them, which no formula reproduces.

Picking a level drafts the plain-language statement GRADE guideline 26 asks
for. Note where the certainty sits: in the verb. "Probably reduces" *is* the
moderate-certainty sentence — not a hedge bolted onto a confident one.

**GRADE is not universal.** It rates certainty in quantitative estimates. A
review synthesising qualitative findings wants GRADE-CERQual, and SWiM
excludes qualitative synthesis too (ENTREQ and eMERGe cover it). If your
question framework suggests a qualitative synthesis, the app says so — as a
warning, not a lock.

### Summary of Findings

The table editors ask for, assembled from what you declared: one row per
result, its contributing studies, participant totals read from your extraction
table, the method, the certainty and the plain-language statement. Exportable
as CSV. A result you never rated reads "not rated" rather than showing an
empty cell — an empty certainty column reads as a confident one.

## Towards a meta-analysis

LitUbik does not pool studies — the model, its assumptions and its
justification are yours — but it computes what a meta-analysis needs and
hands it over. On a reported result, **Effect sizes** lets a project admin
pick a measure (standardised mean difference as Hedges' *g*, mean
difference, odds ratio, risk ratio, correlation as Fisher's *z*) and map its
inputs (N, mean, SD, events, *r*) to the numeric extraction columns. Every
contributing study then gets its estimate, variance and 95 % confidence
interval, computed exactly as metafor's `escalc()` does (small-sample
correction for *g*, the usual continuity correction for zero cells); a
study with a missing or conflicting cell is listed with the reason, never
dropped silently. The table comes with a forest plot without a pooled
diamond, exportable as PNG, and three exports: an **R / metafor** bundle
(`data.csv`, one row per study, plus `analysis.R` which recomputes the
effects from the raw inputs as a check, fits a random-effects model and
draws forest and funnel plots), a **RevMan Web** CSV laid out like its
study-results template (one row per arm, Study ID matching the included
study — RevMan Web generates the template per review, so match the headers
to yours before importing), and a project-wide long CSV of every
quantitative result from the *Synthesis & certainty* tab.

## Importing an extraction table from another platform

Started your review elsewhere (Excel, Covidence, Rayyan export…)? In
**Extraction → Settings**, the project admin can upload the existing
extraction table as an **.xlsx** file. LitUbik proposes a mapping of the
spreadsheet columns — which ones are article metadata (title, DOI, authors,
year…) and which ones are extraction columns (matched by name to your grid,
or created on the fly). Rows are matched to the project's articles by DOI,
then by title; articles not found can be created automatically and enter
the extraction corpus directly, marked as included (they were screened on
the other platform). Non-empty cells are stored as validated values; empty
cells stay blank so the team can finish the table in the app. Re-importing
an updated file simply overwrites your previous imported values.

## Results

The **Results** page charts the included corpus: publications per year,
per country, study designs, and any categorical extraction column. The
charts are interactive: click a year bar, a design bar or a country on the
map to filter every chart at once (grey ghost bars keep showing the
unfiltered totals behind the filtered values, and each card's badge reads
`n=filtered / total`); the filter bar above the charts summarizes and
resets the active filters. Each chart has an **Export** menu (PNG or SVG
download, copy the image, copy the aggregated data) plus a **Data** toggle
that shows the same numbers as a plain table; a page-level button exports
every chart of the current tab at once. The head tiles track progress
toward completeness (extraction, validation, appraisal) and link to
the screen where the number moves. An optional **narrative synthesis**
can be generated by AI from the extraction table — review and edit it before
any use.

The **Themes** tab maps the corpus as a cloud of dots, one per record,
grouped by topic. Choose the corpus (all unique records, the records included
at title/abstract, or those included at full text) and let the number of
groups be chosen automatically (silhouette) or fix it; titles, abstracts and
keywords are vectorised (TF-IDF), reduced (SVD) and laid out in two
dimensions (t-SNE), then the groups are cut out of that map (k-means on
the layout) so each one is a contiguous region, numbered from the largest
— entirely on this server, no AI involved. Each group shows as a
translucent halo around its dots and a label at its centre; colour is the
group, the marker is the screening decision (filled = included, ring =
excluded, faint = undecided), so a cluster of excluded or undecided dots
shows at a glance where the corpus thins out. Each group lists its salient
terms; name it by hand, or ask the AI for suggested labels (marked *AI*
until you edit them). Point at a group in the legend to highlight it on the
map, hover a dot for the paper, click it for the paper card, hide groups
from the legend (the map refits to what remains), export the map as PNG and
the assignment as CSV; the **Table** button shows the same assignment as a
plain table. Every run is kept, so an earlier map can be reopened. It needs
at least six records and works before any screening — it is a scoping aid,
not a result: two neighbouring groups are two sides of one region, not two
unrelated subjects, and a rerun lays the map out afresh.

Its **Critical appraisal** tab leads with the judgement **per bias domain**:
for each study design, how the corpus answered on allocation, blinding,
attrition, and so on. A single "share of criteria met" is deliberately not the
headline — JBI's own guidance and the Cochrane Handbook both advise against
reading such a figure as a quality ranking, since two studies failing entirely
different criteria score the same. That figure is still available further
down, labelled for what it is: an indicator of how complete an appraisal is.

## PRISMA

The **PRISMA** page assembles the flow diagram automatically from the actual
numbers of the project: records identified per database, duplicates removed,
records screened and excluded, full texts assessed with exclusion reasons,
snowballing rounds, and the final included set. It follows the PRISMA 2020
template: the three stage bands (*Identification*, *Screening*, *Included*)
on the left, the main column flowing down with an arrow into each exclusion
box on the right, a second identification column (*via other methods*:
citation searching, manual additions) as soon as one exists, both merging
into the single *Studies included* box. Dashed boxes mark stages not reached
yet. The **Export** menu above the figure downloads it as **PNG** (print
resolution) or **SVG** (vector, for journals that ask for it), or copies the
image to the clipboard; live caveats (unfinished deduplication, provisional
totals) are shown under the figure and never exported.

Under the diagram, **Reviewer activity over the whole review** sums up what
each member did, every round folded (initial search and each snowballing
iteration): title/abstract and full-text records screened by hand out of
those allocated, conflicts settled, duplicates ruled, records extracted and
appraisals done. A stacked bar per stage shows each reviewer's mix of
include / exclude / maybe next to the whole team, and the pairwise Cohen's
kappa is recomputed over every double-screened record of the review, so a
small snowballing round no longer yields a kappa on a handful of records.
Human work only: AI suggestions are not counted, and titles excluded via
the validated AI triage are kept apart from what a reviewer actually read.
