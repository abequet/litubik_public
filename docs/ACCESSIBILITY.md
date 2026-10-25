# Accessibility conformance statement — WCAG 2.1 level AA

**Product:** LitUbik (web interface, English and French)
**Version assessed:** 1.0 development line, 14 October 2026
**Scope:** every page of the application (projects, protocol, equations,
search, deduplication, screening, full text, snowballing, extraction,
results, PRISMA, reporting, settings, help), in both languages, light and
dark themes.
**Method:** automated audit with axe-core 4.14 (rules `wcag2a`, `wcag2aa`,
`wcag21a`, `wcag21aa`, best practices) run by `backend/tests/test_a11y_axe.py`
on eleven representative pages × two languages against a seeded instance —
zero violation of any impact on 14 October 2026 — plus a manual keyboard,
screen-reader (NVDA on Windows) and reduced-motion walk-through of the
twelve pipeline steps. This document is maintained with the code: a change
that affects a criterion updates its row.

Status values: **Supports** · **Partially supports** (with the plan) ·
**Does not support** (with the plan) · **Not applicable**.

## Principle 1 — Perceivable

| Criterion | Level | Status | Notes |
|---|---|---|---|
| 1.1.1 Non-text content | A | Supports | Icons are decorative (`aria-hidden`) or carry an `aria-label`; charts have a text description and a **Data** table toggle; the citation network and the thematic map have an `aria-label` and a table alternative; PDFs are the user's own documents. |
| 1.2.1–1.2.5 Time-based media | A/AA | Not applicable | No audio or video content. |
| 1.3.1 Info and relationships | A | Supports | Semantic headings, lists, tables with `<th scope>` and captions, labelled form controls, landmarks (`main`, named `nav` and `aside`), `role="status"` live regions. |
| 1.3.2 Meaningful sequence | A | Supports | DOM order follows the visual order; sidebar before content, skip link first. |
| 1.3.3 Sensory characteristics | A | Supports | Instructions never rely on shape, colour or position alone (e.g. "AI, to validate" is worded next to the amber cell). |
| 1.3.4 Orientation | AA | Supports | No orientation lock. |
| 1.3.5 Identify input purpose | AA | Supports | E-mail and password fields carry `autocomplete`; other fields are review data with no HTML purpose vocabulary. |
| 1.4.1 Use of colour | A | Supports | Screening decisions, AI/validated cells, cluster membership and effect-size markers also carry text, icons or shapes (filled / ring / faint markers on the thematic map). |
| 1.4.2 Audio control | A | Not applicable | No audio. |
| 1.4.3 Contrast (minimum) | AA | Supports | Design tokens checked at ≥ 4.5:1 on their backgrounds in both themes (`--muted-foreground`, `--success`, `--warning` darkened on 14 October 2026); axe colour-contrast rule clean. |
| 1.4.4 Resize text | AA | Supports | Layout survives 200 % browser zoom; a text-size control (80–140 %) in the header is saved per browser. |
| 1.4.5 Images of text | AA | Supports | No images of text; charts are live SVG/canvas with text alternatives. |
| 1.4.10 Reflow | AA | Partially supports | Pages reflow to 320 px CSS width; wide data grids (extraction table, records table) scroll horizontally inside the viewport, which the criterion allows for data tables — the project sidebar collapses below 1024 px only through the browser's zoom, not a hamburger menu. Plan: collapsible sidebar (v1.1). |
| 1.4.11 Non-text contrast | AA | Supports | Focus rings (3 px, `--ring` at ≥ 3:1), input borders and chart marks checked against their backgrounds. |
| 1.4.12 Text spacing | AA | Supports | No fixed-height text containers; tested with the WCAG text-spacing bookmarklet. |
| 1.4.13 Content on hover or focus | AA | Supports | Tooltips (Radix) are dismissible with Escape, hoverable and persistent; cost estimates on hover are also readable in the button title. |

## Principle 2 — Operable

