# FAQ / Troubleshooting

**The interface is in the wrong language.**
Use the language switch (EN/FR) in the header. The choice is saved per
browser.

**I can't see the Settings entry of a project.**
Only project admins see it. Ask an admin of the project to change your role.

**A database card asks for an API key.**
Configure a project key (*Project settings*, admin) or an app-wide key
(*Administration*, superadmin) — or use the assisted-manual mode: copy the
translated equation into the database website and import the export file.
CORE and Springer Nature keys are free (immediate registration), Lens.org
tokens are free for non-commercial use (request form), Scopus, IEEE and Web
of Science Starter keys come with an institutional subscription. The key
card links to each provider's page.

**The database I need is not in the list.**
Web of Science, EBSCO (PsycINFO/PsycARTICLES), ACM, TRID (transport
research) and Google Scholar are already there, in assisted-manual mode — they only show up as key cards for
Scopus and IEEE, the two with an API connector. Anything else, a project
admin adds in *Project settings → Database keys → Databases added by this
project*; it then appears on the Equations and Search pages like the others.

**How do I connect Zotero?**
Sidebar → *My integrations*. Create a key on zotero.org/settings/keys with
*Allow library access* (and *Allow write access* if you want to send
references from LitUbik; tick the group too if you work in a group library),
paste it, check it, choose the library. The key is personal: stored encrypted
on this server, used only for your own imports and exports, never shared with
other members or synchronised to other instances. Mendeley is not supported
(OAuth-only API being phased out): export RIS/BibTeX instead.

**Typing my university in the institutional access field finds nothing.**
The bundled proxy directory is public and not exhaustive. Try the short form
or the domain (`univ-eiffel`, `ucly`); if nothing matches, keep the name you
typed and paste the proxy login URL yourself (`https://…/login?url=$@`) —
your library can give it to you.

**AI buttons say no provider is configured.**
Add an AI key (project or app level, see *AI assistance*). If a key exists
but fails, check its quota/validity in the provider's dashboard.

**A project is marked “sat” and some actions are locked.**
It is a satellite copy: the structure is managed by the coordinator
instance. Contribute votes/notes/extraction and sync; structural changes
happen on the coordinator.

**I lost my password.**
Ask the app superadmin (v1 has no self-service reset). The superadmin can
also promote accounts.

**I ran snowballing by mistake (or on the wrong included papers).**
Open *Snowballing* → *Iterations* and click the ✕ on the last round. This
undoes it completely — the papers that round found, their screening and its
citation links are removed, as if it never ran — and frees its seeds to be
crawled again. Only the most recent round can be removed (delete rounds from
the top down); the action is admin-only and cannot be undone.

**My journal says no AI was used, but we did use it.**
The AI-use journal starts with the LitUbik version that introduced the
*Reporting* page. A project that used AI before that has AI output in its
tables but no journal entries — the disclosure page detects this and warns
you. Correct the levels in the form by hand before generating; from now on
every call is recorded.

**Does the AI disclosure cover the writing of my paper?**
No. It covers how AI was used to *conduct* the review, because that is what
LitUbik can observe. The generated statement says so explicitly. If you used
an AI tool to draft or edit the manuscript, disclose that separately.

**My review is not a PICO systematic review. Can I use LitUbik?**
Yes. In *Project settings → General*, set the **question framework** to the one
your protocol uses — SPIDER, SPICE, PEO, PICO(S), or a free framing — and the
**review type** to what your review actually is. The protocol extraction, the
concept-block labels, the extraction templates, the AI prompts and the Methods
draft all follow. The pipeline itself is unchanged.

**I chose "best fit" framework synthesis — where is the *a priori* framework?**
There is none in the app, and that is deliberate rather than missing: LitUbik
runs one search strand and has no tool for building an *a priori* framework or
coding data against it. The setting changes the vocabulary, the templates and
the Methods draft, not the pipeline. Do the framework work outside LitUbik and
record it in the extraction table — the `"Best fit" framework synthesis`
template gives you columns for the theme a finding was coded against, whether
the framework accommodated it, the emergent theme when it did not, and the
provenance of each finding. The Methods draft states that the software did not
support that part of the method, so a reader does not credit it with work it
did not do.

