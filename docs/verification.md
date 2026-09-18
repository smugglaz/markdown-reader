# Verification status

This file records checks actually run on this Ubuntu/GNOME computer. A capability
described in the design is not evidence that its runtime behaviour was verified.

## Typography and editing update — 18 September 2026

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

## Packaging

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

## Native runtime

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

## PDF inspection

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

## Separate desktop checks

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
