#!/usr/bin/env python3
"""Native save-safety regressions for editor reuse and cached dirty tracking.

Run after building the frontend, from the graphical desktop session:
  /usr/bin/python3 tests/native_performance_correctness.py --output work/performance-correctness

Only disposable files and isolated application state are opened or changed.
Transactions use the debug selection/typing helpers; Undo, Redo and task toggles
use their actual DOM handlers. This does not test physical keyboard input.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import time

from native_features import NativeFeatures, PROJECT, GLib


class NativePerformanceCorrectness(NativeFeatures):
    def __init__(self, output):
        super().__init__(output)
        self.expected_sources: dict[Path, bytes] = {}

    def fixture(self, name, source, done, edit=True):
        self.expected_sources[self.fixtures / f"feature-{name}.md"] = source.encode("utf-8")
        super().fixture(name, source, done, edit)

    def checked_source(self, doc):
        self.require(doc.path.read_bytes() == self.expected_sources[doc.path],
                     f"Unexpected source write: {doc.path.name}")

    def expect_clean(self, doc, message, source, description):
        self.require(message.get("dirty") is False, description + ": marked dirty")
        self.require(message.get("markdown") == source, description + ": normalized or changed original bytes")
        self.checked_source(doc)

    def start(self):
        self.window = self.app.ensure_window()
        self.window.present()
        self.window.set_theme("light")
        self.list_source = "# List at the end\n\n* First item\n* Second item\n"
        self.fixture("clean-list", self.list_source, self.clean_list, edit=False)
        return GLib.SOURCE_REMOVE

    def clean_list(self, doc):
        def selected(_):
            def inspected(state):
                self.require(state["trailingParagraph"], "Selection did not exercise the trailing empty paragraph")
                self.serialize(doc, checked)
            self.evaluate(doc, """(()=>{const last=document.querySelector('.ProseMirror').lastElementChild;
                return {trailingParagraph:last?.tagName==='P' && !last.textContent.trim()};})()""", inspected)

        def checked(message):
            self.expect_clean(doc, message, self.list_source, "Selection-only edit of a list")
            self.record("Entering Edit and selecting text can append an empty paragraph without dirtying or normalizing the source")
            self.undo_to_original(doc)

        self.window.mode_changed("edit")
        self.wait_mode(doc, "edit", lambda: self.evaluate(
            doc, "(()=>{" + self.select("Second item") + "return true;})()", selected))

    def undo_to_original(self, doc):
        marker = "A reversible Unicode edit: café हिन्दी."

        def typed(_):
            self.serialize(doc, before_undo)

        def before_undo(message):
            self.require(message.get("dirty") is True and marker in message["markdown"], "Typing was not captured as dirty")
            self.evaluate(doc, "(()=>{" + self.click("Undo (Ctrl+Z)") + "return true;})()",
                          lambda _: self.serialize(doc, undone))

        def undone(message):
            self.expect_clean(doc, message, self.list_source, "Undo back to the saved document")
            self.evaluate(doc, "(()=>{" + self.click("Redo (Ctrl+Shift+Z)") + "return true;})()",
                          lambda _: self.serialize(doc, redone))

        def redone(message):
            self.require(message.get("dirty") is True and marker in message["markdown"], "Redo did not restore the unsaved edit")
            self.checked_source(doc)
            self.record("Toolbar Undo restores exact clean source; Redo restores dirty Unicode text")
            self.metadata_recovery()

        self.evaluate(doc, "(()=>{window.reader.testInsertText(" + json.dumps(marker) + ");return true;})()", typed)

    def metadata_recovery(self):
        self.disk_metadata = "---\ntitle: Original metadata\n---\n\n# Same body\n\nKeep this paragraph unchanged.\n"
        self.draft_metadata = self.disk_metadata.replace("Original metadata", "Recovered metadata")

        def opened(doc):
            # This is the same load payload produced after accepting recovery;
            # its savedMarkdown still comes from the unchanged disk snapshot.
            doc.text = self.draft_metadata
            doc.dirty = True
            doc.mode = "edit"
            doc.requested_mode = "edit"
            doc.revision += 1
            doc.load_frontend()
            self.wait_mode(doc, "edit", lambda: self.serialize(doc, checked))

            def checked(message):
                self.require(message.get("dirty") is True, "A metadata-only recovered draft became clean")
                self.require(message["markdown"].startswith("---\ntitle: Recovered metadata\n---\n"),
                             "Recovered metadata was replaced with the saved prefix")
                self.require("# Same body" in message["markdown"] and "Keep this paragraph unchanged." in message["markdown"],
                             "Metadata recovery changed the body")
                self.checked_source(doc)
                self.record("Recovered frontmatter remains dirty when the body equals the saved document")
                self.fixture("late-save-ack", "# Save acknowledgement\n\nOriginal paragraph.\n", self.late_save_ack)

        self.fixture("metadata-recovery", self.disk_metadata, opened, edit=False)

    def late_save_ack(self, doc):
        first = " First serialized edit."
        later = " New edit arriving after serialization."

        def typed_first(_):
            self.serialize(doc, snapshot_ready)

        def snapshot_ready(message):
            self.require(message.get("dirty") is True and first in message["markdown"], "Initial snapshot was not dirty")
            snapshot = message["markdown"]
            # Do not serialize between the further edit and markSaved: this
            # models acknowledgement of the earlier asynchronous save request.
            expression = "(()=>{window.reader.testInsertText(" + json.dumps(later) + ");window.reader.markSaved(" + json.dumps(snapshot) + ");return true;})()"
            self.evaluate(doc, expression, lambda _: self.serialize(doc, acknowledged))

        def acknowledged(message):
            self.require(message.get("dirty") is True, "Earlier save acknowledgement cleared a newer edit")
            self.require(first in message["markdown"] and later in message["markdown"], "Earlier acknowledgement lost edited text")
            self.checked_source(doc)
            self.record("Acknowledging a serialized snapshot retains a later unsaved edit")
            self.fixture("refresh-history", "# Before refresh\n\nInitial saved paragraph.\n", self.refresh_history)

        self.evaluate(doc, "(()=>{window.reader.testInsertText(" + json.dumps(first) + ");return true;})()", typed_first)

    def refresh_history(self, doc):
        def typed(_):
            self.serialize(doc, ready_to_save)

        def ready_to_save(message):
            self.require(message.get("dirty") is True, "History fixture did not record an edit")
            self.pending_saved_source = message["markdown"]
            self.window.save(doc, done=self.guard(saved))

        def saved(okay):
            self.require(okay, "Could not save disposable history fixture")
            self.expected_sources[doc.path] = self.pending_saved_source.encode("utf-8")
            self.serialize(doc, clean_before_refresh)

        def clean_before_refresh(message):
            self.expect_clean(doc, message, self.pending_saved_source, "Saved history fixture")
            expression = """(()=>{window.__correctnessEditor=document.querySelector('.ProseMirror');
                return {undo:!document.querySelector('#toolbar button[aria-label="Undo (Ctrl+Z)"]').disabled};})()"""
            self.evaluate(doc, expression, write_external)

        def write_external(state):
            self.require(state["undo"], "The refresh test must begin with a nonempty undo history")
            self.window.mode_changed("read")
            self.wait_mode(doc, "read", write_when_read)

        def write_when_read():
            self.refresh_source = "# Fresh agent document\n\nThe latest disk version must survive Undo and Redo.\n"
            previous_revision = doc.revision
            doc.path.write_text(self.refresh_source, encoding="utf-8")
            self.expected_sources[doc.path] = self.refresh_source.encode("utf-8")
            self.wait_for(lambda: doc.loaded and doc.revision > previous_revision and doc.text == self.refresh_source,
                          refreshed, "clean agent refresh")

        def refreshed():
            self.window.mode_changed("edit")
            expression = """({sameEditor:window.__correctnessEditor===document.querySelector('.ProseMirror'),
                text:document.querySelector('.ProseMirror').textContent,
                undoDisabled:document.querySelector('#toolbar button[aria-label="Undo (Ctrl+Z)"]').disabled,
                redoDisabled:document.querySelector('#toolbar button[aria-label="Redo (Ctrl+Shift+Z)"]').disabled})"""
            self.wait_mode(doc, "edit", lambda: self.evaluate(doc, expression, history_reset))

        def history_reset(state):
            self.require(state["sameEditor"], "Clean refresh recreated the editor instead of reusing it")
            self.require("Fresh agent document" in state["text"], "Native reload completed before the frontend showed the new source")
            self.require(state["undoDisabled"] and state["redoDisabled"], "Agent refresh retained stale undo or redo history")
            self.evaluate(doc, "(()=>{" + self.click("Undo (Ctrl+Z)") + self.click("Redo (Ctrl+Shift+Z)") + "return true;})()",
                          lambda _: self.serialize(doc, checked))

        def checked(message):
            self.expect_clean(doc, message, self.refresh_source, "Undo and Redo after refresh")
            self.record("Clean disk refresh reuses the editor and clears Undo/Redo history")
            self.checkbox_modes()

        self.evaluate(doc, "(()=>{window.reader.testInsertText(' Saved edit with undo history.');return true;})()", typed)

    def checkbox_modes(self):
        self.task_source = "- [ ] Task changes require Edit mode.\n"

        def opened(doc):
            def read_toggled(state):
                self.require(state == {"readonly": "true", "checked": "false"}, f"Read mode task checkbox changed: {state}")
                self.serialize(doc, read_clean)

            def read_clean(message):
                self.expect_clean(doc, message, self.task_source, "Clicking a task in Read mode")
                self.window.mode_changed("edit")
                self.wait_mode(doc, "edit", lambda: self.task_action(doc, "pointer", pointer_toggled))

            def pointer_toggled(state):
                self.require(state == {"readonly": "false", "checked": "true"}, f"Pointer did not toggle the task: {state}")
                self.serialize(doc, pointer_serialized)

            def pointer_serialized(message):
                self.require(message.get("dirty") is True and "[x] Task changes require Edit mode." in message["markdown"],
                             "Pointer task change was not dirty")
                self.evaluate(doc, "(()=>{" + self.click("Undo (Ctrl+Z)") + "return true;})()",
                              lambda _: self.serialize(doc, pointer_undone))

            def pointer_undone(message):
                self.expect_clean(doc, message, self.task_source, "Undoing a pointer task toggle")
                self.task_action(doc, "Space", space_toggled)

            def space_toggled(state):
                self.require(state == {"readonly": "false", "checked": "true"}, f"Space did not check the task: {state}")
                self.task_action(doc, "Enter", enter_toggled)

            def enter_toggled(state):
                self.require(state == {"readonly": "false", "checked": "false"}, f"Enter did not uncheck the task: {state}")
                self.serialize(doc, keyboard_clean)

            def keyboard_clean(message):
                self.expect_clean(doc, message, self.task_source, "Space followed by Enter")
                self.task_action(doc, "Space", lambda _: self.serialize(doc, ready_to_save))

            def ready_to_save(message):
                self.require(message.get("dirty") is True and "[x] Task changes require Edit mode." in message["markdown"],
                             "Task edit was not included in checked serialization")
                self.saved_task_source = message["markdown"]
                self.window.save(doc, done=self.guard(saved))

            def saved(okay):
                self.require(okay, "Task-checkbox save failed")
                self.expected_sources[doc.path] = self.saved_task_source.encode("utf-8")
                self.serialize(doc, checked)

            def checked(message):
                self.expect_clean(doc, message, self.saved_task_source, "Saved task checkbox")
                self.window.mode_changed("read")
                self.wait_mode(doc, "read", lambda: self.task_action(doc, "all", back_in_read))

            def back_in_read(state):
                self.require(state == {"readonly": "true", "checked": "true"}, f"Returning to Read left the task mutable: {state}")
                self.serialize(doc, readonly_saved)

            def readonly_saved(message):
                self.expect_clean(doc, message, self.saved_task_source, "Task interaction after returning to Read")
                self.record("Task pointer toggles undo cleanly; Space/Enter toggle in Edit; saved tasks remain immutable in Read")
                self.cached_visuals()

            self.task_action(doc, "all", read_toggled)

        self.fixture("checkbox-modes", self.task_source, opened, edit=False)

    def task_action(self, doc, action, done):
        pointer_down = "task.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,cancelable:true}));"
        pointer = pointer_down + "task.click();"
        space = "task.focus();task.dispatchEvent(new KeyboardEvent('keydown',{key:' ',bubbles:true,cancelable:true}));"
        enter = "task.focus();task.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));"
        unchanged = "if(task.getAttribute('aria-checked')!==before)throw new Error('A Read-mode task handler changed its state');"
        all_read = "const before=task.getAttribute('aria-checked');" + "".join(step + unchanged for step in (pointer_down, "task.click();", space, enter))
        actions = {"pointer": pointer, "Space": space, "Enter": enter, "all": all_read}
        expression = "(()=>{const task=document.querySelector('#editor [role=\"checkbox\"]');if(!task)throw new Error('Task checkbox missing');" + actions[action] + ";return {readonly:task.getAttribute('aria-readonly'),checked:task.getAttribute('aria-checked')};})()"
        self.evaluate(doc, expression, done)

    def wait_dom(self, doc, expression, done, label, timeout=25):
        deadline = time.monotonic() + timeout

        def inspected(ready):
            if ready:
                done()
            else:
                self.require(time.monotonic() < deadline, "Timed out waiting for " + label)
                self.delay(check, 75)

        def check():
            self.evaluate(doc, expression, inspected)

        check()

    def cached_visuals(self):
        self.visual_source = """# Cached document visuals

