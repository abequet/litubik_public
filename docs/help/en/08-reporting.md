# Reporting: Methods section and AI disclosure

The last step of the pipeline produces two texts for your manuscript, written
from what the app recorded while you worked — not from what anyone remembers.
Both are drafts: you edit them, and you sign them.

## Methods section

*Reporting → Methods section* drafts the methodology paragraphs of your paper:
protocol and eligibility criteria, information sources and the frozen search
equation, the deduplication rule, how many reviewers screened under which
allocation and conflict rule, the inter-rater agreement actually obtained, the
exclusion reasons, full-text retrieval, appraisal instrument, extraction
procedure, snowballing iterations, and — for a living review — the dates and
cadence of the search-update passes.

Every number comes from the project's audit trail (the panel above the button
shows the main facts, so you can check them before generating). The AI writes
prose around those facts; it cannot invent a threshold or a reviewer count
because it is only given what the pipeline stored. The generated text credits
LitUbik and its version as the software the review was conducted in.

### What the draft contains

It follows the PRISMA 2020 structure of a journal Methods section: study design
and registration · eligibility criteria (as a Criterion/Description table) ·
information sources and search strategy (concepts × terms, and each database
query **quoted verbatim as it was run**, hand-edited ones included, with its
result count) · study selection, one subsection per phase on the same pattern —
screened, included, excluded, conflicts and how they were resolved, and each κ
with its Landis & Koch interpretation · full-text retrieval and the exclusion
reasons with their counts · data collection · critical appraisal, naming the
instrument actually used and whether two assessors worked independently ·
synthesis method. Snowballing iterations get the same treatment, one per round, and the
final corpus is split between the database search and each iteration.

### Registration is a setting, not a guess

PRISMA item 24a asks for the register and the registration number, **or** an
explicit statement that the review was not registered. Those are two different
answers, and silence is a third. *Project settings → General* holds all three:
pick your register (PROSPERO, OSF Registries, INPLASY…) and give the number,
or answer "Not registered".

Leave it unanswered and the Methods draft marks a visible gap. Answer "Not
registered" and it states so plainly, as the limitation it is. What the draft
will never do is turn your silence into a claim that the review was not
registered — you have to say it.

Importing a protocol from an OSF link pre-fills the register and the URL, but
only if you had not answered yet. When the link is an OSF *registration*, its
identifier (the five-character GUID) and its registration date are filled in
too; an OSF *project* is not a preregistration, so the number then stays
yours to give.

### The gaps are marked, not filled

Some things a Methods section needs are simply not in the app: why you chose
that year window or those languages, the rationale for your synthesis method,
table and supplement numbers. Rather than inventing them, the draft writes
**[TO COMPLETE: …]** in bold, in place — search for it before submitting.

If the recorded numbers do not add up at some phase, the draft reports them as
recorded and flags the discrepancy instead of quietly adjusting a figure.

Pick **English or French** before generating — useful when your protocol is in
one language and your target journal in the other. The French version uses the
established French methodological terms rather than literal translations.

## AI disclosure statement

*Reporting → AI disclosure* produces the statement journals increasingly ask
for, covering **how AI was used to conduct the review**: searching, selection,
appraisal, extraction, synthesis. It deliberately says nothing about the
writing of your manuscript, which does not happen in LitUbik — the statement
says so explicitly, so a reader knows what it does and does not cover. If you
also used AI to write the paper, disclose that separately.

### It is written from a journal, not from memory

Every AI call LitUbik makes is recorded: which helper, which model, how many
calls, by whom, on which days, at what cost. The page shows that journal, plus
what the reviewers did with the output — how many AI screening suggestions
matched the final human decision and how many were overruled, how many
prefilled extraction cells were validated, how many bulk triage proposals a
reviewer confirmed.

This matters because reconstructing AI use after the fact is unreliable:
people misattribute and under-report what a tool contributed. Here you are
correcting a record instead of rebuilding one.

> If the project used AI *before* this version of LitUbik existed, the page
> warns you: the journal starts later than the actual use, and you must
> correct the levels by hand before generating.

### The form comes before the button

