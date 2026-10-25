# LitUbik

A self-hosted web application covering the full systematic literature review pipeline:
protocol ingestion (OSF) → search equation builder → multi-database automated search →
RIS import & deduplication → double-blind title/abstract screening → full-text retrieval →
full-text screening with exclusion reasons → snowballing → appraisal (JBI, MMAT) and data extraction →
auto-generated PRISMA 2020 flow diagram → Methods section and AI disclosure statement
for the manuscript.

Optional AI assistance at every step (Anthropic / OpenAI / Gemini / Grok / Mistral, or a local
OpenAI-compatible server such as Ollama — user-provided API keys).

### Reporting: the paragraphs your paper needs, written from the audit trail

The last step drafts two texts, from what the app recorded rather than from what anyone
remembers. The **Methods section** is written from the project's audit trail — the frozen
equation and its filters, the databases and dates, the deduplication rule, reviewer counts
and allocation, the κ actually obtained, exclusion reasons, appraisal instrument,
snowballing iterations — so no threshold or count in it can be invented.

The **AI disclosure statement** is written from the project's **AI-use journal**: every LLM
call LitUbik makes is recorded (helper, model, author, day, cost), alongside what the
reviewers did with the output — how many AI screening suggestions the humans agreed with
and how many they overruled, how many prefilled cells were validated, how many bulk-triage
proposals were confirmed. Authors review a structured form (level of AI support per review
activity, tools, material sent to providers, safeguards, human validation, authorship
boundary) that arrives **pre-answered from the journal**, correct anything that does not
match, and only then generate the statement — which stays editable. Both texts can be
generated in English or French.

