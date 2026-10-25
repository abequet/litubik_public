# Collaboration and synchronisation

Two ways to work as a team:

## Same instance (simplest)

If everyone can reach the same LitUbik server (lab server, shared machine),
just invite members to the project — everyone works on the same data live.

## Separate instances (coordinator / satellites)

When each reviewer runs their own LitUbik (e.g. the Windows exe on their
laptop), one instance is the **coordinator** — it owns the project structure
(protocol, equations, rounds, settings) — and the others hold **satellite**
copies (marked *sat*).

- The coordinator **publishes snapshots** of the project; satellites import
  them and get the up-to-date structure, records and PDFs.
- Satellites **export their contributions** (votes, notes, annotations,
  extraction) back to the coordinator, which merges them.
- On a satellite, structural actions (changing the protocol, launching
  searches…) are locked — they belong to the coordinator.
- Screening **lots** (weighted lots, see *Screening*) are part of the
  structure: the coordinator previews and starts them; satellites receive
  the lots and each reviewer's assignments with the snapshot, and their
  votes flow back as usual. The allocation CSV can be downloaded on any
  instance.

## Two transport modes

- **Shared folder** (recommended): the coordinator links the project to a
  folder synced by Nextcloud/Drive/Dropbox; publishing and importing then
  happen automatically in the background. A reviewer joins in one step with
  *Join via a shared folder* on the home page.
- **Manual zips**: export a snapshot to a `.zip`, send it however you like,
  the other side uses *Import a project*. Works with no infrastructure at
  all (email, USB stick).

## Project passphrase (shared-folder security)

Set a **project passphrase** on the Synchronisation page and give the same one
to every co-reviewer out-of-band (chat, phone — not through the folder itself).
It does two things:

- it authenticates every package dropped in the shared folder, so only genuine
  co-reviewers' contributions are imported automatically — a file placed by
  anyone else with access to the folder is refused;
- it encrypts any shared API keys that travel between instances.

Without a passphrase, automatic shared-folder import is disabled (manual zip
import still works). Choose at least 12 characters — the encrypted blob travels
in the folder, so a weak passphrase could be attacked offline by anyone who can
read it.

Only the instance administrator can attach the app-wide AI keys to a project
as shared keys (the *Share my … key* buttons): they are the administrator's
keys. Another project admin shares a key of their own instead.

## Work time (project admin)

LitUbik measures the **active time** each member spends on the work pages —
screening (title/abstract, full text, conflicts), dedup, extraction and
appraisal. While such a page is open, visible and in use, the browser tells
the server every 30 seconds; the server folds these beats into sessions per
stage. Nothing about the reference on screen is recorded: only the stage and
the duration.

Everyone is told: the **Members** panel of the project card explains the
measure and shows each member their **own total**. The detail per reviewer
is for the **project admin** only, on the *Work time* page of the sidebar:

- a table reviewer × stage, with the total and the **median time per
  screened record** (title/abstract and full text), the figure usually
  reported when a screening tool is evaluated;
- active minutes per week;
- a **measured / estimated** switch. *Estimated* rebuilds sessions from the
  timestamps reviewers already leave (votes, rulings, extracted cells,
  appraisals): a gap longer than the *inactivity cut-off* (10 min by
  default) closes a session, and each act is credited at most the *max time
  per act* (5 min). Use it for work done before this feature existed, or as
  a cross-check of the measure;
- a CSV export (reviewer × stage × day).

Sessions travel with the reviewer's contributions between a satellite and
the coordinator, like votes. Never a time per individual reference is
shown, exported or synced — only aggregates.

## Backups and restore

A snapshot is also a full backup of the project. Export one from the
Synchronisation page whenever you reach a milestone (end of a screening round,
before a reset…) and keep the `.zip` somewhere safe.

To roll the project back to a backup:

- **Project still on the instance**: Synchronisation → *Restore from a
  snapshot (backup)*. The whole project is replaced by the archive content —
  everything done since that export is lost — and it stays the reference
  (coordinator) instance.
- **Project deleted, or a fresh instance**: Projects page → *Import a
  project* → pick *My own backup — restore it*. The project is recreated as
  coordinator.

Both are for archives exported from **your own** project. To receive a
coordinator's update on a satellite copy, use *Apply a received snapshot*
instead — that path keeps your local votes; a restore deliberately does not.

## Public replication archive (to publish with a paper)

A snapshot is a working copy for your team. It holds material you may use
but not redistribute: the full-text PDFs, the abstracts (they belong to the
publishers, even when an open index serves them), the raw exports of
commercial databases (Scopus, Web of Science, IEEE Xplore, ACM… forbid their
redistribution) and your shared API keys. Do not publish it.

To deposit the review on OSF or Zenodo, or as supplementary material, use
Synchronisation → **Public replication archive** → *Export public archive*.
The archive (`…_public.zip`) keeps:

- the bibliographic metadata (title, authors, year, venue, DOI);
- the protocol, equations, counts and recall;
- deduplication, votes, conflicts, reasons and AI suggestions;
- appraisal, extraction, deviations and the AI-use journal.

It leaves out the PDFs, abstracts and their AI translations, raw database
exports, the passages quoted by PDF annotations (your notes stay), shared
API keys and pending invitations. It also drops traces that say more about
the people than about the review: the reviewers' work sessions, the
retrieval diagnostics, the name of the institution whose access fetched a
paper (the source type "institution" stays), and any e-mail address a
database left in an author field. It does not change the snapshot version.

A `README.txt` at the root of the zip says what the archive holds, what was
left out and how to re-import it. LitUbik does not choose a licence for the
archive: state the licence of your own contribution (decisions, coding,
protocol) next to it, for example CC BY 4.0. The bibliographic metadata stays
subject to the terms of the databases you searched.

Imported into LitUbik (*Import a project* → *My own backup — restore it*), it
reproduces the PRISMA counts and the agreement statistics. The full texts
show as "to retrieve": whoever replicates the review fetches them with their
own access.

**Pseudonymise the reviewers** is an option, because journals differ. It
replaces every e-mail address in the archive by `reviewer-N@pseudonymized.invalid`
and the reviewers' names by "Reviewer N". Names you typed yourself in
free-text notes (conflict resolution notes, deviations, comments) are not
detected: reread them before publishing.

### Instance-wide backup (application admin)

Project snapshots cover one project at a time. The **Instance backup** page
(Administration section of the sidebar) downloads the whole instance in one
zip: the complete database (all projects and accounts), the auto-generated
secret key, and optionally every stored file (PDFs, raw RIS, protocols).
Keep the secret key with the backup — without it (`LITUBIK_SECRET_KEY` or
`data/secret.key`), a restored database cannot decrypt the API keys stored
in it.

For a recurring backup, run `scripts/backup_litubik.ps1` (in the repository)
on any machine that can reach the instance: it logs in with a superadmin
account, downloads the zip, verifies it and keeps only the most recent
copies (3 by default). Its `-Install` switch registers it as a daily Windows
scheduled task.

To restore: stop the app, put `litubik.db` (and `secret.key`) from the zip
back into the `data/` folder, delete any `litubik.db-wal` / `litubik.db-shm`
files, unzip `storage/` next to them, restart.

Everything is managed from the **Synchronisation** page of the project.
