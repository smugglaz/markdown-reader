#!/usr/bin/env python3
"""Additional real GTK/WebKit toolbar, sanitization, and failure-state checks.

All edits use disposable documents under --output and isolated application state.
TextSelection is the only editor test helper: formatting runs actual toolbar DOM
handlers. Physical keyboard/clipboard and file-picker UX remain manual checks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_smoke import NativeSmoke, PROJECT, GLib, sha


class NativeFeatures(NativeSmoke):
    def start(self):
        self.window = self.app.ensure_window()
        self.window.present()
        self.window.set_theme("light")
        self.fixture("marks", "Alpha bold Beta italic Gamma strike Delta code.\n", self.marks)
        return GLib.SOURCE_REMOVE

    def fixture(self, name, source, done, edit=True):
        path = self.fixtures / f"feature-{name}.md"
        path.write_text(source, encoding="utf-8")
        doc = self.window.open_path(str(path))
        self.doc = doc
        def ready():
            self.require(doc.loaded, "Fixture did not load")
            if edit:
                self.require(doc.editable, f"{name} is not editable: {doc.edit_reason}")
                self.window.mode_changed("edit")
            self.delay(lambda: done(doc), 180)
        self.wait_for(lambda: doc.loaded, ready, f"{name} fixture")

    def act(self, doc, body, done):
        self.evaluate(doc, "(()=>{" + body + ";return window.reader.inspect();})()", done)

    def select(self, text):
        return "window.reader.testSelectText(" + json.dumps(text) + ");"

    def click(self, label):
        return "document.querySelector('#toolbar button[aria-label=" + json.dumps(label) + "]').click();"

    def choose(self, label, value):
        if label == "Paragraph style":
            return self.click("Text style") + "document.querySelector('#toolbar [data-style=" + json.dumps(value) + "]').click();"
        options = {"table": "Table", "row": "Add row", "col": "Add column", "delrow": "Delete row", "delcol": "Delete column"}
        menu = "Insert" if value == "table" else "Table"
        return "document.querySelector('#toolbar .menu-trigger[aria-label=" + json.dumps(menu) + "]').click();document.querySelector('#toolbar [role=menuitem][aria-label=" + json.dumps(options[value]) + "]').click();"

    def marks(self, doc):
        cases = [("bold", "Bold (Ctrl+B)", "strong"), ("italic", "Italic (Ctrl+I)", "em"),
                 ("strike", "Strikethrough", "del"), ("code", "Inline code", "code")]
        def step(index=0):
            if index == len(cases):
                self.undo_redo(doc)
                return
            text, label, tag = cases[index]
            def changed(state):
                def checked(found):
                    self.require(found, f"Toolbar {label} did not format the selected text")
                    self.record("Actual toolbar " + label)
                    step(index + 1)
                self.evaluate(doc, f"[...document.querySelectorAll('#editor {tag}')].some(x=>x.textContent==={json.dumps(text)})", checked)
            self.act(doc, self.select(text) + self.click(label), changed)
        step()

    def undo_redo(self, doc):
        def undone(_state):
            def no_code(found):
                self.require(not found, "Undo retained the most recent inline-code mark")
                self.act(doc, self.click("Redo (Ctrl+Shift+Z)"), redone)
            self.evaluate(doc, "[...document.querySelectorAll('#editor code')].some(x=>x.textContent==='code')", no_code)
        def redone(_state):
            def has_code(found):
                self.require(found, "Redo did not restore the inline-code mark")
                self.record("Toolbar undo and redo restore editor transactions")
                self.serialize(doc, lambda _message: self.fixture("heading", "Heading sample\n", self.heading))
            self.evaluate(doc, "[...document.querySelectorAll('#editor code')].some(x=>x.textContent==='code')", has_code)
        self.act(doc, self.click("Undo (Ctrl+Z)"), undone)

    def serialize(self, doc, done):
        def serialized(message):
            self.require(message.get("ok", True), message.get("error", "Document failed preservation checks"))
            done(message)
        doc.request("serialize", self.guard(serialized))

    def heading(self, doc):
        def changed(state):
            self.require(state["markdown"].startswith("## Heading sample"), "Heading selection did not produce level 2")
            self.record("Toolbar heading level selection")
            self.list_cases = [("bullet", "• List", "ul"), ("ordered", "Numbered list", "ol"), ("task", "Task list", "task")]
            self.list_case()
        self.act(doc, self.select("Heading sample") + self.choose("Paragraph style", "2"), changed)

    def list_case(self):
        if not self.list_cases:
            self.fixture("table-insert", "Table insertion anchor.\n", self.insert_table)
            return
        name, label, kind = self.list_cases.pop(0)
        def ready(doc):
            actual_label = "Bullet list" if name == "bullet" else label
            def changed(state):
                if kind == "task":
                    self.require("[ ]" in state["markdown"] or "[x]" in state["markdown"], "Task-list toolbar did not create a task marker")
                    checked(True)
                else:
                    self.evaluate(doc, f"!!document.querySelector('#editor {kind} li')", checked)
            def checked(ok):
                self.require(ok, f"{name} list not represented in the document")
                self.record("Toolbar " + name + " list")
                self.serialize(doc, lambda _message: self.list_case())
            self.act(doc, self.select("List sample") + self.click(actual_label), changed)
        self.fixture("list-" + name, "List sample\n", ready)

    def insert_table(self, doc):
        def changed(_state):
            def checked(result):
                self.require(result["count"] == 1, f"Insert Table did not create exactly one table: {result}")
                self.record("Toolbar Insert Table")
                self.fixture("table-operations", "| CellA | CellB |\n| --- | --- |\n| CellC | CellD |\n", self.table_operations)
            self.evaluate(doc, "({count:[...document.querySelectorAll('#editor table')].filter(t=>t.rows.length).length,markdown:window.reader.inspect().markdown})", checked)
        self.act(doc, self.select("Table insertion anchor.") + self.choose("Insert and table tools", "table"), changed)

    def table_operations(self, doc):
        cases = [("CellC", "row", 3, 2), ("CellC", "delrow", 2, 2),
                 ("CellA", "col", 2, 3), ("CellA", "delcol", 2, 2)]
        def step(index=0):
            if index == len(cases):
                self.serialize(doc, lambda _message: self.security())
                return
            anchor, action, rows, cols = cases[index]
            def changed(_state):
                def checked(size):
                    self.require(size == [rows, cols], f"Table {action}: expected {[rows, cols]}, got {size}")
                    self.record("Toolbar table " + action, {"rows": rows, "columns": cols})
                    step(index + 1)
                self.evaluate(doc, "(()=>{const t=[...document.querySelectorAll('#editor table')].find(t=>t.rows.length);return [t.rows.length,t.rows[0].cells.length];})()", checked)
            self.act(doc, self.select(anchor) + self.choose("Insert and table tools", action), changed)
        step()

    def security(self):
        source = '''# Unsafe markup stays inert

<div><script>window.__readerAttack = 'executed'</script><img src="missing.png" onerror="window.__readerAttack='event'"><a href="javascript:window.__readerAttack='link'">Unsafe link</a><iframe srcdoc="<script>parent.__readerAttack='frame'</script>"></iframe><svg onload="window.__readerAttack='svg'"><text>SVG content</text></svg>Safe visible text.</div>
'''
        def ready(doc):
            self.security_hash = sha(doc.path)
            def checked(result):
                self.require(not result["attack"], "Document script or event handler ran")
                self.require(result["dangerous"] == 0, f"Unsafe markup survived sanitization: {result}")
                self.require("Safe visible text." in result["text"], "Sanitization removed safe document text")
                self.require(sha(doc.path) == self.security_hash, "Rendering rewrote the original unsafe source")
                self.record("HTML scripts, event handlers, frames and javascript links remain inert")
                self.missing_image()
            expression = "({attack:window.__readerAttack||null,dangerous:document.querySelectorAll('#editor script,#editor iframe,#editor [onerror],#editor [onload],#editor a[href^=\"javascript:\"]').length,text:document.querySelector('#editor').innerText})"
            self.evaluate(doc, expression, checked)
        self.fixture("unsafe-html", source, ready, edit=False)

    def missing_image(self):
        def ready(doc):
            def checked(message):
                issues = message.get("issues", [])
                self.require(any("Image unavailable" in issue for issue in issues), f"Missing local image did not block clean export: {issues}")
                self.record("Export preparation reports a missing local image", issues)
                doc.call("exportFinished")
                self.fixture("disappearance", "# Original readable text\n", self.disappear, edit=False)
            doc.request("prepareExport", self.guard(checked))
        self.fixture("missing-image", "# Missing image\n\n![Unavailable](never-created.png)\n", ready, edit=False)

    def disappear(self, doc):
        original = doc.text
        doc.path.unlink()
        def missing():
            self.require(doc.text == original, "A transient missing file destroyed the last readable document")
            self.record("Deleted file retains last readable content and reports an error")
            doc.path.write_text("# Reappeared document\n\nAn agent recreated this file.\n")
            self.wait_for(lambda: doc.loaded and "Reappeared document" in doc.text, lambda: restored(), "deleted file reappearance")
        def restored():
            self.require(not doc.banner.get_visible(), "Missing-file error remained after recovery")
            self.record("Directory watcher recovers after deletion and reappearance")
            self.fixture("readonly", "# Protected original\n\nPermission test.\n", self.readonly)
        self.wait_for(lambda: doc.banner.get_visible() and "Cannot read" in doc.banner_label.get_text(), missing, "missing-file error banner")

    def readonly(self, doc):
        before = doc.path.read_bytes()
        doc.path.chmod(0o444)
        def edited(_state):
            def checked(okay):
                doc.path.chmod(0o644)
                self.require(not okay, "Saving a read-only file unexpectedly succeeded")
                self.require(doc.path.read_bytes() == before, "Failed save modified the original bytes")
                self.require(doc.dirty, "Failed save discarded the edited buffer")
                self.record("Read-only save failure preserves original and edited buffer")
                self.renderer_failure(doc)
            self.window.save(doc, done=self.guard(checked))
        self.act(doc, "window.reader.testInsertText(' Unsaved recovery text.');", edited)

    def renderer_failure(self, doc):
        doc.web.terminate_web_process()
        def stopped():
            drafts = self.app.store.load_drafts()
            self.require("Unsaved recovery text." in drafts.get(doc.id, {}).get("text", ""), "Renderer termination lost the latest native recovery buffer")
            self.record("Renderer termination preserves the unsaved recovery draft")
            self.record("Physical clipboard interaction", "Not automated; user clipboard was preserved", "manual")
            self.finish()
        self.wait_for(lambda: "renderer stopped" in doc.banner_label.get_text().lower(), stopped, "renderer termination notice")


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--output", type=Path, default=PROJECT / "work/native-features")
    args = arguments.parse_args()
    raise SystemExit(NativeFeatures(args.output).run())
