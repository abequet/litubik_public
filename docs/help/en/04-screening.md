# Screening (title/abstract and full text)

## How votes work

Each record is screened by the reviewers assigned to it (allocation is set by
the project admin in the screening settings: number of reviewers per record,
who screens what). A vote is **include**, **exclude** or **maybe**.
When the required votes agree, the decision is final; when they disagree the
record appears in the **Conflicts** view, where it is discussed and resolved.

## Weighted lots and rotating pairs

For a team where everyone does not take the same share of the work, the
project admin can allocate the round in **weighted lots** (*Who screens
what* → *Weighted lots*):

- the corpus is cut, in corpus order, into **lots** of a chosen size
  (100 records by default);
- each lot is screened by **one pair** of reviewers, so every record still
  gets two votes;
- each reviewer declares a **share of the work in percent** (the shares add
  up to 100; *Spread evenly* fills them in); the pairs are chosen lot after
  lot so that every reviewer ends up within one lot of their share, and the
  pairs **rotate** — with equal shares every pair gets a lot before any pair
  gets a second one;
- with *Arbiter* conflict resolution, the up to **two arbiters** named for
  the round are never paired on the same lot, so a conflict always has an
  arbiter who did not vote on it.

**Preview the lots** shows the plan before anything starts: one line per
lot with its pair, which you can change, and a deadline you can set. The
effective share of each reviewer updates as you edit. **Export the plan
(CSV)** downloads the plan as it stands, in the same format as the
allocation CSV, so you can deposit it with the protocol before the round
starts. **Start screening with these lots** applies that plan — it is the
one that gets published.

Records that enter the round later (snowballing, search update passes, a
late import) form **new lots**, numbered after the existing ones, on the
quotas that remain.

The **Dashboard** then shows the *share per reviewer* (effective against
declared) and the *lots* table: pair, progress of each reviewer, deadline,
status (*open*, *late* once the deadline has passed, *closed* when every
vote of the lot is in). **Allocation CSV** downloads one line per lot — lot,
size, reviewer A, reviewer B, deadline, status — the allocation to deposit
with the protocol.

## Lead reviewer: one screens everything, the others share

When one person — typically the project lead — wants to see every record
while the rest of the team splits the load, choose *Who screens what* →
**Lead reviewer**. Pick the lead among the ticked reviewers (yourself by
default). Every record then gets exactly **two votes**: the lead's and one
co-reviewer's. With 100 records and two co-reviewers, the lead screens 100,
each co-reviewer 50; with three, 34 / 33 / 33.

The co-reviewers share the corpus **equally** unless you declare their
**shares in percent** (the shares add up to 100 over the co-reviewers only;
*Spread evenly* fills them in). Records are dealt in corpus order to the
co-reviewer furthest below their share, so the allocation is reproducible.
Late records (snowballing, update passes) go to the lead plus the next
co-reviewer in that balance.

Conflicts between the lead and a co-reviewer are resolved as in every other
allocation (consensus or arbiter). The kappa is Cohen's with one
co-reviewer; with several, the *Vote cross-matrix* shows one matrix per
lead/co-reviewer pair. The Dashboard shows the *share per reviewer*
(effective against declared) for the co-reviewers.

With a single co-reviewer this allocation is the same as *Everyone screens
every record*. The option is available at both stages, title/abstract and
full text.

## Anonymous reviewers

Double blind hides the *votes* until a record is complete; it does not hide
*who* is screening with whom. When the team prefers not to know — so that
a disagreement is argued on the paper and not on the person — the project
admin ticks **Anonymous reviewers** in the screening settings, at either
stage (title/abstract, full text). The option is frozen when the round
starts, like the rest of the configuration.

While the round runs, **nobody — the admins and arbiters included — sees a
reviewer's name**: everywhere a name would appear (the votes of a conflict,
the per-reviewer progress, the kappa matrices, the lots and their pairs,
the allocation CSV, the screening notes, the PDF highlights) it is replaced
by a stable pseudonym, *Reviewer 1*, *Reviewer 2*… — the same for everyone,
your own included, flagged *(you)* on your votes. The *Reviewer activity*
table of the PRISMA page is withheld altogether, because its other columns
(duplicates, extraction) would give the pseudonyms away. The names come
back **once the round is complete**: every record voted and every conflict
resolved. A resolved conflict therefore stays pseudonymous while other
records are still open.