**I changed the question framework and my protocol still shows the old one.**
That is expected: the setting applies to the **next** extraction. The protocol
text already generated is yours — possibly hand-edited — so the app never
rewrites it. Re-run the AI extraction on a new protocol version, or edit the
Markdown by hand.

## Accessibility

LitUbik targets WCAG 2.1 level AA. The conformance statement — every
criterion with its status and the plan for the two partial ones — is in
`docs/ACCESSIBILITY.md` of the source tree; an automated axe-core audit of
the main pages runs with the test suite.

**Can I use LitUbik with a keyboard only?**
Yes. Every control is reachable with Tab, and the first Tab on any page
offers a *Skip to main content* link that jumps over the sidebar. Extraction
cells are buttons: Tab to a cell, Enter to edit it, Escape to cancel. The
screening pages add single-letter shortcuts (Y/N/M/S/P); if they clash with
your assistive technology, turn them off in the **?** menu (*Single-key
shortcuts*).

**Can I read the charts without seeing them?**
Every chart on the Results page has a **Data** button that shows the same
numbers as a plain table, and the citation network of the Snowballing page
has the same button listing the papers (status, round, linked seeds,
citations). Charts
also carry a text description for screen readers.

**The animations bother me.**
LitUbik follows your operating system's *reduce motion* setting: with it on,
dialogs open without transitions and the guided tour does not animate. The
citation network never moves on its own: its layout is computed once and drawn
still.

**The text is too small.**
The header has a text-size control (the *A* icon) from 80 % to 140 %, saved
per browser; the browser's own zoom works too. In the light theme, secondary
text now meets the WCAG AA contrast ratio (4.5:1) and no informative label
is smaller than 12 px.

**Which language does my screen reader use?**
The one you chose for the interface: the page language follows the EN/FR
switch, so the screen reader switches voice with it.

**Something looks wrong / I found a bug.**
Use the feedback button (message icon in the header) — it files a ticket
with the page context, visible on the *Tickets* page of **your instance**:
it reaches whoever administers it, not the LitUbik developers. The app admin
can export all tickets (with their comments) as CSV from that page. A bug in
LitUbik itself goes to the issue tracker of the public repository
(github.com/abequet/litubik_public).

**Where is my data stored?**
In the `data/` folder next to the app (SQLite database + PDFs). Back up that
folder; on a server keep `LITUBIK_SECRET_KEY` stable, otherwise stored API
keys become unreadable.

**Which e-mail address does LitUbik give to Crossref, OpenAlex and PubMed?**
Yours, if you give one — otherwise none. These services serve faster and more
reliably the requests that carry a contact address. LitUbik sends the address
set in `LITUBIK_CONTACT_EMAIL` (in `backend/.env`, or the server's
environment) or, failing that, the global Unpaywall e-mail entered in the
Full text settings. With neither, requests go out without an address: it
still works, on the services' public pool. No placeholder address is ever
sent, and nothing else leaves your installation: no telemetry, no update
check.

**What is the demo instance?**
The public demo lets anyone try LitUbik in one click, without an account: on
the demo address, *Start a guest session* opens a personal sandbox with an
example review already set up (screening in progress, conflicts to settle, a
PRISMA diagram). No e-mail and no password are asked. Everything in the
session is deleted at the daily reset — or at once with *End session and
delete my data* in the user menu; signing out of a guest session is final,
since it has no password.

A guest session has limits: a few projects, imports and searches capped at
2,000 records (5,000 per project), one background task at a time, full texts
retrieved from open-access sources only, and no stored API keys, project
members, synchronisation or prompt changes. The AI features run on the
instance's key within a small budget — per session, and per day and per month
for all visitors together — shown in the yellow banner; once it is used up,
AI stops until the next session, day or month.

Full, persistent accounts on the demo server are for the people its
administrator allowlisted (and the members an allowlisted account adds to a
project); they sign in on the instance's ordinary address. The legal notice,
terms of use and privacy notice are linked at the bottom of every page.
Nothing of this applies to a normal (self-hosted or desktop) installation.