The disclosure covers how AI was used to *conduct* the review, and says so explicitly:
LitUbik never sees the writing of your manuscript. The form's structure follows
[DAISY](https://doi.org/10.1145/3808045.3808056) (Ahmetoglu, Constantinides & Cox,
CHIWORK '26), which found that structured disclosure produces more complete statements
without making authors less comfortable with them, and that authors prefer a generated
statement they can edit.

### AI title triage (bulk pre-screening)

For broad searches where many hits are off-topic from the title alone, the reviewer can send
every not-yet-voted title of a T/A round to the LLM (with the protocol as context). It proposes
the clearly off-topic papers for exclusion above a confidence threshold; the human reviews the
checklist, unticks any doubt, and validates — **nothing is ever auto-applied**. Two modes (set by
the admin): `admin` = the validated list excludes globally (audited), `reviewers` = it casts the
reviewer's own exclude votes (double screening preserved). Proposals are saved with the job, so
you can leave and come back to validate them later, or move the threshold to refine the list,
without re-running the AI.

### Snowballing in rounds, reversible

Backward/forward citation searching runs in successive rounds seeded by the
full-text–included papers; each round's discoveries go back through
title/abstract and full-text screening. A round can be **undone**: from
*Snowballing → Iterations* an admin removes the latest iteration and everything
it produced — discovered papers, their screening, citation links — as if it
never ran (handy when a round was seeded by a paper included by mistake). Only
the most recent round is removable; peel them back from the top down.

## Getting started

Three ways to run LitUbik, by increasing involvement:

**1. Packaged app (Windows, zero prerequisites).** Download
`LitUbik-<version>-windows.zip` from the [releases](../../releases), unzip, run
`LitUbik.exe`: it creates its data folder (`%LOCALAPPDATA%\LitUbik`), applies the
database migrations, and opens your browser. No Python, no Node, no terminal.
(Note: the packaged build skips the optional Playwright-based full-text tiers — use
option 2 if you need bot-protected/institutional PDF retrieval.) The executable is
not code-signed, so Windows SmartScreen may say "Windows protected your PC" on first
launch: *More info* → *Run anyway*. `LICENSE`, `NOTICE` and the third-party licence
texts sit next to `LitUbik.exe`. Release builds come from this repository's CI
(`.github/workflows/ci.yml`, on a version tag); to build one yourself:
`packaging\build_windows.ps1`.

**2. From source (Windows — one click).** Double-click **`start.bat`** at the repo
root. It creates the Python environment, builds the frontend, applies the database
migrations, launches the server on http://localhost:8000, and opens your browser.
Keep the window open; Ctrl+C stops the app.

**3. Hosted (a lab/university server).** `docker compose up -d --build` with a
`LITUBIK_SECRET_KEY` in `.env` — it signs sessions **and** encrypts every stored
API key and institutional password, so keep it and keep it stable: if it
changes, those become permanently unreadable. Data lives on the `./data` volume.
Put an HTTPS reverse proxy in front for anything beyond a trusted LAN.

**Collaborating across machines/institutions** — snapshots, contribution
packages, shared-folder auto-sync, shared API keys: see
[docs/COLLABORATION.md](docs/COLLABORATION.md).

**Prerequisites**

- **Python 3.12+** — install from <https://www.python.org/downloads/> and, on the
  first installer screen, tick **“Add python.exe to PATH”**. This one is required:
  the launcher cannot install Python for you and will stop with instructions if
  it is missing.
- **Node.js** — *optional to install yourself*. If `npm` is not found, `start.bat`
  automatically downloads a local copy (no admin rights) into
  `%LOCALAPPDATA%\litubik\node` and uses it only for LitUbik. To install it
  system-wide instead, get the **LTS** build from <https://nodejs.org/>.

If a prerequisite is missing, the launcher now **stops with a clear message**
instead of starting half-broken. The automatic Node download needs an internet
connection the first time.

**Flags**: `start.bat --no-build` (skip the frontend build and serve the existing
`frontend/dist`) · `start.bat --no-browser` (don't open the browser).

## Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy 2 + Alembic, SQLite (WAL)
- **Frontend**: React 19 + TypeScript (Vite), TanStack Query, Tailwind CSS
- **Deployment**: runs on a single machine; teammates connect over the local network. Docker-ready.

SQLite is the only backend that is tested. Persistence goes through SQLAlchemy,
so PostgreSQL is reachable, but it is not there yet: `psycopg` is not a
dependency, the migrations have only ever run against SQLite, and a few places
work around SQLite's write lock specifically. Treat it as a port to do, not a
switch to flip.

## Development

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # then edit secrets
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

The dev frontend proxies `/api` to `http://localhost:8000`.

In production the backend serves the built frontend (`npm run build`) on a single port.

## Project layout

```
backend/    FastAPI app (api, models, services: llm, connectors, ris, dedup,
            screening, fulltext, snowballing, extraction, prisma, reporting,
            sync; workers)
frontend/   React SPA
packaging/  PyInstaller spec + Windows build script (one-click executable)
data/       SQLite DB + per-project storage (raw RIS, PDFs) — not committed
```

## Third-party materials

LitUbik reproduces, so that reviewers can fill them in, the wording of:

- the **PRISMA 2020** checklist (Page et al., BMJ 2021;372:n71 — CC BY 4.0);
- the **SWiM** reporting items (Campbell et al., BMJ 2020;368:l6890 — CC BY 4.0);
- the **JBI** critical-appraisal checklists (© JBI, <https://jbi.global>);
- the **MMAT** 2018 criteria (Hong et al., McGill University).

That wording is its authors' work, reproduced with attribution: it is **not**
covered by LitUbik's AGPL licence and stays under its own terms — see
[NOTICE](NOTICE). JBI is a registered trademark of the Joanna Briggs Institute.
LitUbik is not affiliated with, nor endorsed by, JBI or the MMAT authors.

## Contributing

Bug reports from people running real reviews are as useful as code — see
[CONTRIBUTING.md](CONTRIBUTING.md). Security issues go through
[SECURITY.md](SECURITY.md), never a public issue.

## License

LitUbik is free software, released under the
**GNU Affero General Public License v3** (see [LICENSE](LICENSE)): you may use,
study, modify and redistribute it, and anyone who offers a modified version as a
network service must publish their changes under the same terms.

[NOTICE](NOTICE) records the third-party components and what they require;
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) is the full generated
inventory. If you cite LitUbik in a review, see [CITATION.cff](CITATION.cff).