Two things the option cannot do: hide the lead reviewer from the admin who
picked them, and mean anything with two reviewers — each of them knows who
the other is.

## Resolving conflicts — and undoing a resolution

Each card of the **Conflicts** tab shows the votes, the reviewers' notes and
the abstract (click it to unfold the full text, click again to fold it).
*Include* or *Exclude* records the final decision.

Clicked the wrong button? A banner appears above the list right after each
resolution, with **Undo resolution**; the same button sits on every card of
the *Resolved* view. Undoing puts the conflict back in *To resolve*, votes
untouched. Whoever may resolve may undo (the reviewers in consensus mode,
the arbiters in arbiter mode). One limit: a title/abstract inclusion can no
longer be undone once the record has received full-text votes.

## The dashboard

- **Per reviewer** — progress of each reviewer, counted on what they really
  have to read. If the AI title triage was used, the titles it excluded are
  drawn hatched and left out of the total: `120/400 · 600 via AI triage`
  means 400 records to screen by hand, 120 done, 600 removed by the triage.
- **Vote cross-matrix** — for two reviewers, one table with a name on each
  axis: a cell counts the papers the row reviewer and the column reviewer
  voted that way, the diagonal being the agreements. With three reviewers or
  more there is one such table per pair of reviewers, each with its own
  Cohen's κ, so you can see *who* disagrees with *whom* (the headline κ stays
  Fleiss' κ over the whole team).
- **κ at title/abstract: "maybe" counts as "include"** — both votes send the
  record on to full text, so the κ and the raw agreement measure the binary
  call *goes forward / excluded*: one reviewer voting *maybe* and the other
  *include* is an agreement. The matrix still shows the three votes apart,
  and a *maybe* still opens a conflict to resolve — only the statistic is
  affected. At full text the three votes stay distinct. The reporting
  checklist and the generated Methods paragraph state this grouping.

## Keyboard-first screening

The screening screen is designed for speed: keyboard shortcuts for
include/exclude/maybe and next/previous are shown on the page. They are
single letters (Y, N, M, S, P), which can get in the way of speech input or
of some assistive technologies: the **?** menu in the header has a
*Single-key shortcuts* switch that turns them off (Escape, Enter and
Backspace keep working). Configurable **highlights** (project settings)
colour inclusion-related terms in green and exclusion-related terms in red
in titles and abstracts.

## One-by-one or list view, and keyword search

The screen tab has two layouts, switchable at the top: **one by one** (the
default — one record, big buttons, keyboard shortcuts) and **list** (scroll
through your queue and vote inline on each card). Typing in the **search
box** always opens the list, filtered to the papers matching your keywords
(title, abstract, authors, journal — accents ignored, terms combined with
AND, matches highlighted). While searching, the list covers everything
assigned to you, including papers you already voted on — voting again
simply replaces your vote as long as the record is not completed.

In the list, a card stays where it is after you vote, with an **↶ Undo**
button: it takes the vote back (the paper returns to your queue) or puts
back the vote it replaced. Undo works even if your vote completed the
record or opened a conflict — the conflict is withdrawn — as long as that
conflict has not been resolved yet. Each card also carries its **tags**
(*+ Tag*), exactly as in the one-by-one view.

## Reading an abstract in your language

If an AI provider is configured, **Translate to English / French** under a
record translates its title and abstract into the language of your interface.
Tick **Translate automatically** to have it done by itself for every record
you open that is not already in your language. The list view never translates
by itself: use the link under a card when you want one. In the one-by-one view it also translates the next three
records of your queue while you read the current one, so the text is usually
ready when you get there. The same link is available on each side of a pair in
**Dedup**.

