# The review pipeline

## Review type and question framework

Two settings in *Project settings → General* decide the vocabulary of the whole
review:

- **Review type** — a plain systematic review, or a *"best fit" framework
  synthesis* (Carroll & Booth, 2013).
- **Question framework** — PICO, PICOS, **SPIDER** (Cooke, Smith & Booth, 2012:
  Sample, Phenomenon of Interest, Design, Evaluation, Research type), SPICE,
  PEO, or a free/adapted framing.

They change how the app talks to you and to the AI: the slots the protocol
extraction looks for, what the concept blocks are called, which extraction
template is offered, and what the Methods draft claims the review is.

**They change nothing in the pipeline itself.** The twelve steps below are the
same whatever you pick. In particular, choosing a "best fit" framework
synthesis does not give you a tool for the *a priori* framework: LitUbik runs
one search strand, has no object for that framework and does not code data
against it. Build the framework and do that coding outside LitUbik — the
`"Best fit" framework synthesis` extraction template gives you columns to
record which theme a finding was coded against, what did not fit, and where
each finding came from — and the Methods draft will say the software did not
support that part rather than credit it.

Changing the framework applies to the **next** protocol extraction: a protocol
already extracted keeps the text it has (which stays editable by hand).

## The twelve steps

Each project follows the same twelve steps. Nothing is ever deleted between
steps: every record keeps its provenance for the PRISMA report.

1. **Protocol** — research questions, the elements of your question framework,
   inclusion/exclusion rules. Written in Markdown; the AI assistant can draft a
   first version from your topic description.
2. **Equations** — build the search equation from your concepts (keywords are
   OR-ed inside a block, blocks are AND-ed; two concepts placed in the same
   block are OR-ed together), with AI advice and per-database translation
   (each database card shows the translated syntax).
3. **Search** — run the equations against the connected databases (OpenAlex,
   PubMed, Europe PMC, arXiv, Scopus, IEEE…) or import export files manually
   for assisted-manual databases. A *living review* can schedule update
   passes later; each pass is screened as a round of its own.
4. **Dedup** — automatic duplicate detection with manual review of the
   uncertain pairs.
5. **Screening** — title/abstract screening. Each record gets
   include/exclude/maybe votes from the assigned reviewers; conflicts are
   resolved in a dedicated view.
6. **FT retrieval** — fetch the PDFs of included records (open access sources,
   or your institutional access).
7. **FT screening** — full-text screening against the protocol criteria, with
   exclusion reasons (they feed the PRISMA diagram).
8. **Snowballing** — explore references and citations of included papers in
   rounds; new candidates go back through screening. Ran a round by mistake
   (e.g. seeded by a wrongly included paper)? From *Snowballing → Iterations*
   an admin can delete the **latest** round — its discovered papers, their
   screening and citation links are removed, as if it never ran (only the most
   recent round; peel back from the top down).
   The **citation network** at the bottom of the page has two views.
   *Iterations* (the default) shows only the retained papers, one column per
   round, each linked to the seed whose crawl found it (solid = found in its
   references, dashed = found among the papers citing it). The bar beside a
   seed sums up what its crawl brought back (◀ backward, ▶ forward); each column
   header gives the round's yield, and its footer counts what was not
   retained — click it for that list, most-linked papers first. A round that
   retains nothing is your saturation signal. *Network* draws the retained
   papers and the papers several seeds share; the papers found by a single seed
   are folded into one ring per seed (click it to fan them out). Its
   *Iterations shown* filter adds rounds without moving anything. Both views
   export to PNG or SVG, and **Data** lists every paper as a table.
9. **Extraction** — structured data extraction in a configurable table
   (columns defined by the project admin), with optional AI prefill that you
   validate cell by cell.
10. **Results** — charts (per year, country, design…) and an optional AI
    narrative synthesis.
11. **PRISMA** — the flow diagram is generated automatically from everything
    recorded above, exportable for your paper.
12. **Reporting** — the Methods section of your paper, drafted from the audit
    trail of everything above, and an AI disclosure statement drafted from the
    project's AI-use journal. Both are editable drafts (see *Reporting*).

## Exporting the references

At any stage, the sidebar's **Export references** entry downloads the
project's references — all of them, or only those currently included,
excluded, or still undecided (full-text decisions override title/abstract
ones) — as **RIS**, **BibTeX** or **CSV**. RIS and BibTeX re-import cleanly
into Zotero, EndNote or another LitUbik project; the CSV adds a
`screening_status` column.

The same dialog can **send the references straight to Zotero** (destination
*Zotero*) once your library is connected in *My integrations* with a key
that has write access. Pick an existing collection or let LitUbik create
`LitUbik – <project>`: each reference becomes an item tagged
`litubik:included` / `excluded` / `undecided` plus its LitUbik tags, with the
decision noted in the *Extra* field. A reference sent before is updated in
place (its Zotero tags and collections are kept), never duplicated. PDFs are
not sent.
