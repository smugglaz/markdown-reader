#!/usr/bin/env python3
"""Bounded GTK/WebKit checks for reading before lazy editor construction.

Uses disposable documents and isolated application state. Editor transactions,
toolbar actions and reading DOM handlers are real; physical input, file-picker
UX and visual PDF inspection remain separate manual/native checks.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import time

from native_features import NativeFeatures, PROJECT, GLib
from native_performance import document
from markdown_reader.storage import read_document


class NativeReadFirst(NativeFeatures):
    def __init__(self, output):
        super().__init__(output)
        self.expected_sources = {}

    def fixture(self, name, source, done, edit=False):
        self.expected_sources[self.fixtures / f"feature-{name}.md"] = source
        super().fixture(name, source, done, edit)

    def unchanged(self, doc):
        self.require(doc.path.read_text() == self.expected_sources[doc.path],
                     f"Unexpected source write: {doc.name}")

    def poll_js(self, doc, expression, predicate, done, label, timeout=45):
        deadline = time.monotonic() + timeout
        def inspected(state):
            if predicate(state):
                done(state)
                return
            self.require(time.monotonic() < deadline, f"Timed out: {label}; last state {state}")
            self.delay(check, 25)
        def check():
            self.evaluate(doc, expression, inspected)
        check()

    def mode(self, doc, mode, done):
        self.window.tabs.set_selected_page(doc.page)
        self.window.mode_changed(mode)
        expression = "(()=>{const s=window.reader.inspect();return {mode:s.mode,busy:s.busy,editable:s.editable};})()"
        def complete(state):
            self.require(mode != "edit" or state["editable"], "Editor gate rejected fixture")
            done()
        self.poll_js(doc, expression,
                     lambda s: s["mode"] == mode and not s["busy"] and doc.mode == mode and not doc.mode_busy,
                     complete, mode + " mode")

    def clean(self, doc, done):
        def checked(message):
            self.require(message.get("dirty") is False, "Read-only operation became dirty")
            self.require(message["markdown"] == self.expected_sources[doc.path], "Clean serialization rewrote Markdown")
            self.unchanged(doc)
            done()
        self.serialize(doc, checked)

    def start(self):
        self.window = self.app.ensure_window()
        self.window.present()
        self.window.set_theme("light")
        self.dense_source = document(100_000)
        self.fixture("read-first-dense", self.dense_source, self.dense_read)
        return GLib.SOURCE_REMOVE

    def dense_read(self, doc):
        expression = """(()=>{const root=document.querySelector('.reading-document');
            const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);const parts=[];
            while(walker.nextNode())parts.push(walker.currentNode.textContent);
            return {state:window.reader.inspect(),headings:root.querySelectorAll('h1,h2,h3,h4,h5,h6').length,
                lists:root.querySelectorAll('ul,ol').length,items:root.querySelectorAll('li').length,text:parts.join(' ')};})()"""
        def checked(result):
            state = result["state"]
            self.require(state["mode"] == "read" and not state["editorCreated"] and not state["busy"],
                         "Initial reading created an editor")
            blocks = self.dense_source.count("## A useful section")
            self.require((result["headings"], result["lists"], result["items"]) == (blocks + 1, blocks, blocks * 2),
                         "Dense read rendered only part of the document structure")
            # Fixture-specific plain text, independent of either rendering path.
            expected = re.sub(r"(?m)^#{1,6} |^- ", "", self.dense_source)
            expected = expected.replace("**", "").replace("`", "").replace("[reference](https://example.com)", "reference")
            tokens = lambda text: re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
            self.require(tokens(result["text"]) == tokens(expected), "Dense reading omitted, duplicated or reordered text")
            self.record("Complete dense 100 KB reading renders every heading, list item and text token without creating an editor")
            self.clean(doc, lambda: self.first_edit(doc))
        self.evaluate(doc, expression, checked)

    def first_edit(self, doc):
        self.window.mode_changed("edit")
        self.require(doc.mode_busy, "First Edit did not mark native preparation busy")
        def rejected(ok):
            self.require(not ok and not doc.saving and not doc.dirty, "Save proceeded while the editor was preparing")
            self.unchanged(doc)
            self.record("Save while first Edit is preparing rejects safely without changing the document")
            self.mode(doc, "edit", lambda: self.edit_dense(doc))
        self.window.save(doc, done=self.guard(rejected))

    def edit_dense(self, doc):
        self.marker = " Unicode draft café हिन्दी λ."
        def typed(_):
            self.serialize(doc, dirty)
        def dirty(message):
            self.require(message.get("dirty") and self.marker in html.unescape(message["markdown"]),
                         f"First Edit lost Unicode input: dirty={message.get('dirty')}; tail={message['markdown'][-120:]!r}")
            self.edited_source = message["markdown"]
            self.unchanged(doc)
            self.mode(doc, "read", lambda: self.read_dirty(doc))
        self.evaluate(doc, "(()=>{window.__savedEditor=document.querySelector('.ProseMirror');window.reader.testInsertText(" + json.dumps(self.marker) + ");return true;})()", typed)

    def read_dirty(self, doc):
        def checked(state):
            self.require(state["mode"] == "read" and state["dirty"] and self.marker in state["text"],
                         "Read mode failed to display unsaved edits")
            self.require(state["markdown"] == self.edited_source, "Read mode replaced the dirty buffer")
            self.unchanged(doc)
            self.mode(doc, "edit", lambda: self.undo_retained(doc))
        self.evaluate(doc, "window.reader.inspect()", checked)

    def undo_retained(self, doc):
        def identity(same):
            self.require(same, "Read/Edit recreated the retained editor")
            self.evaluate(doc, "(()=>{" + self.click("Undo (Ctrl+Z)") + "return true;})()",
                          lambda _: self.clean(doc, redo))
        def redo():
            self.evaluate(doc, "(()=>{" + self.click("Redo (Ctrl+Shift+Z)") + "return true;})()",
                          lambda _: self.serialize(doc, redone))
        def redone(message):
            self.require(message.get("dirty") and message["markdown"] == self.edited_source, "Read/Edit lost Redo history")
            self.record("Read/Edit preserves the same editor, dirty Unicode buffer and exact Undo/Redo history")
            self.mode(doc, "read", lambda: self.window.save(doc, done=self.guard(saved)))
        def saved(ok):
            self.require(ok, "Explicit Save from Read failed")
            self.expected_sources[doc.path] = self.edited_source
            self.clean(doc, lambda: self.record_saved_and_refresh())
        self.evaluate(doc, "window.__savedEditor===document.querySelector('.ProseMirror')", identity)

    def record_saved_and_refresh(self):
        self.record("Reading leaves original bytes untouched; explicit Save in Read writes the retained edited buffer")
        self.fixture("never-edited", "# Initial agent document\n\nInitial body.\n", self.agent_refresh)

    def agent_refresh(self, doc):
        updates = [("ordinary", "# Ordinary agent update\n\nWhole new body.\n"),
                   ("atomic", "# Atomic agent update\n\nNewest complete body.\n")]
        def next_update():
            if not updates:
                self.fixture("cancel-import", "# Cancel lazy editor\n\nKeep this exact source.\n", self.cancel_edit)
                return
            kind, source = updates.pop(0)
            revision = doc.revision
            if kind == "atomic":
                temporary = doc.path.with_suffix(".replacement")
                temporary.write_text(source)
                temporary.replace(doc.path)
            else:
                doc.path.write_text(source)
            self.expected_sources[doc.path] = source
            def loaded():
                def checked(state):
                    self.require(state["markdown"] == source and not state["editorCreated"] and not state["dirty"],
                                 kind + " refresh initialized the editor or changed source")
                    self.require(source.splitlines()[0][2:] in state["text"], kind + " refresh retained stale reading DOM")
                    self.clean(doc, lambda: (self.record(kind + " agent refresh remains editor-free and exact"), next_update()))
                self.evaluate(doc, "window.reader.inspect()", checked)
            self.wait_for(lambda: doc.loaded and doc.revision > revision and doc.text == source, loaded, kind + " refresh")
        next_update()

    def cancel_edit(self, doc):
        # Both requests run in the same JS turn, so cancellation overlaps the
        # actual lazy import even on a warm filesystem cache.
        expression = """(()=>{window.__cancelFinished=false;const edit=window.reader.setMode('edit');
            const busy=window.reader.inspect().busy;const read=window.reader.setMode('read');
            Promise.allSettled([edit,read]).then(()=>window.__cancelFinished=true);return busy;})()"""
        def started(busy):
            self.require(busy, "Cancellation fixture did not exercise asynchronous editor preparation")
            def checked(state):
                self.require(state["mode"] == "read" and not state["busy"] and not state["dirty"],
                             "Canceled Edit reactivated the editor or changed the buffer")
                self.require(doc.mode == "read" and not doc.mode_busy, "Native controls ignored completed cancellation")
                self.clean(doc, lambda: (self.record("Canceling first Edit during lazy import stays in Read and preserves exact source"),
                                         self.fixture("obsolete-import", "# Obsolete source\n\nOld body.\n", self.obsolete_revision)))
            self.poll_js(doc, "({finished:!!window.__cancelFinished,...window.reader.inspect()})",
                         lambda s: s["finished"], checked, "canceled lazy import")
        self.evaluate(doc, expression, started)

    def obsolete_revision(self, doc):
        self.obsolete_source = "# Current source\n\nAn obsolete editor must never replace this buffer.\n"
        # Queue Edit and a new native load immediately. This isolates revision
        # cancellation; ordinary and atomic directory monitoring are tested above.
        doc.call("setMode", "edit")
        doc.path.write_text(self.obsolete_source)
        self.expected_sources[doc.path] = self.obsolete_source
        doc.snapshot = read_document(doc.path)
        doc.text = self.obsolete_source
        doc.mode = doc.requested_mode = "read"
        doc.mode_busy = False
        doc.revision += 1
        doc.load_frontend()
        def loaded():
            # Await one subsequent Edit. ensureEditor must settle any obsolete
            # preparation before constructing the current generation.
            self.mode(doc, "edit", checked_edit)
        def checked_edit():
            def checked(state):
                self.require(state["markdown"] == self.obsolete_source and not state["dirty"],
                             "Obsolete editor preparation replaced the current buffer")
                self.require("Current source" in state["text"] and "Old body." not in state["text"],
                             "Current editor contains the obsolete revision")
                self.clean(doc, lambda: (self.record("Superseding a pending Edit preserves the new revision and its exact clean buffer"), self.reading_features()))
            self.evaluate(doc, "window.reader.inspect()", checked)
        self.wait_for(lambda: doc.loaded, loaded, "superseding native load")

    def reading_features(self):
        source = """---