An inline equation $x^2 + y^2 = z^2$ stays rendered.

```python title="cached.py"
print("Keep this highlighted preview")
```

```mermaid
flowchart LR
    Read --> Edit
```

![Unavailable Markdown image](missing-cached-image.png)

<div><img src="missing-embedded-image.png" alt="Unavailable embedded image"></div>
"""

        def opened(doc):
            self.wait_mode(doc, "read", lambda: self.wait_dom(doc,
                self.visual_ready("read"), lambda: capture(doc, "read", lambda: enter_edit(doc)),
                "initial cached diagrams, equations, code and missing image placeholders"))

        def capture(doc, mode, done):
            key = "__cachedReadingVisuals" if mode == "read" else "__cachedEditorVisuals"
            root = ".reading-document" if mode == "read" else ".ProseMirror"
            code = ".code-block>pre" if mode == "read" else ".code-preview:not(.diagram-preview)>pre"
            expression = """(()=>{const diagram=document.querySelector('.diagram-preview>svg');
                const cached={diagram,root:document.querySelector(ROOT),math:document.querySelector('.katex'),code:document.querySelector(CODE),added:0};
                window[KEY]=cached;
                cached.observer=new MutationObserver(records=>{
                    for(const record of records)for(const node of record.addedNodes)
                        if(node instanceof SVGElement && node.tagName.toLowerCase()==='svg')cached.added++;
                });cached.observer.observe(diagram.parentElement,{childList:true});return true;})()"""
            expression = expression.replace("ROOT", json.dumps(root)).replace("CODE", json.dumps(code)).replace("KEY", json.dumps(key))
            self.evaluate(doc, expression, lambda _: done())

        def enter_edit(doc):
            self.window.mode_changed("edit")
            self.wait_mode(doc, "edit", lambda: self.wait_dom(doc, self.visual_ready("edit"),
                lambda: capture(doc, "edit", lambda: return_read(doc)), "initial editor visuals"))

        def return_read(doc):
            self.window.mode_changed("read")
            self.wait_mode(doc, "read", lambda: self.evaluate(doc, self.visual_identity("read"),
                lambda state: read_retained(doc, state)))

        def read_retained(doc, state):
            self.check_visual_identity(state, "read", added=0)
            self.window.mode_changed("edit")
            self.wait_mode(doc, "edit", lambda: self.evaluate(doc, self.visual_identity("edit"),
                lambda state: edit_retained(doc, state)))

        def edit_retained(doc, state):
            self.check_visual_identity(state, "edit", added=0)
            self.record("Read/Edit cycles separately retain each view's root, diagram SVG, KaTeX and highlighted code without changing their content")
            self.window.mode_changed("read")
            self.wait_mode(doc, "read", lambda: dark_theme(doc))

        def dark_theme(doc):
            self.window.set_theme("dark")
            self.wait_dom(doc, "!!document.querySelector('.diagram-preview>svg') && document.querySelector('.diagram-preview>svg')!==window.__cachedReadingVisuals.diagram",
                          lambda: self.evaluate(doc, self.visual_identity("read"), lambda state: dark_checked(doc, state)), "dark reading diagram rerender")

        def dark_checked(doc, state):
            self.check_visual_identity(state, "read", diagram=False, added=1, theme="dark")
            self.evaluate(doc, "(()=>{window.__cachedReadingVisuals.diagram=document.querySelector('.diagram-preview>svg');return true;})()",
                          lambda _: dark_edit(doc))

        def dark_edit(doc):
            self.window.mode_changed("edit")
            self.wait_mode(doc, "edit", lambda: self.wait_dom(doc,
                "!!document.querySelector('.diagram-preview>svg') && document.querySelector('.diagram-preview>svg')!==window.__cachedEditorVisuals.diagram",
                lambda: self.evaluate(doc, self.visual_identity("edit"), lambda state: dark_editor_checked(doc, state)),
                "dark retained editor diagram rerender"))

        def dark_editor_checked(doc, state):
            self.check_visual_identity(state, "edit", diagram=False, added=1, theme="dark")
            self.window.mode_changed("read")
            self.wait_mode(doc, "read", lambda: self.evaluate(doc,
                "(()=>{window.reader.setTheme('dark');return true;})()",
                lambda _: self.evaluate(doc, self.visual_identity("read"), lambda state: unchanged_theme(doc, state))))

        def unchanged_theme(doc, state):
            self.check_visual_identity(state, "read", added=1, theme="dark")
            self.record("Changing theme rerenders each view's diagram once while equations and code stay stable; an unchanged theme retains the reading diagram")
            # Force a same-source frontend reload to exercise reuse of retained
            # unavailable image views and their error records.
            doc.load_frontend()
            self.wait_mode(doc, "read", lambda: self.evaluate(doc, self.visual_identity("read"), lambda state: refreshed(doc, state)))

        def refreshed(doc, state):
            self.check_visual_identity(state, "read", added=1, theme="dark")
            self.evaluate(doc, "({unavailable:document.querySelectorAll('img.unavailable').length,withSource:document.querySelectorAll('img.unavailable[src]').length})",
                          lambda images: missing_images(doc, images))

        def missing_images(doc, images):
            self.require(images == {"unavailable": 2, "withSource": 0}, f"Missing local images did not remain source-free placeholders: {images}")
            doc.request("prepareExport", self.guard(lambda message: exported(doc, message)))

        def exported(doc, message):
            self.require(message.get("ok", True), message.get("error", "Export preparation failed"))
            issues = message.get("issues", [])
            for filename in ("missing-cached-image.png", "missing-embedded-image.png"):
                self.require(any("Image unavailable" in issue and filename in issue for issue in issues),
                             f"Same-content refresh lost the export warning for {filename}: {issues}")

            class ImageSources(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.unavailable_sources = []

                def handle_starttag(self, tag, attributes):
                    attrs = dict(attributes)
                    if tag == "img" and "unavailable" in attrs.get("class", "").split() and attrs.get("src"):
                        self.unavailable_sources.append(attrs["src"])

            html = message.get("html", "")
            images = ImageSources()
            images.feed(html)
            self.require(not images.unavailable_sources, f"Unavailable image URLs entered export HTML: {images.unavailable_sources}")
            self.require('class="katex"' in html and "<svg" in html and "Keep this highlighted preview" in html,
                         "Export HTML omitted a cached equation, diagram or code preview")
            self.record("Same-content refresh preserves missing-image export warnings and exports cached visuals without unavailable image URLs", issues)
            doc.call("exportFinished")
            self.evaluate(doc, "(()=>{window.__cachedReadingVisuals.observer.disconnect();window.__cachedEditorVisuals.observer.disconnect();return true;})()",
                          lambda _: self.serialize(doc, lambda serialized: visual_clean(doc, serialized)))

        def visual_clean(doc, message):
            self.expect_clean(doc, message, self.visual_source, "Cached visual rendering and export")
            self.folding_refresh()

        self.fixture("cached-visuals", self.visual_source, opened, edit=False)

    def folding_refresh(self):
        source = "> [!NOTE]- Initially folded\n> Original callout body.\n"

        def opened(doc):
            def initial(hidden):
                self.require(hidden, "A minus callout must start folded")
                self.fold_cases = [("", False, True), ("+", False, False), ("-", True, False), ("+", False, False)]
                self.window.mode_changed("edit")
                self.wait_mode(doc, "edit", lambda: self.evaluate(doc,
                    "(()=>{window.__foldCallout=document.querySelector('.callout');return !!window.__foldCallout;})()", capture_editor))

            def capture_editor(present):
                self.require(present, "Editor callout view is missing")
                next_refresh()

            def next_refresh():
                if not self.fold_cases:
                    self.record("Reused editor callouts adopt changed folding markers; Read shows each marker's expected fold state without hiding nonfolding callouts")
                    self.stale_source_dialog()
                    return
                marker, hidden, disabled = self.fold_cases.pop(0)
                updated = "> [!NOTE]" + marker + " Updated title " + str(time.time_ns()) + "\n> Fresh agent callout body.\n"
                previous_revision = doc.revision
                doc.path.write_text(updated, encoding="utf-8")
                self.expected_sources[doc.path] = updated.encode("utf-8")

                def refreshed():
                    expression = """(()=>{const callout=document.querySelector('.callout'),label=callout.querySelector('.callout-label');return {
                        same:callout===window.__foldCallout,hidden:callout.querySelector(':scope>div').hidden,
                        disabled:label.disabled,folded:label.textContent.startsWith('▸'),text:callout.textContent};})()"""
                    self.wait_mode(doc, "edit", lambda: self.evaluate(doc, expression, inspected))

                def inspected(state):
                    self.require(state["same"], "Folding regression did not exercise a reused callout view")
                    self.require(not state["hidden"] and state["folded"] == hidden and state["disabled"] == disabled,
                                 f"Editor callout marker {marker!r} has wrong folding state: {state}")
                    self.require("Fresh agent callout body." in state["text"], "Callout still shows obsolete source")
                    self.window.mode_changed("read")
                    self.wait_mode(doc, "read", inspect_reading)

                def inspect_reading():
                    expression = """(()=>{const callout=document.querySelector('.reading-callout');return {
                        hidden:callout.querySelector('.reading-callout-content').hidden,
                        folding:callout.querySelector('.callout-label').tagName==='BUTTON',text:callout.textContent};})()"""
                    self.evaluate(doc, expression, reading_inspected)

                def reading_inspected(state):
                    self.require(state["hidden"] == hidden and state["folding"] == (not disabled),
                                 f"Reading callout marker {marker!r} has wrong folding state: {state}")
                    self.require("Fresh agent callout body." in state["text"], "Reading callout still shows obsolete source")
                    self.serialize(doc, checked)

                def checked(message):
                    self.expect_clean(doc, message, updated, "Callout marker refresh")
                    self.window.mode_changed("edit")
                    self.wait_mode(doc, "edit", next_refresh)

                self.wait_for(lambda: doc.loaded and doc.revision > previous_revision and doc.text == updated,
                              refreshed, "callout folding-marker refresh")

            self.wait_mode(doc, "read", lambda: self.evaluate(doc,
                "document.querySelector('.reading-callout-content').hidden", initial))

        self.fixture("folding-refresh", source, opened, edit=False)

    def stale_source_dialog(self):
        source = "# Equation source\n\nOriginal equation $a+b$.\n"
        updated = "# Equation source\n\nLatest agent equation $c+d$.\n"

        def opened(doc):
            expression = """(()=>{const equation=document.querySelector('.protected-inline[data-kind="inlineMath"]');
                if(!equation)throw new Error('Equation missing');
                equation.dispatchEvent(new MouseEvent('dblclick',{bubbles:true}));
                const dialog=document.querySelector('dialog.source-dialog');
                if(!dialog?.open)throw new Error('Equation dialog did not open');
                window.__obsoleteSourceForm=dialog.querySelector('form');
                dialog.querySelector('textarea').value='OBSOLETE_SOURCE';return true;})()"""
            def write_external(_):
                previous_revision = doc.revision
                doc.path.write_text(updated, encoding="utf-8")
                self.expected_sources[doc.path] = updated.encode("utf-8")
                self.wait_for(lambda: doc.loaded and doc.revision > previous_revision and doc.text == updated,
                              refreshed, "agent refresh during source dialog")

            def refreshed():
                expression = """(()=>{const closed=!document.querySelector('dialog.source-dialog[open]');
                    window.__obsoleteSourceForm.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));
                    return closed;})()"""
                self.wait_mode(doc, "edit", lambda: self.evaluate(doc, expression, obsolete_applied))

            def obsolete_applied(closed):
                self.require(closed, "Agent refresh left an obsolete source dialog open")
                self.serialize(doc, checked)

            def checked(message):
                self.expect_clean(doc, message, updated, "Obsolete source-dialog submission after refresh")
                self.require("OBSOLETE_SOURCE" not in message["markdown"], "Obsolete source dialog overwrote the agent's equation")
                self.record("Agent refresh closes a source dialog and its stale Apply callback cannot change the latest document")
                self.finish()

            self.evaluate(doc, expression, write_external)

        self.fixture("stale-source-dialog", source, opened)

    def visual_ready(self, mode):
        code = ".code-block>pre" if mode == "read" else ".code-preview:not(.diagram-preview)>pre"
        return ("!!document.querySelector('.diagram-preview>svg') && !!document.querySelector('.katex') && "
                "!!document.querySelector(" + json.dumps(code + " .hljs-string") + ") && document.querySelectorAll('img.unavailable').length===2")

    def visual_identity(self, mode):
        key = "__cachedReadingVisuals" if mode == "read" else "__cachedEditorVisuals"
        root = ".reading-document" if mode == "read" else ".ProseMirror"
        code = ".code-block>pre" if mode == "read" else ".code-preview:not(.diagram-preview)>pre"
        expression = """(()=>{const cached=window[KEY],diagram=document.querySelector('.diagram-preview>svg'),
            math=document.querySelector('.katex'),code=document.querySelector(CODE);return {
            root:cached.root===document.querySelector(ROOT),diagram:cached.diagram===diagram,
            math:cached.math===math,code:cached.code===code,added:cached.added,
            equation:math?.querySelector('annotation[encoding="application/x-tex"]')?.textContent,
            codeText:code?.textContent,diagramText:diagram?.textContent,theme:document.documentElement.dataset.theme};})()"""
        return expression.replace("KEY", json.dumps(key)).replace("ROOT", json.dumps(root)).replace("CODE", json.dumps(code))

    def check_visual_identity(self, state, mode, diagram=True, added=0, theme="light"):
        expected = {"root": True, "diagram": diagram, "math": True, "code": True, "added": added}
        self.require({key: state[key] for key in expected} == expected,
                     f"The {mode} view rebuilt unexpected visuals: {state}")
        self.require(state["equation"] == "x^2 + y^2 = z^2", f"The {mode} equation changed: {state}")
        self.require(state["codeText"].strip() == 'print("Keep this highlighted preview")', f"The {mode} code changed: {state}")
        self.require("Read" in state["diagramText"] and "Edit" in state["diagramText"], f"The {mode} diagram lost its labels: {state}")
        self.require(state["theme"] == theme, f"The {mode} view has the wrong theme: {state}")

    def finish(self):
        if not self.done:
            for path, expected in self.expected_sources.items():
                try:
                    unchanged = path.read_bytes() == expected
                except OSError:
                    unchanged = False
                self.record("Disposable source protection: " + path.name,
                            "matches expected bytes" if unchanged else "unexpected source change",
                            "passed" if unchanged else "failed")
                self.failed |= not unchanged
        super().finish()


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--output", type=Path, default=PROJECT / "work/performance-correctness")
    args = arguments.parse_args()
    raise SystemExit(NativePerformanceCorrectness(args.output).run())
