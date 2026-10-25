# Searching databases and importing records

## Building the equation: concepts and blocks

On the **Equations** page you list your concepts and their keywords, then
combine them into variants. Keywords inside a block are **OR**-ed, blocks are
**AND**-ed:

    (older adults OR elderly) AND (gamification OR "serious games")

By default each concept is its own block. To search *either* of two concepts
instead of both, put them in the **same block**: next to each selected concept,
a small selector says which block it belongs to. The preview line under the
form shows what you are about to create, e.g.
`(Population OR Setting) AND Intervention`. A merged block is simply the union
of its concepts' keywords — nothing else about the equation changes, and every
database translation follows.

If your protocol already names its own search concepts and keywords, the
protocol extraction keeps them (section *Search concepts* of the generated
protocol) and **Propose from protocol** starts from them rather than inventing
new ones. Re-running the proposal never overwrites what you wrote: concepts you
already listed only get new keywords added.

The AI **synonyms** button on a concept works the same way — it is told the
research question, the protocol and the other concepts, so its suggestions stay
on that concept's axis. Nothing is ever applied without you: every keyword
stays editable and removable.

## Pasting an equation written elsewhere

A protocol often arrives with its equation already built and tested — fifty
lines of PubMed syntax with `[tiab]` and `[MeSH]` tags that no concept
builder would reproduce. Switch the *New variant* form to **typed per
database**, give the variant a label (*Eq. 6*), pick the database the text is
written for and paste it. Nothing is generated: what you typed is what the
counts run, what the Search page fetches or shows for manual export, and what
the search report quotes.

The other databases the review searches are **pre-filled by the AI** right
after creation (the box *Pre-fill the other databases by AI* is ticked by
default; the form says how many databases and roughly what it costs). One
call per database runs in the background, each draft lands as that
database's query, and the variant card and the Search page cards show it
with an **AI draft, not reviewed** badge. The draft is usable at once —
counts, fetches, the copy button for a manual export — but it stays marked
until a human either clicks **Validate draft** after reading it, or edits
the text (an edited text is yours, the badge disappears). The search report
and the Methods audit say which queries ran as unreviewed drafts, so review
them before the real search. **Draft … missing by AI** on the card or on the
Search page drafts any database still without a query, from the first text
the team wrote itself.

You can also work one database at a time: open a row, type its query, or
click **Draft with AI from…** to get a draft in the editor with the model's
remarks (a MeSH term it had to drop, for instance), then *Save edit*. A
typed variant keeps its label *typed*; it is frozen, counted and duplicated
like any other.

Which databases all this covers is a project setting: *Settings → Database
keys → Databases searched by this review*. Tick the ones your protocol
names (declared databases always count); the Equations and Search pages,
the counts, the drafts, the recall checks and the PRISMA-S report then
follow that list instead of the whole registry.

**Duplicate** makes a new draft with the same queries — the way *Eq. 6 bis*
is derived from *Eq. 6* to test one change. Counts and recall checks stay
with the original.

## Golden set and recall per database

The **Golden set** panel lists the references every acceptable equation must
retrieve, by **DOI or PMID** (one at a time, or several lines at once); the
missing identifier is looked up on PubMed. **Check recall** on a variant then
answers the protocol's question *is each reference retrieved in each
database?* in two ways, recorded side by side on the card and in the search
report:

- **API** — PubMed (by PMID), OpenAlex, Europe PMC, and Scopus or Web of
  Science when their key is configured, are asked whether their search for
  the equation retrieves each reference;
- **import** — for every database you have imported records from (EBSCO,
  TRID, ACM, Compendex… or an API fetch), the references are looked up among
  the records imported under that source for the variant. This check runs by
  itself after each import, so an export dropped on a card updates the chip
  at once.

Each chip reads *found/total*; its tooltip names the references missed. A
reference known only by DOI cannot be checked on PubMed and counts as missed
there, which is the protocol's own rule: a reference is expected wherever it
is indexed. The history of every check is kept per variant.

## Connected databases

