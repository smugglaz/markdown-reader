# Verification status

This file records checks actually run on this Ubuntu/GNOME computer. A capability
described in the design is not evidence that its runtime behaviour was verified.

## Readability update — 23 September 2026

The native readability pass uses disposable documents and the installed GTK 4,
libadwaita, and WebKit 6 runtime. It checks matching Read/Edit table alignment
and borders, position retained across Read/Edit, explanatory format labels,
custom callout types, legible dark code comments, single-row compact toolbar,
Contents as an overlay at 620 px and 140% text, source-preserving code wrap and
expanded views, and source hashes. It also checks the actual Stocks Data README
at wide and narrow sizes. Evidence and screenshots are in the native test outputs.

The 49 frontend and 72 Python tests, TypeScript build, native design check,
native feature check, focused readability check, file-layout check, and complete
native smoke workflow passed for this update. The smoke workflow exercised
explicit Save, conflicts, drafts, and PDF export. The visual captures were
inspected. Physical keyboard, clipboard, Files double-click, and manual colour
perception remain outside this automated pass.

## Integrated reading-first update — 23 September 2026

The reading-first implementation is now in the application source. Initial Read
renders complete sanitized Markdown without loading or constructing the editor.
First Edit prepares and validates the editor; later Read/Edit changes retain its
document model, DOM, and Undo/Redo history. The earlier disposable prototype is
historical, not the current implementation; see the [assessment](read-first-assessment.md).

The integrated build passes 47 frontend tests and 72 Python tests, with successful
TypeScript checking and a production build. Evidence is in
`work/performance/read-first-unit.log`, `read-first-python.log`, and
`read-first-build.log`.

Programmatic native GTK/WebKit checks passed in these runs:

| Run under `work/performance/` | Verified scope |
| --- | --- |
| `read-first-workflow` | Complete 100 KB reading without an editor; deferred Edit and safe busy state; retained unsaved Unicode buffer and Undo/Redo; explicit Save from Read; ordinary/atomic refresh; canceled and superseded preparation; reading links, callouts, tasks, images, math, diagrams, and export warnings |
| `read-first-correctness` | Exact clean-source return after Undo; metadata-only recovery; late save acknowledgements; refresh history reset; task behavior; retained visual identity; theme changes; missing-image warnings; changed fold markers; stale source-dialog rejection |
| `read-first-features` | Formatting and table controls; inert embedded scripts/events/frames; missing-image warnings; deletion/reappearance; read-only save failure; recovery after renderer termination |
| `read-first-design-final` | Style selection, Normal text and Clear formatting; Enter after headings; list toggling; marker alignment; narrow viewport with enlarged text; native screenshot capture |
| `read-first-smoke` | Read, actual Stocks Data README, protected-syntax edit/save, Unicode, atomic refresh, conflicts, recovery, Save a Copy, and A4/Letter PDF export including unsaved edits |
| `read-first-overflow` | Wide tables and code scroll inside their own containers in both Read and Edit; table controls remain usable |

Each directory contains `native-results.json` with its tested frontend hash.
The latest correctness run passes all its checks. The integrated runs retain
source-hash checks; capture of a screenshot alone does not establish visual approval.

All three exported PDF pages were rendered and visually inspected: two A4 pages
and one Letter page. Tables, code, equations, Mermaid, local images, and text render
without clipping. The PDFs contain selectable text, four A4 link annotations
(including footnote links), and one Letter link annotation. Final whole-window
dark and 620 px/140% text screenshots were inspected; the heading is clear of the
toolbar and wrapped list text aligns correctly. Physical keyboard, clipboard,
file-picker, and mouse double-click checks remain distinct from programmatic testing.
The update is installed in user-owned application storage. All 168 native and
built-frontend payload files matched the tested source/build. Both Markdown MIME
defaults still point to `local.markdownreader.Reader.desktop`. An isolated run
using the installed Python module and frontend passed `read-first-installed`,
including cancellation, source protection, edits, refresh, and render readiness.
The existing user process was not terminated; it needs a normal save/close/reopen
to use the update. Remaining speed limits and manual checks prevent a claim of
complete acceptance.