| Criterion | Level | Status | Notes |
|---|---|---|---|
| 2.1.1 Keyboard | A | Supports | Every control is a native button, link or input, or a Radix component with full keyboard support; extraction cells open with Enter, close with Escape; the citation network and thematic map have table alternatives for keyboard users; the scrolling content region (`main`) is in the tab order so it can be scrolled from the keyboard. |
| 2.1.2 No keyboard trap | A | Supports | Dialogs trap focus intentionally and release it on Escape or close. |
| 2.1.4 Character key shortcuts | A | Supports | Single-letter screening shortcuts (Y/N/M/S/P) can be turned off in the **?** menu (saved per browser) and are inactive while a text field has focus. |
| 2.2.1 Timing adjustable | A | Supports | No time limits; sessions do not expire during work. |
| 2.2.2 Pause, stop, hide | A | Supports | No content moves on its own: the citation network's layout is computed once and drawn still. |
| 2.3.1 Three flashes | A | Supports | Nothing flashes. |
| 2.4.1 Bypass blocks | A | Supports | "Skip to main content" link as the first focusable element on every page. |
| 2.4.2 Page titled | A | Supports | `document.title` follows the page and project. |
| 2.4.3 Focus order | A | Supports | Follows the DOM; dialogs move focus in and restore it on close. |
| 2.4.4 Link purpose (in context) | A | Supports | Links are worded; icon-only links carry an `aria-label`. |
| 2.4.5 Multiple ways | AA | Supports | Sidebar navigation, breadcrumb, in-app help with its own navigation and search of records. |
| 2.4.6 Headings and labels | AA | Supports | One `h1` per page, descriptive section headings, labelled controls. |
| 2.4.7 Focus visible | AA | Supports | Visible 3 px focus ring on every interactive element (`focus-visible`). |
| 2.5.1 Pointer gestures | A | Supports | Pan/zoom on the maps have button equivalents (reset view) and table alternatives; no multipoint or path gestures required. |
| 2.5.2 Pointer cancellation | A | Supports | Actions fire on `click`/`pointerup`, not on `pointerdown`. |
| 2.5.3 Label in name | A | Supports | Accessible names contain the visible text (axe `label-content-name-mismatch` clean). |
| 2.5.4 Motion actuation | A | Not applicable | No motion-operated function. |

## Principle 3 — Understandable

| Criterion | Level | Status | Notes |
|---|---|---|---|
| 3.1.1 Language of page | A | Supports | `<html lang>` follows the interface language (en/fr). |
| 3.1.2 Language of parts | AA | Partially supports | Bibliographic records keep their original language without a `lang` attribute (their language is unknown to the app). Plan: tag abstracts whose language the translation helper detected. |
| 3.2.1 On focus | A | Supports | Focusing never changes context. |
| 3.2.2 On input | A | Supports | Selects and checkboxes apply their value without navigating away; saves are explicit or announced. |
| 3.2.3 Consistent navigation | AA | Supports | Same sidebar and header everywhere. |
| 3.2.4 Consistent identification | AA | Supports | Same icons and wording for the same actions across pages. |
| 3.3.1 Error identification | A | Supports | Errors are announced in `aria-live` regions next to the control, in text. |
| 3.3.2 Labels or instructions | A | Supports | Every input has a visible label or placeholder plus `aria-label`; help text under complex settings. |
| 3.3.3 Error suggestion | AA | Supports | Server messages say what to fix (e.g. "Qualify the study design first"). |
| 3.3.4 Error prevention (legal, financial, data) | AA | Supports | Destructive actions (delete a study, reset, remove a key) ask for confirmation; AI outputs are never applied without human validation. |

## Principle 4 — Robust

| Criterion | Level | Status | Notes |
|---|---|---|---|
| 4.1.1 Parsing | A | Supports | React-generated DOM, no duplicate ids (axe clean). |
| 4.1.2 Name, role, value | A | Supports | Native and Radix components expose name, role and state; custom cells are buttons with text state; tab bars used without panels no longer expose a dangling `aria-controls`. |
| 4.1.3 Status messages | AA | Supports | `LiveStatus` (`role="status"`, `aria-live="polite"`) carries errors, progress and confirmations without moving focus. |

## Known limitations and plan

- **1.4.10 Reflow** — the sidebar does not collapse on narrow viewports;
  planned for v1.1.
- **3.1.2 Language of parts** — bibliographic text has no `lang` attribute;
  planned with the translation helper's language detection.
- The PDF viewer renders third-party documents: their accessibility (tagged
  PDF, reading order) depends on the publisher.

## How to re-run the audit

```powershell
cd frontend; npm install          # brings axe-core (devDependency)
npm run build
cd ..\backend
$env:LITUBIK_A11Y = "1"
.venv\Scripts\python.exe -m pytest tests/test_a11y_axe.py -q
```

The test writes `a11y_report.json` (every violation with its impact, rule
and nodes) into the test data directory and fails on any serious or
critical violation. The CI job `a11y` runs it on every push with Chromium.

## Feedback

Accessibility problems are bugs: report them from the in-app **?** menu
("Something looks wrong") or on the issue tracker, with the page, the
assistive technology and the browser used.
