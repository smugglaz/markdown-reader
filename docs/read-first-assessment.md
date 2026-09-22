# Reading-first implementation assessment — 23 September 2026

The application now renders Read mode without constructing the visual editor.
This removes editor preparation from ordinary opening and reading refresh. It
also moves that cost to the first Edit request, which remains a noticeable delay.
The implementation is integrated, installed, and verified in an isolated native
run from installed code. Complete acceptance is not established: measured speed
limits and physical-interaction checks remain.

## Implemented behavior

The reading entry point uses the shared Markdown pipeline and sanitizer to build
a complete semantic document. Lists, tables, callouts, images, footnotes, math,
code, and diagrams render without editor node views. Selection, links, search,
outline, agent refresh, and export preparation operate on that reading view.
Asynchronous visual rendering is tracked for PDF readiness and error reporting.

`main.ts` dynamically imports `editing.ts` for the first Edit request. Native
controls show “Preparing editor…” and block Save while preparation is pending.
The source-preservation gate must pass before editing is enabled. Canceling back
to Read or loading a newer revision prevents an obsolete editor result from
replacing the current document.

Read/Edit changes detach and reattach the retained editor DOM and model, keeping
the unsaved buffer and Undo/Redo history. Reading displays the latest unsaved
content and can reuse its own unchanged DOM. The original source remains intact
until explicit Save. Model/Markdown validation, external-version conflict
handling, and recovery behavior remain in the save path.

## Integrated measurement and remaining limits

The actual GTK/WebKit foreground run in
`work/performance/read-first-integrated/performance.json` recorded these rounded
100 KB results:

| Operation | Observed time |
| --- | ---: |
| Open through native paint | 1,449 ms |
| First Edit | 1,790 ms |
| Typing transaction p95 | 19 ms |
| Agent refresh | 876 ms |
| Loaded-tab switching, including during typing | 35–63 ms |

All measurements in that run recorded foreground state. Opening met its 2,000 ms
target and the measured tab switches met 100 ms. First Edit exceeded 100 ms,
typing transactions exceeded 16 ms, and refresh exceeded 550 ms. The first-entry
editing cost is deferred, not eliminated; the application must not be described
as meeting every latency goal. Later Read/Edit toggles and current 500 KB behavior
are not established by this table. See [performance evidence](performance.md).

The integrated build passes 47 frontend and 72 Python tests. Native reading
workflow, feature, and programmatic design checks pass. The latest native
correctness run also passes, including retained views/history, exact source
restoration, refresh, theme changes, export warnings, and obsolete source dialogs.
Run locations and test scope are in [verification status](verification.md).
The full smoke/PDF workflow and final design visual recheck also pass. All three
exported pages were inspected, including unsaved edits exported on Letter paper.

## Historical reset and bounded prototype

Before this implementation, the user identified an optimization loop: small
changes were being measured without delivering a clearly faster application.
The investigation shifted to the cost of constructing an editor merely to read.
The following prototype result is retained as historical evidence, not as the
measurement of the integrated implementation above.

Disposable files are under `work/read-first-prototype`; they are not installed.
The baseline and prototype use the same 99,941-byte fixture. The prototype uses
the existing sanitized fallback renderer and omits Crepe construction.

The decision rule was complete content plus at least 40% faster foreground
opening. One comparison was attempted. An initial screenshot API error was
corrected; the subsequent baseline measured 2,426 ms in the foreground and
passed full text, heading/list counts and source-hash checks. Its DOM contained
8,787 descendant elements.

The prototype ran in the background, so its paint latency cannot be compared.
Its check also stopped at paragraph counts: compact HTML lists need not have the
same paragraph wrappers as the editor. Full text equality was not reached.
The visible screenshot was inspected, but that does not prove complete content.
Source hashes remained unchanged. No valid speedup is established, and the
experiment stopped without further timing runs.

## What remains before acceptance

Judge the installed result through representative documents and the actual user
workflow. Preserve the distinction between the completed programmatic native/PDF
checks and physical keyboard, clipboard, file-picker, and desktop
double-click checks. The measured first-Edit and refresh delays remain limitations;
the earlier prototype must not be installed or treated as the delivered app.