The foreground 100 KB timing run recorded 1,449 ms opening, 1,790 ms first Edit,
19 ms typing-transaction p95, 876 ms agent refresh, and 35–63 ms loaded-tab
switches. First Edit, typing transaction time, and refresh exceeded their targets.
All measurements recorded foreground state. See [performance evidence](performance.md)
and `work/performance/read-first-integrated/performance.json`; passing correctness
checks does not mean every latency budget passes.

Three additional controller regressions verify that an agent update arriving
during a mode transition is retried once after completion, retains unsaved edits
as a conflict, and rejects obsolete completion messages.

## Historical performance update before reading-first integration

After the investigation reset, 44 frontend tests and the production build pass
(`work/performance/frontend-tests-reset.log`, `reset-build.log`). Three additional
anchor regressions cover duplicate-heading insertion/deletion/reordering,
explicit HTML IDs, and unchanged attribute writes. These final anchor changes
had unit coverage; the native runs in this historical section preceded that
correction. At that point the separate read-first prototype was inconclusive.
The integrated implementation and newer results are recorded above.

The production build and 41 frontend tests pass. The existing 69 Python tests
also pass. Real GTK/WebKit runs in `work/performance/correctness-final`,
`native-final`, and `features-final` pass the content and safety checks: explicit
saving, protected syntax, Unicode, atomic refresh, conflicting saves, recovery,
Save a Copy, formatting/table controls, deleted-file recovery, and renderer
termination. The Stocks Data README retained its original hash.

The added regressions cover editor reuse, exact clean-source return after Undo,
late save acknowledgements, metadata-only recovery, task controls, retained
visuals, missing-image warnings, changed callout folding markers, and obsolete
source dialogs. Opening or changing mode still does not write to the document.

The final A4 export has two pages and three link annotations. The Letter export
has one page and one link annotation, including unsaved edits. All three pages
were rendered and visually inspected; text remains selectable and equations,
diagrams, code, local images, and tables render without clipping.

The WebKit light/dark snapshots were inspected. A smoke-test whole-window dark
capture retained an older composited light page and was excluded. The separate
`design-final` whole-window dark and narrow screenshots were inspected and
render correctly. `overflow-final` verifies contained table/code scrolling.
Physical keyboard, clipboard, and file-picker checks remain manual.

Passing content tests does not mean every performance target passes. The smoke
run recorded a 4.968-second 100 KB load warning; its foreground state was not
recorded. Explicit foreground timing and the remaining large-document limits
are documented in [performance evidence](performance.md). The timing harness
rejects background measurements when `--enforce` is used.

## Historical typography and editing update — 18 September 2026

The previous style selector failed a real WebKit check: it stayed on Heading 2
after moving the selection to an ordinary paragraph. `tests/native_design.py`
now verifies that the replacement follows the cursor, Normal text preserves
inline emphasis, Clear formatting removes marks without removing words, Enter
after a heading creates normal text, and list controls exit back to text while
preserving neighbouring items.

The list layout check measures bullet, nested, checkbox, and two-digit numbered
markers against the first text line. Their centres now differ by less than
0.01 CSS px in the fixture. SVG markers inherit text colour rather than the
editor's pale border colour. Whole native-window screenshots were inspected for
the heading-preview menu, light/dark themes, and a 620 px window at 140% text
size. The test waits for WebKit compositing before capturing GTK frames.

The update passes the existing 69 Python and 11 frontend tests, the TypeScript
production build, the full native smoke workflow, and native formatting/table
checks. The original Stocks Data README retained its hash. The current run
loaded the 100 KB fixture in 1.864 seconds and the first comprehensive fixture
in 2.178 seconds; timings vary with startup and rendering work.

Both new PDF fixtures were rendered and visually inspected on every page:
two A4 pages and one Letter page, with selectable text and respectively three
and one link annotations. Source-preservation, explicit saving, atomic refresh,
conflict protection, recovery, and export of unsaved edits passed again.

Evidence is in `work/native-design-after`, `work/native-features-design`, and
`work/native-check-design`. These are isolated test artifacts. Physical mouse
and keyboard interaction and the native file picker are still manual checks;
programmatic event handlers do not establish those as passed.

## Historical packaging checks

The final Python suite passes 69 tests: 28 storage, 13 document-controller,
8 packaging, and 20 PDF-export tests. The frontend passes 11 transformation and
preservation tests, TypeScript checking, and the production build. All 23
Milkdown packages resolve to 7.22.1. The dependency audit reports no known
vulnerabilities in this locked build.