title: Actual metadata
---
---
Important body text
---
Rest

# Read features

[Jump to the target](#target-section)

> [!NOTE]- More detail
> Hidden callout body.

- [ ] Read-only task

![Local image](local%20image.svg)
![Missing image](missing-image.svg)

Inline math $E=mc^2$.

$$
\\int_0^1 x^2\\,dx=\\frac{1}{3}
$$

```mermaid
flowchart LR
  Read --> Save
```

```mermaid
this is deliberately not a valid diagram
```

""" + ("A paragraph to make heading navigation scroll.\n\n" * 24) + "## Target section\n\nDestination body.\n"
        self.fixture("reading-features", source, self.feature_export)

    def feature_export(self, doc):
        def prepared(message):
            doc.call("exportFinished")
            issues = message.get("issues", [])
            self.require(any("Image unavailable" in issue for issue in issues), "Export did not report the missing image")
            self.require(any("Diagram could not be rendered" in issue for issue in issues), "Export did not report the failed diagram")
            self.require("reading-document" in message.get("html", "") and "Destination body." in message["html"],
                         "Read export omitted document content")
            self.require("Important body text" in message["html"] and "Rest" in message["html"],
                         "Export stripped body content that resembles a second frontmatter block")
            self.record("Read export waits for rendering and reports missing images and failed diagrams", issues)
            self.feature_actions(doc)
        doc.request("prepareExport", self.guard(prepared))

    def feature_actions(self, doc):
        expression = """(()=>{const root=document.querySelector('.reading-document');
            const label=root.querySelector('.callout-label'),body=root.querySelector('.reading-callout-content');
            const folded=body.hidden;label.click();const opened=!body.hidden;label.click();
            const task=root.querySelector('[role=checkbox]'),before=task.getAttribute('aria-checked');
            task.dispatchEvent(new MouseEvent('click',{bubbles:true}));
            task.dispatchEvent(new KeyboardEvent('keydown',{key:' ',bubbles:true}));
            task.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
            const image=root.querySelector('img[alt="Local image"]');
            const result={state:window.reader.inspect(),folded,opened,refolded:body.hidden,
                taskUnchanged:before===task.getAttribute('aria-checked'),taskReadonly:task.getAttribute('aria-readonly'),
                imageReady:image.complete&&image.naturalWidth>0,math:root.querySelectorAll('.katex').length,
                diagrams:root.querySelectorAll('.diagram-preview svg').length};
            root.querySelector('a[href="#target-section"]').click();return result;})()"""
        def checked(result):
            self.require(not result["state"]["editorCreated"], "Reading feature rendering created an editor")
            self.require("Important body text" in result["state"]["text"] and "Rest" in result["state"]["text"],
                         "Reading stripped body content after real frontmatter")
            self.require(result["folded"] and result["opened"] and result["refolded"], "Reading callout fold control failed")
            self.require(result["taskUnchanged"] and result["taskReadonly"] == "true", "Read task checkbox was mutable")
            self.require(result["imageReady"] and result["math"] >= 2 and result["diagrams"] >= 1,
                         "Read mode failed local image, equation or valid Mermaid rendering")
            self.delay(lambda: self.evaluate(doc, "({scroll:scrollY,target:document.querySelector('#target-section')?.getBoundingClientRect().top,height:innerHeight})", linked), 100)
        def linked(state):
            self.require(state["scroll"] > 0 and state["target"] < state["height"], "Heading link failed to bring its target into view")
            self.record("Editor-free Read supports heading links, folded callouts, immutable tasks, local images, math and Mermaid")
            self.clean(doc, lambda: self.evaluate(doc, "(()=>{scrollTo(0,0);return true;})()",
                                                lambda _: self.snapshot(doc, "read-first-features.png", self.stale_equation_dialog)))
        self.evaluate(doc, expression, checked)

    def stale_equation_dialog(self):
        source = "# Equation dialog scope\n\nOriginal equation $a+b$.\n"
        def opened(doc):
            expression = """(()=>{document.querySelector('[data-kind="inlineMath"]').dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
                const dialog=document.querySelector('dialog.source-dialog');
                if(!dialog?.open)throw new Error('Equation dialog did not open');
                window.__obsoleteEquationForm=dialog.querySelector('form');
                dialog.querySelector('textarea').value='OBSOLETE_EQUATION';return true;})()"""
            def prepared(_):
                self.mode(doc, "read", force_submission)
            def force_submission():
                expression = """(()=>{const closed=!document.querySelector('dialog.source-dialog[open]');
                    window.__obsoleteEquationForm.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
                    return {closed,state:window.reader.inspect()};})()"""
                self.evaluate(doc, expression, checked)
            def checked(result):
                self.require(result["closed"], "Switching to Read left the equation dialog open")
                self.require(not result["state"]["dirty"] and result["state"]["markdown"] == source,
                             "Stale equation submission changed the Read buffer")
                self.clean(doc, lambda: doc.request("prepareExport", self.guard(exported)))
            def exported(message):
                doc.call("exportFinished")
                self.require("OBSOLETE_EQUATION" not in message.get("html", ""), "Read export included a stale modal edit")
                self.require(not message.get("issues"), "Original equation failed export after canceled dialog")
                self.record("Edit → Read closes equation dialogs; forced stale submission cannot change the buffer or export")
                self.finish_checked()
            self.evaluate(doc, expression, prepared)
        self.fixture("stale-equation-read", source, opened, edit=True)

    def finish_checked(self):
        for path, expected in self.expected_sources.items():
            self.require(path.read_text() == expected, "A disposable source changed outside its explicit save/update")
        self.record("All fixture sources match their explicit saves and simulated agent writes")
        self.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "work/native-read-first")
    args = parser.parse_args()
    raise SystemExit(NativeReadFirst(args.output).run())
