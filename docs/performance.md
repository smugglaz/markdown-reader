# Performance update — 23 September 2026

Opening a document now renders Read mode without loading or constructing the
Milkdown/ProseMirror editor. Editor preparation is deferred until Edit is
requested. The measured 100 KB foreground opening time is 1,449 ms. First entry
into Edit takes longer, at 1,790 ms; not all latency targets have been met.

## Current reading and editing flow

`frontend/src/main.ts` owns the reading view and dynamically imports
`frontend/src/editing.ts` when needed. `reading.ts` renders semantic HTML using
the shared Markdown pipeline, sanitizer, asset resolver, and visual renderers.
Ordinary lists do not need editor node views. Images, equations, code highlighting,
and Mermaid rendering are tracked separately so readable content can appear
before those tasks finish; PDF export still waits for them and reports failures.

The first Edit request creates the editor and runs the existing source-preservation
gate before allowing editing. Native controls display “Preparing editor…” and
prevent saving while that request is pending. Canceling back to Read or receiving
a newer document revision invalidates an obsolete preparation result.

Switching between Read and Edit retains the editor DOM, document model, and
Undo/Redo history. The inactive DOM is detached. Read displays the current unsaved
buffer; unchanged reading DOM can also be reattached without rebuilding it.
A clean agent update in Read rerenders the document without preparing an editor
for the new revision. Save still validates the edited model and Markdown, and
the native file layer still rejects external-version conflicts.

## Current measured evidence and limits

The integrated reading-first build was measured in the actual GTK/WebKit app
with disposable documents, bundled resources, and no external images. Every
measurement in `work/performance/read-first-integrated/performance.json`
recorded `foreground: true`. Rounded results for the 100 KB fixture:

| Operation | Observed time | Target |
| --- | ---: | ---: |
| Open through native paint checkpoint | 1,449 ms | 2,000 ms |
| First entry into Edit | 1,790 ms | 100 ms |
| Typing transaction, 95th percentile | 19 ms | 16 ms |
| Worst measured event-loop stall during typing | 70 ms | 100 ms |
| Agent refresh through paint | 876 ms | 550 ms |
| Switching loaded tabs, including during typing | 35–63 ms | 100 ms |

Opening, loaded-tab switches, and the worst measured typing stall met their
targets in this run. First Edit, typing transaction time, and agent refresh did
not. The first Edit cost is now paid on demand, so it must not be described as
eliminated or as an improvement in first-entry latency. This run does not measure
the cost of every later Read/Edit toggle or establish a 500 KB opening time.

The same run measured the 5 KB fixture opening at 853 ms, first Edit at 726 ms,
and refresh at 316 ms. One initial tab switch took 126 ms, above its 100 ms target.
These are observations from one foreground run, not universal speed guarantees.

## Earlier editor optimizations

The following work preceded the reading-first architecture. The optional editor
still uses these optimizations; they alone did not resolve the cost of building
an editor merely to read a document.

- **Reuse parsing and serialization.** Canonical comparisons reuse the editor's
  original parse tree and a bounded cache: at most eight entries, 2 Mi source
  characters, and 8 Mi result characters. Serialization reuses unchanged block
  trees, then stringifies the whole document once. Unsupported extensions use
  the complete serializer. Only the current document's block trees are retained.
- **Compare immutable editor nodes.** Dirty checks skip identical nodes and
  shared subtrees instead of converting the whole document to JSON and parsing
  Markdown again. Generated attributes and empty trailing paragraphs retain
  their previous comparison rules. Frontmatter remains part of dirty state.
- **Use lighter list and anchor views.** List markers no longer require a
  framework component or mounting transactions for every item. Outline IDs are
  owned by small node views, preventing DOM observers from treating ID updates
  as document edits. Duplicate anchor IDs are allocated without repeated scans.
- **Retain rendered visuals.** Mermaid loads only when a diagram needs it.
  Read/Edit changes reuse diagrams, equations, and highlighted code. A theme
  change rerenders diagrams once; missing-image warnings survive view reuse.
- **Reuse the editor across revisions.** When an editor is needed for a new
  revision, a new document state replaces clean content while retaining the
  editor view. Undo history resets, stale source dialogs close, and callouts
  adopt updated folding markers.
- **Reduce editor layout work.** Preparation batches layout writes before
  selection geometry is read. A stable inherited cursor variable avoids
  restyling the document when focus changes.

## Historical measurements before reading-first rendering

The earlier foreground 100 KB run, which built an editor during opening, recorded:

| Operation | Observed time |
| --- | ---: |
| Open through native paint checkpoint | 2,625 ms |
| Enter Edit | 519 ms |
| Typing transaction, 95th percentile | 21 ms |
| Worst measured event-loop stall during typing | 99 ms |
| Agent refresh through paint | 1,385 ms |
| Switching loaded tabs, including during typing | 35–58 ms |

Source: `work/performance/foreground-ordinary/performance.json`. Every row in
that run recorded `foreground: true`. These measurements precede the final
Read-at-creation, cursor-style, mode-write batching, and linear anchor fixes;
they are an intermediate observation, not final-build latency guarantees.

Instrumented JavaScript loading for the same 100 KB fixture measured 3,525 ms
in `baseline-stages/native-results.json` and 1,879 ms in
`final-timings/native-results.json`, both under `work/performance`. These measure
frontend work, not complete opening-to-paint time. The latter run was in the
background and also preceded the last layout/anchor corrections. GNOME/WebKit
background throttling caused paint callbacks to wait roughly one or two seconds;
those runs cannot support a fair before/after paint comparison.

The 500 KB stress fixture still took several seconds: its recorded frontend
loading stage was 7,436 ms in `final-timings`, before the last corrections.
These older results do not establish the current architecture's large-document
performance. No universal speedup factor or claim that all budgets pass is made.

## Correctness evidence and scope

The earlier editor-optimization build passed 41 frontend tests and 69 Python
tests, recorded in
`work/performance/frontend-tests-final.log` and `python-tests-final.log`.
`work/performance/correctness-final/native-results.json` reports a passing native
regression run covering exact clean-source preservation after selection/Undo,
Redo, metadata-only recovery, late save acknowledgements, refresh history reset,
task controls in Read/Edit, cached visual identity, missing-image export warnings,
callout folding, stale dialogs, and expected source bytes.

Those results predate the reading-first architecture and are historical evidence.
The current build passes 47 frontend tests and 72 Python tests. Native runs in
`read-first-workflow`, `read-first-correctness`, `read-first-features`,
`read-first-design-final`, and `read-first-smoke` pass. These cover editor-free
initial reading, deferred preparation, retained dirty buffers and Undo/Redo,
refresh, cancellation, protected source, conflicts, and export. All three PDF
pages and the final dark/narrow native screenshots were visually inspected.

These are programmatic native checks; they do not certify physical keyboard,
clipboard, or file-picker interaction. Consult [verification status](verification.md)
and the relevant run outputs for completed native and PDF checks. This document
records the completed installation separately from the remaining acceptance gaps.

## Reproduce

Follow the build and native-test commands in the [README](../README.md). Keep the
timing window in front and use `--wait-active` to start after it gains focus.
The timing harness records foreground state for each measurement. `--enforce`
fails the run on a missed latency budget; without it, a passing run establishes
workflow correctness, not that every performance target passed. Compare the
same fixture, build, foreground state, and machine load before claiming a speedup.