Eight isolated `--prefix` tests pass, including default-handler restoration,
preserving later user handler changes, refusing unowned files and symlinks,
preserving modified files on uninstall, and resolving unusual relative launch
paths. A real staging installation passes `desktop-file-validate`, compiles its
MIME database, and identifies a `.markdown` document as `text/markdown`.

## Historical native runtime checks

`/usr/bin/python3 tests/native_smoke.py --output work/native-check` runs the actual
GTK 4/libadwaita/WebKit 6 application in the desktop session with disposable
documents and a separate state directory. The latest complete run passed:

- Formatted headings, GFM tables/tasks, callouts, highlighted code, inline/display
  mathematics, Mermaid diagrams, and scoped local images.
- Encoded file URI opening and canonical-identity tab reuse. The Stocks Data
  `README.md` opened successfully and retained its original SHA-256 hash.
- A real Milkdown transaction and native Save of a comprehensive disposable
  document retained frontmatter, code-fence metadata, literal `latex` fences,
  footnotes, HTML source, Unicode, and local image paths.
- Read mode starts without an editable surface; editing does not write until
  Save. PDF export includes unsaved edits without saving Markdown.
- Native directory monitoring handles atomic replacement. Concurrent edits on
  disk block Save while retaining the local buffer. Recovery drafts retain that
  buffer. Save a Copy preserves the original and rebases relative images/links.
- Whole native GTK window and WebKit snapshots in light/dark themes were captured
  and visually reviewed. A narrow 620 px viewport with enlarged text had no
  horizontal document overflow.
- A 100 KB local document loaded in 1.534 seconds. The comprehensive first
  document loaded in 1.841 seconds. These are observed runs, not universal bounds.

`work/native-check/native-results.json` contains the machine-readable results;
PNG snapshots and PDF fixtures are beside it. These are test artifacts, not user
documents. Startup must run with access to the graphical desktop; a restricted
sandbox without a display is not a valid native-runtime test.

## Historical PDF inspection

The final local Chromium snapshot backend passed the native application export
workflow and PDF inspection. Poppler rendered every page; each resulting page
was visually reviewed. Tables, code, mathematics, Mermaid labels, callouts,
footnotes, Unicode text, and the local SVG image appear without clipping or
overlap. The same SVG also appears in the unsaved-edit Letter export.

`pypdf` confirmed:

- The A4 fixture has two pages, each approximately 594.96 by 841.92 points,
  selectable document text, and three link annotations: an internal footnote
  destination, a local Markdown file URI, and `https://example.com/`.
- The Letter fixture has one 612 by 792 point page, selectable text containing
  unsaved edits, and a clickable local-file link. Export left the source Markdown
  unchanged and still marked as unsaved.

`work/native-check/pdf-inspection.json` records dimensions, extracted-text counts,
and link targets. The frontend index hash matched before and after the final run,
so the acceptance check used one stable build. Chromium is used only for export;
the native WebKit print API currently omits PDF link annotations
([upstream issue](https://bugs.webkit.org/show_bug.cgi?id=302265)).

## Historical desktop checks

The app is installed at `~/.local/share/markdown-reader/app`, with
`~/.local/bin/markdown-reader` and a validated desktop entry. Both Markdown MIME
types now resolve to `local.markdownreader.Reader.desktop`. The installation
record retains `md.obsidian.Obsidian.desktop` as the previous handler for both.

The installed executable opened the actual README and Quick Start. Subsequent
launches with a Unicode path containing spaces, `#`, and `%`, the equivalent
encoded file URI, and `gio open` all reached the existing app and produced one
tab for that canonical file. The disposable desktop test tab was then closed.

`tests/native_features.py` also passed against the final build: real toolbar
click handlers for formatting, lists, headings, tables and undo/redo; inert
document scripts/event handlers/frames; missing-image warnings; deletion and
reappearance; read-only save failure; and recovery after terminating WebKit.

Physical keyboard/clipboard interaction, interactive file-picker selection,
and a mouse double-click in Files still require the requested user check. The
Quick Start document has been selected in Files for that check. These are not
marked passed based on programmatic launcher or renderer tests.