A translation is a reading aid, never the source: it is marked *AI
translation* with the model that produced it, **Show original** is one click
away, and the *Edit the abstract* button under the text still edits the
original abstract. Keyword
highlighting works on whichever text is displayed, so terms from your English
equation will not light up in a French translation. When in doubt about a
criterion — a number, a population, a design — check the original before
voting.

Each text is translated once and shared with the whole team (it travels with
snapshots), so nobody pays twice; editing the abstract discards its
translation. An abstract already in your language costs no AI call. The
instruction given to the model is editable in *Project settings → AI prompts*,
and translation appears in the AI-use journal and disclosure like every other
AI feature.

## Notes and tags

Every record can carry free-text notes (visible to the whole team on the
*Screening notes* page — a vote justification only once that record is
complete, so the blind holds there too) and coloured tags to organise
papers of interest.

## Full-text screening

FT screening works the same way, but each exclusion requires an **exclusion
reason** (chosen from the protocol criteria). These reasons appear verbatim
in the PRISMA diagram, so keep them consistent.

Not ready to decide — say, the PDF is missing, truncated or the wrong
paper? Press **S** (*Skip — decide later*): the report stays in your queue,
sinks to the back and comes around again once everything else is voted.
You can also upload or replace the PDF right there (see *Full text*), and
only fall back to the "full text not retrievable" reason when it truly
cannot be obtained.

## AI suggestions

If an AI provider is configured, the assistant can pre-sort records or
suggest votes. AI suggestions are always displayed as such (marked *AI*) and
**never** count as a human vote — a reviewer always confirms or overrides.

A stored PDF of **more than 45 pages** is never sent to the AI (full-text
suggestion, extraction prefill, appraisal): at that length the file is a
book, a thesis or a whole proceedings volume, of which the model would only
see the first pages. The button says so; assess the report by hand, or
replace the file with the article itself.

### Seeing the suggestion only after your vote

A suggestion read before deciding tends to anchor the decision. The
screening settings offer **Show the AI suggestion only after the vote**, per
round and per stage. With it on:

- the suggestion is withheld **by the server** until your own vote on that
  record exists — the same rule as the blinding between reviewers, so no
  screen can show it early;
- once you have voted, a short card compares your decision with what the AI
  had suggested, then the queue moves on (*Enter* or *Next*);
- the on-demand *AI suggestion* button and *Regenerate* only appear on records
  you have voted on (your history);
- a suggestion **already computed** — by your own batch run or a
  co-reviewer's — can still be looked at before voting, through the explicit
  **See the AI suggestion before voting** button. That choice is recorded:
  the AI-use journal and the disclosure statement report how many votes were
  cast after an early reveal, so blind votes can be told from informed ones.

At full text the same setting exists; there, the AI's exclusion reasons are
never copied into your form by themselves — **Use the AI's exclusion
reasons** does it on request, and you still pick the primary reason.

An admin can switch the setting while the round runs. Snowballing rounds
inherit it from the previous round.

### Control sample for the AI title triage

The title triage excludes in bulk what the AI is confident is off-topic,
after a human validates the list. To check that confidence against the
reviewers' own judgement, the screening settings offer a **Control sample**
next to the triage mode (10 % by default, 1–50 %, changeable while the round
runs). With it on, that share of every validated list is drawn at random and
**not** excluded: those titles stay in the normal queue with no mark of any
kind, so the reviewers screen them like any other record. A second triage
pass never proposes them again.

The dashboard then shows an **AI triage control sample** card: how many
controls are still in the queue, how many the reviewers excluded by hand
(the triage is confirmed) and how many they kept — an include, a *maybe* or
an unresolved conflict all count as a contradiction. Pending controls are
only counted, never listed, so nobody can tell them apart while screening;
decided ones appear with the AI's confidence and reason next to the
reviewers' decision. If more than a tenth of the decided controls contradict
the triage, the card says so: lower the confidence threshold or re-read the
validated lists before relying on the automatic exclusions. The card is
admin-only in admin mode; in reviewers mode each reviewer sees the controls
drawn from their own lists.
