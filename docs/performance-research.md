# Upstream performance research — 23 September 2026

## Decision

**Update after the user's review:** the sequence of small tuning experiments
has stopped. See the [read-first assessment](read-first-assessment.md) for the
implemented architecture, its native verification, and remaining first-Edit
delay. The earlier disposable trial was inconclusive; the research and proposed
experiments below are retained as investigation history.

**Capture an engine trace of opening and entering Edit before changing the
renderer again.** Separate Markdown parsing, ProseMirror construction, and
WebKit layout. The primary sources support this diagnostic approach; they do
not establish a missing dependency upgrade or a safe one-line speed fix.

## What the sources establish

| Finding | Application here |
| --- | --- |
| Web Inspector separates style/layout/paint from sampled JavaScript call trees. [WebKit documentation](https://webkit.org/web-inspector/timelines-tab/) | Use the trace to identify whether the remaining pause is JavaScript, layout, or focus/selection work. Keep the debugger and allocation profiler off during timing. |
| WebKitGTK gained Sysprof integration in 2.46; its profiling guide describes capturing an application and its subprocesses. [Release](https://webkitgtk.org/2024/10/04/webkitgtk-2.46.html), [profiling guide](https://raw.githubusercontent.com/WebKit/WebKit/main/Source/WebKit/glib/profiling.md.in) | The locally identified 2.52.6 runtime is new enough. Trace the disposable native test process, without unrelated system-wide collection. |
| Milkdown 7.22.1 parses synchronously through `remark.parse`, transforms the AST, then constructs ProseMirror nodes. Its state and view have separate readiness timers. [Parser](https://raw.githubusercontent.com/Milkdown/milkdown/v7.22.1/packages/transformer/src/parser/state.ts), [state](https://raw.githubusercontent.com/Milkdown/milkdown/v7.22.1/packages/core/src/internal-plugin/editor-state.ts), [view](https://raw.githubusercontent.com/Milkdown/milkdown/v7.22.1/packages/core/src/internal-plugin/editor-view.ts) | The current `create` timing combines distinct costs. Time the parser separately and use `EditorStateReady`/`EditorViewReady` to locate the rest. Off-screen CSS cannot remove parser cost. |
| Crepe's `setReadonly` calls `view.setProps` whenever the editor exists, including repeated values. [Versioned source](https://raw.githubusercontent.com/Milkdown/milkdown/v7.22.1/packages/crepe/src/core/builder.ts) | Guard redundant Read assignments with `instance.readonly`. This is a small measurable experiment, not an explanation for the whole delay. |
| ProseMirror prop changes can update DOM and preserve scroll; `storeScrollPos` reads geometry, and focus also preserves selection/scroll. [View source](https://github.com/ProseMirror/prosemirror-view/blob/master/src/index.ts), [geometry source](https://raw.githubusercontent.com/ProseMirror/prosemirror-view/master/src/domcoords.ts) | These paths are present in the installed 1.42.3 source. Check which triggers layout. Do not bypass selection maintenance or replace `view.focus()` with bare DOM focus; the maintainer explains its browser workaround. [Maintainer guidance](https://discuss.prosemirror.net/t/respect-focus-with-preventscroll/8208/2) |
| Milkdown's list-order plugin scans the document for generic transactions, without first requiring a document change. [7.22.1 source](https://raw.githubusercontent.com/Milkdown/milkdown/v7.22.1/packages/plugins/preset-commonmark/src/plugin/sync-list-order-plugin.ts) | A possible typing/selection cost. It does not run merely because `setProps` is called. Profile before replacing it; ordered-list conversion and numbering must still work. |
| ProseMirror fixed a large-flat-document update bug in 1.18.2. [Changelog](https://prosemirror.net/docs/changelog/) | Installed 1.42.3 already contains that historical fix. An old forum recommendation to upgrade is not an applicable remedy. |
| Remark's maintainer distinguishes parsing from rendering and notes that reference links require full-document parsing. [Maintainer discussion](https://github.com/orgs/remarkjs/discussions/1027#discussioncomment-3385057) | Do not split raw Markdown at arbitrary viewport boundaries. Such an optimization could change links, footnotes, or nested blocks. |

## Local evidence and limits

`work/performance/release-timings/performance.json` records a **foreground**
100 KB open at 2,782 ms and entering Edit at 386 ms. Later measurements in that
run were backgrounded and cannot establish foreground paint latency.
The local investigation already removed repeated parsing/serialization,
framework-heavy list views, and unnecessary visual rebuilding. A local
`content-visibility` experiment worsened typing and scroll estimates; this
research does not recommend shipping it.

These are local observations, not performance guarantees from upstream. Neither
historical Chromium spell-check reports nor macOS Safari benchmarks establish
the cause in this Linux WebKit application.

## Ranked experiments and stop rules

1. **Trace one 100 KB open and Read→Edit transition in the real WebKit runtime.**
   Record parser time, state/view construction, validation, layout, and first
   native paint. Use the same file and foreground state. Compare against a
   pre-created DOM clone outside ProseMirror only if layout dominates, so the
   test distinguishes browser cost from editor plugins.
2. **Apply the smallest change at the measured hot path.** If layout dominates,
   reduce repeated style invalidation/geometry reads, retaining selection and
   scroll correctness. If parsing dominates, measure schema-matcher allocation
   and repeated validation separately. The parser constructs its schema matcher
   list for each AST node; whether caching it matters is an untested hypothesis.
   Do not replace parser semantics or skip preservation checks to meet a budget.
3. **Consider a worker or deferred editing validation only after that split.**
   Worker parsing could keep input responsive but adds initialization and data
   transfer; it is not proven to reduce opening time. Showing Read earlier must
   keep Edit disabled until full preservation validation succeeds, reject stale
   revisions, and retain the complete source. Do not count partial loading as
   a fully interactive open.

Accept an optimization only when the same native benchmark improves and the
fidelity, refresh, selection, save-conflict, and PDF checks still pass. Remove a
failed experiment instead of combining it with unrelated changes.