On the **Search** page, each database has its own card. Databases with an
open API work out of the box: **PubMed**, **OpenAlex**, **Semantic Scholar**,
**Crossref**, **Europe PMC** (PubMed + PMC + the bioRxiv, medRxiv, ChemRxiv,
Research Square and SSRN preprints — tick the *Preprint* document type in
the equation to include them; there is no separate bioRxiv card), **arXiv**
(physics, maths, computer science, quantitative biology, statistics — one
request every 3 s, so a large fetch takes minutes), **HAL** (the French open
archive, all disciplines) and **DOAJ** (open-access journals). Databases
that require an API key need a key configured — **Scopus** and **IEEE
Xplore** (keys through your institution's subscription), **Web of Science
Starter** (subscribers, through the library; the Starter API returns titles
without abstracts), **CORE** (open-access aggregator, free key on
core.ac.uk), **Lens.org** (Crossref + PubMed + OpenAlex + CORE, free token
for non-commercial use, requested on lens.org) and **Springer Nature**
(Springer, Nature, BMC, free key on dev.springernature.com):

- **project keys** — *Settings → Database keys* of the project (project
  admin); a helper on each card tells you where to request the key (usually
  through your institution's subscription), or
- **app-wide keys** — *Administration → Database keys* (superadmin).

Without a key, the database is not blocked: its card switches to
**assisted-manual mode** — the app shows the query translated to that
database's syntax, you run it on the database's website and import the
export file.

Launch the search from the card; results are imported with full metadata and
tagged with their source database and the equation used.

## Assisted-manual databases

Some databases have no usable API (e.g. Web of Science without subscription,
EBSCO, TRID, Compendex, ACM DL, Google Scholar). Their card shows the
**translated equation** to copy into the database's own interface, then lets
you **import the export file**. Accepted: RIS (`.ris`, also EBSCO's and ACM's),
PubMed MEDLINE (`.nbib`, or `.txt` from *Save → PubMed format*), BibTeX
(`.bib`) and CSV (Scopus's CSV export; a Web of Science *tab-delimited* export
works once renamed to `.csv`). EndNote XML and Web of Science *plain text*
are not read: export again in one of the formats above. A PMID carried by the
file (`.nbib`, PubMed RIS, EBSCO MEDLINE) is kept: it is an exact
deduplication key and what the golden-set check looks up.

Before dropping the file, declare what PRISMA-S asks for: the day you ran the
search on the database (**Searched on**) and the result count it displayed
(**Hits shown**) — an export is often uploaded days later and may be capped
below the real count. Both appear in the imports table and the search report;
an API fetch fills them in by itself. Records imported this way carry the
same provenance as API results.

More PRISMA-S items sit under every upload, database export or free import
alike: **Date limits**, **Discipline limits** and **Document type limits** —
whether a date range, a discipline (subject-area) restriction and a
document-type restriction were actually applied when searching that source.
When disciplines or document types were applied, name them in the field that
appears (*Psychology, Engineering, Transportation*; *Article, Review*: the
lists the database offered, comma-separated). **Searched in** records the
fields the query ran on — title, abstract, keywords, full text or all fields;
tick every one that applies. Leave the selects on *not declared* and the
boxes unticked if you do not know; the answers show in the **Limits** column
of the imports table and in the search report. An API fetch sets them from
the equation's parameters.

Records that arrive **without an abstract** (Web of Science Starter, Scopus
without an institutional token, many manual exports) are completed in the
background right after the import, from open APIs only (OpenAlex, Semantic
Scholar, PubMed): nothing to click, the abstracts appear in the table within
a minute or two. Records that no open source describes keep an empty
abstract; the **Snowballing** page still offers the deeper manual pass that
also reads the publisher pages.

**Round**: an export belongs to the **initial search** by default, even when
uploaded after screening has started — a database's export often arrives
days after the others, and its records simply join the active round's
queues. Choose **search update** when the file is a *re-run* of the search
(before submission, say): it then becomes an update pass with its own round
(deduplicated at once, next screening round opened, team notified), exactly
like an API fetch launched during screening.

## Adding a database yourself

The built-in list (PubMed, OpenAlex, Semantic Scholar, Crossref, Europe PMC,
arXiv, HAL, DOAJ, Web of Science, Scopus, IEEE Xplore, CORE, Lens.org,
Springer Nature, EBSCO PsycINFO/PsycARTICLES, ACM DL, TRID, Compendex, Google
Scholar) rarely covers every source a review needs — a national portal
(Cairn, Érudit), a thesis or dissertation repository (theses.fr, DUMAS), a
domain repository (ERIC, Embase), grey literature.

A project admin adds one in *Settings → Database keys → Databases added by
this project*:

- **name** — what your co-reviewers will see, and the source name of every
  import from it;
- **query syntax** — the app cannot know the query language of an arbitrary
  database, so pick the closest built-in one (or the generic boolean string)
  and adjust the query by hand on the Equations page if needed;
- **link and instructions** (optional) — shown on the card, so everyone
  searches and exports the same way.

The database then behaves like any assisted-manual one: it appears on the
Equations page (translated query, manual count) and on the Search page
(instructions + file import), and its records count in PRISMA. Removing it
later only removes the card — records already imported keep their source.

## Importing from Zotero

If your references already live in **Zotero**, connect your library once
(sidebar → *My integrations*: paste an API key created on
zotero.org/settings/keys with *Allow library access*, then pick your personal
library or one of your groups). The Search page then shows a **Zotero
library** card: choose a collection (or the whole library), say whether it
counts as a **database search** or an **other source** for PRISMA, tick
*Also fetch the attached PDFs* if you want them in the full-text library,
and import. The import runs in the background, is archived and traced like
any file import (source `zotero:<collection>`), and is deduplicated right
away. Each imported record remembers its Zotero item, so sending references
back later updates those items instead of creating copies.

## Living review: update passes

A review can be kept alive after the first search. On the **Search** page,
the *Living review — search updates* panel (project admin) lets you:

- **schedule** update passes every 7, 14, 30 or 90 days on the API
  databases you tick (the frozen equation is re-run; each database is asked
  only for what it indexed since the previous pass — PubMed by Entrez date,
  OpenAlex and Crossref by creation date, Europe PMC, arXiv, HAL and DOAJ by
  deposit date, Scopus by load date; Semantic Scholar and IEEE cannot filter
  that way, so they over-fetch and dedup absorbs the overlap);
- **run an update now**, on the same databases;
- read the **history of passes** (date, databases, fetched, new unique
  records) and delete the latest one if it went wrong.

Each pass is a **round of its own**, like a snowballing iteration: the new
records are deduplicated against the whole corpus, a title/abstract
screening round opens with the previous round's reviewers and rules, the
full-text round is prepared as a draft, and PRISMA shows the pass as its own
column (*Search update 1, 2…*). Every member gets an in-app notification
(bell in the header, badge on the project card) saying how many new
candidates there are to screen. The Methods draft lists the update dates and
the cadence.

**Fetching from a card while a screening round is active** does the same
thing: the fetch becomes an update pass with its own round, so records never
slip into a round whose screening has already started. Before any screening
has started, a fetch simply extends round 1. In both cases deduplication runs
right after the fetch.

Scheduled passes run on the coordinator instance while it is up (the check is
hourly); there is no e-mail — the notification is in the app.
