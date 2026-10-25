# Contributing to LitUbik

Thanks for considering it. LitUbik is a research tool: bug reports from people
running real reviews are as valuable as code.

## Reporting

- **A bug or a methodological problem** — open an issue. For anything touching
  screening decisions, deduplication or PRISMA counts, say which stage you were
  in and what you expected the number to be; those bugs are worth fixing fast
  because they end up in someone's manuscript.
- **A security vulnerability** — do *not* open a public issue. See
  [SECURITY.md](SECURITY.md).

## Working on the code

```powershell
# from source, Windows, one click
start.bat

# backend tests
cd backend; .venv\Scripts\python.exe -m pytest tests -q

# frontend typecheck + build, unit tests, and lint
cd frontend; npm run build; npm test; npm run lint
```

A few conventions that are not obvious from reading the diff:

- **`npm run lint` includes the jsx-a11y rules** (`frontend/.oxlintrc.json`,
  which explains the two rules deliberately relaxed). Keep it clean: real
  buttons for clickable things, a label for every control, no information
  carried by colour alone. Errors and status messages go through
  `components/LiveStatus.tsx` so screen readers announce them.

- **Every model change needs an Alembic migration.** The launcher and `start.bat`
  run `alembic upgrade head` at boot, so a model without a migration breaks
  everyone's next start.
- **The UI is bilingual EN/FR in "natural key" mode**: the English string *is*
  the key, and `frontend/src/locales/fr.json` holds the French. Adding a string
  means adding its French entry; *changing* an English string means renaming its
  key in `fr.json` too, or the translation silently disappears. Removing one
  means deleting the orphan key.
- **AI suggestions are never applied without a human.** Anything a model
  produces is stored as a suggestion, with its provider, model and confidence,
  and a named person validates it. That invariant is the point of the tool —
  please do not add a code path that writes a decision on the model's behalf.
- Tests live in `backend/tests/` and, for the pure front-end modules (layouts,
  graph model), in `frontend/tests/` (`node --test`, no extra dependency). New
  behaviour comes with one.

## Licensing of contributions

LitUbik is distributed under the **GNU AGPL v3** (see [LICENSE](LICENSE)).

By submitting a contribution you agree to two things:

1. **Sign-off (DCO).** Add a `Signed-off-by: Your Name <you@example.org>` line to
   each commit — `git commit -s` does it — certifying you wrote the change or
   have the right to submit it, as in the
   [Developer Certificate of Origin 1.1](https://developercertificate.org/).
2. **Relicensing grant.** You grant Université Gustave Eiffel, the copyright
   holder of LitUbik (see [NOTICE](NOTICE)), a perpetual, worldwide,
   non-exclusive, royalty-free right to license your contribution under the AGPL
   *and* under other terms.

Point 2 needs a word of explanation rather than fine print. It exists so the
project is not permanently frozen on one licence by a dependency: LitUbik is
AGPL partly because PyMuPDF is, and if that dependency is ever replaced the
project should be free to move without having to track down every past
contributor. It also allows a commercial edition. You keep the copyright on
your contribution — this is a licence you grant, not an assignment.

If that is a problem for you, say so in the pull request: a contribution under
AGPL-only terms can still be accepted, it just gets recorded so we know which
parts are not covered.

## Third-party material

Do not add a dependency under a licence more restrictive than AGPL, and do not
commit third-party content — checklists, datasets, fonts, brand logos — without
checking that redistribution is allowed. [NOTICE](NOTICE) records what is
bundled and why; add to it in the same pull request.