You review a short form — level of AI support (none / low / medium / high) for
each review activity, tools and versions, what material was sent to the
providers, safeguards you configured on the provider side, human validation,
authorship boundary. The levels are pre-answered from the journal; change
anything that does not match how you worked, then generate.

The generated statement is editable, and your edited version is kept when you
regenerate.

The structure of this form follows **DAISY**, the disclosure tool evaluated in:

> Ahmetoglu, Y., Constantinides, M., & Cox, A. (2026). AI Disclosure with
> DAISY. *Proceedings of the 5th Annual Symposium on Human-Computer
> Interaction for Work (CHIWORK ’26)*, Linz, Austria. ACM.
> <https://doi.org/10.1145/3808045.3808056>

Their study found that structured disclosure produced more complete statements
without making authors less comfortable with them, and that authors preferred a
generated statement they could edit over one they had to write or accept as
is — which is why LitUbik fills the form first and leaves the text yours to
rewrite.

## Amendments to the planned methods

A review is allowed to change its mind. What a reader needs — and what
editorial triage checks, for any review that references a protocol — is the
change *and its reason*. PRISMA item 24c asks for it; SWiM item 1b asks for it
about synthesis groups specifically.

*Reporting → Amendments* answers it from two directions.

**What the pipeline noticed.** LitUbik timestamped every stage as it ran, so
some changes are visible in its own tables: eligibility criteria reworded once
screening had begun, a protocol version validated after the records were in, a
search equation frozen after imports, a screening round restarted over existing
votes. Each of those surfaces as a card.

A card is a **question, not a verdict**. Nothing is promoted to a deviation
automatically, because the reason is the part only you have. Answer it — "it
was a change, here is why" — or dismiss it: "we looked, it was a typo fix". A
dismissal is recorded rather than forgotten, so nobody re-litigates the same
signal in three months.

**What no table could see.** A regrouping decided in a meeting, a synthesis
method abandoned, a database added mid-search: declare those yourself, with the
stage they belong to.

Only what you declare reaches the Methods draft, which closes on an
**Amendments to the planned methods** subsection listing each one with its date
and its reason. An unanswered signal stays a question for you and never becomes
a claim about the review.

Note what is deliberately *not* detected: extraction columns added mid-way.
LitUbik does not timestamp columns, so the only available signal would fire for
every project that ever started extracting, whether or not anything changed —
and a register that cries wolf is a register nobody reads. Declare that one by
hand.

## Reporting checklists

*Reporting → Checklists* fills the **PRISMA 2020** checklist — the 42-row file
journals ask for as a supplementary — with what this project actually recorded.

Each item lands in one of four states:

- **Recorded by the app** — the pipeline watched it happen, and the fact is
  shown. Item 8, for instance, reads back the number of reviewers, the
  allocation rule, the κ obtained and how conflicts were settled.
- **Yours to write** — outside the software by nature: funding, competing
  interests, the discussion. Add your note and the page.
- **Not done** — the app knows the stage never ran. This is the state that
  makes the file worth having: an empty cell reads as an oversight, "not done"
  reads as a finding, and you would rather find it here than in a reviewer's
  report.
- **Not applicable** — only you can say that, so it is the one status you set
  by hand.

The **SWiM** checklist appears alongside it as soon as one of your results
declares a synthesis method other than meta-analysis — that is SWiM's own
scope, and showing it to a review it does not cover would teach you to ignore
checklists.

Export either as CSV, with your page references in the last column.

### Before you submit

The same tab lists the problems editorial triage looks for, when they are
present: no appraisal instrument applied, no certainty framework, a single
assessor, a search equation never frozen, a search never checked against known
references, changes the pipeline noticed that nobody explained.

What it deliberately does **not** do is score you. Triage tools ask a handling
editor to rate six domains from 1 to 5; reproducing that here would turn an
editor's instrument into an author's, and awarding yourself a 4 is exactly the
self-declared compliance those tools exist to catch. A grade is a judgement. A
missing appraisal is a fact.

## Who can generate them

Any project member, like the other on-demand AI buttons: the author and the
cost are recorded. On a satellite copy the page is read-only — reporting is
published from the coordinator instance.
