#!/usr/bin/env python3
"""Inspect readability changes in the real GTK/WebKit view with disposable files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from native_smoke import NativeSmoke, PROJECT, GLib, Gtk, sha


SAMPLE = """# A readable document

Normal paragraphs explain the purpose of a document.

## Tables and lists

- A longer list item should wrap under its text and keep the marker aligned.
- [ ] An unsaved task should stay visible.

| Detail | Purpose | Number |
| --- | --- | ---: |
| Normal text | Read easily | 42 |
| Headings | Find sections | 100 |

> [!WARNING] Check before saving
> An agent may update this file while it is open.

```python
# This comment should be legible in both themes.
print("A very long line stays complete: abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789")
```

```html
<div class="notice">A readable document</div>
```

## A later section

""" + ("A paragraph with enough words to test navigation and scrolling.\n\n" * 24)


class NativeReadability(NativeSmoke):
    def start(self):
        self.window = self.app.ensure_window()
        self.window.present()
        self.window.set_theme("light")
        self.window.set_default_size(1120, 820)
        self.window_paintable = Gtk.WidgetPaintable.new(self.window)
        self.require(not self.window.mode_box.get_visible(), "Read/Edit appears on welcome")
        self.require(not self.window.find_button.get_visible(), "Find appears on welcome")
        self.require(not self.window.outline_button.get_visible(), "Contents appears on welcome")
        path = self.fixtures / "readability.md"
        path.write_text(SAMPLE)
        self.source_hash = sha(path)
        self.doc = self.window.open_path(str(path))
        self.wait_for(lambda: self.doc.loaded, self.read, "readability fixture")
        return GLib.SOURCE_REMOVE

    def read(self):
        expression = """(()=>{const th=[...document.querySelectorAll('.reading-table th')];
          const block=document.querySelector('.code-block');
          return {align:th.map(x=>getComputedStyle(x).textAlign),
            border:getComputedStyle(th[0]).borderColor,
            callout:document.querySelector('.reading-callout .callout-label')?.textContent,
            controls:[...block.querySelectorAll('.code-actions button')].map(x=>x.textContent),
            original:block.querySelector('pre').textContent,
            viewport:innerWidth,scroll:document.documentElement.scrollWidth};})()"""
        def checked(value):
            self.require(value["align"][:2] == ["left", "left"], f"Read table headings not aligned: {value}")
            self.require(value["align"][2].endswith("right"), f"Explicit Markdown alignment lost: {value}")
            self.require(value["callout"] == "Warning · Check before saving", f"Callout type missing: {value}")
            self.require("Wrap lines" in value["controls"] and "Expand" in value["controls"], "Code controls missing")
            self.require(value["scroll"] <= value["viewport"] + 1, "Page scrolls sideways")
            self.read_border = value["border"]
            self.original_code = value["original"]
            self.code_controls()
        self.evaluate(self.doc, expression, checked)

    def code_controls(self):
        expression = """(()=>{const block=document.querySelector('.code-block');
          block.querySelector('button[title^="Fit long lines"]').click();
          const wrapped=block.querySelector('pre').classList.contains('wrapped');
          block.querySelector('button[title^="Open this block"]').click();
          const dialog=document.querySelector('dialog.reader-focus-dialog');
          const source=dialog?.querySelector('pre')?.textContent;
          dialog?.querySelector('.reader-focus-heading button')?.click();
          return {wrapped,source,closed:!document.querySelector('dialog.reader-focus-dialog[open]')};})()"""
        def checked(value):
            self.require(value == {"wrapped": True, "source": self.original_code, "closed": True},
                         f"Code wrap/expand changed source: {value}")
            self.record("Code wraps or expands while preserving exact source")
            self.evaluate(self.doc, """(()=>{document.querySelector('.table-expand').click();
                const dialog=document.querySelector('dialog.reader-focus-dialog');
                return {open:dialog?.open,cells:dialog?.querySelectorAll('td').length};})()""", self.table_expanded)
        self.evaluate(self.doc, expression, checked)

    def table_expanded(self, value):
        self.require(value == {"open": True, "cells": 6}, f"Focused table lost its cells: {value}")
        self.window.mode_changed("edit")
        self.wait_mode(self.doc, "edit", self.edit)

    def edit(self):
        expression = """(()=>{const th=[...document.querySelectorAll('.milkdown th')];
          return {align:th.map(x=>getComputedStyle(x).textAlign),border:getComputedStyle(th[0]).borderColor,
            menu:[...document.querySelectorAll('#text-style + .format-menu [data-style]')].map(x=>x.textContent),
            more:!!document.querySelector('#toolbar .toolbar-more'),
            callout:document.querySelector('.callout-label')?.textContent};})()"""
        def checked(value):
            self.require(value["align"][:2] == ["left", "left"] and value["align"][2] == "right",
                         f"Edit table alignment changed: {value}")
            self.require(value["border"] == self.read_border, f"Read/Edit table borders differ: {value}")
            self.require(any("Body of the document" in x for x in value["menu"]), "Normal text is unexplained")
            self.require(value["more"] and "Warning" in value["callout"], "Formatting or callout labels missing")
            self.record("Read and Edit share table alignment, borders, and callout type")
            self.evaluate(self.doc, "!!document.querySelector('dialog.reader-focus-dialog[open]')", self.dialog_closed)
        self.evaluate(self.doc, expression, checked)

    def dialog_closed(self, still_open):
        self.require(not still_open, "Focused table covered the editor after changing modes")
        self.record("Focused table closes when changing modes")
        self.scroll_check()

    def scroll_check(self):
        def positioned(value):
            self.require(value >= 300, f"Long fixture did not scroll: {value}")
            self.edit_scroll = value
            self.window.mode_changed("read")
            self.wait_mode(self.doc, "read", self.scroll_read)
        self.evaluate(self.doc, "(window.scrollTo(0,600),window.scrollY)", positioned)

    def scroll_read(self):
        def checked(value):
            self.require(abs(value-self.edit_scroll) <= 65,
                         f"Read mode moved away from the visible passage: {self.edit_scroll} -> {value}")
            self.window.mode_changed("edit")
            self.wait_mode(self.doc, "edit", self.scroll_edit)
        self.delay(lambda:self.evaluate(self.doc, "window.scrollY", checked), 150)

    def scroll_edit(self):
        def checked(value):
            self.require(abs(value-self.edit_scroll) <= 65,
                         f"Returning to Edit moved away from the visible passage: {self.edit_scroll} -> {value}")
            self.record("Read/Edit preserves the visible passage", {"edit":self.edit_scroll,"returned":value})
            self.window.set_default_size(620, 820)
            self.window.zoom_by(.4)
            self.delay(self.narrow, 300)
        self.delay(lambda:self.evaluate(self.doc, "window.scrollY", checked), 150)

    def narrow(self):
        self.doc.call("toggleOutline")
        self.delay(self.narrow_checked, 250)

    def narrow_checked(self):
        expression = """(()=>{const nav=document.querySelector('#outline'),main=document.querySelector('#main');
          return {width:innerWidth,scroll:document.documentElement.scrollWidth,
            compact:document.body.classList.contains('compact-outline'),
            textSize:parseFloat(getComputedStyle(document.querySelector('#outline-items a')).fontSize),
            mainLeft:main.getBoundingClientRect().left,
            backdrop:getComputedStyle(document.querySelector('.outline-backdrop')).display,
            current:!!nav.querySelector('a[aria-current=location]'),
            toolbarHeight:document.querySelector('#toolbar').getBoundingClientRect().height};})()"""
        def checked(value):
            self.require(value["compact"] and value["mainLeft"] < 2 and value["backdrop"] != "none",
                         f"Contents still squeezes the article: {value}")
            self.require(value["textSize"] >= 18 and value["current"], f"Contents is too small or has no location: {value}")
            self.require(value["scroll"] <= value["width"] + 1, f"Narrow page overflows: {value}")
            self.require(value["toolbarHeight"] < 50, f"Compact toolbar wrapped into extra rows: {value}")
            self.record("Narrow enlarged-text Contents overlays the article", value)
            self.snapshot(self.doc, "native-narrow-contents.png", self.close_outline)
        self.evaluate(self.doc, expression, checked)

    def close_outline(self):
        self.evaluate(self.doc, "(document.querySelector('.outline-close').click(),document.body.classList.contains('show-outline'))",
                      lambda shown: self.after_close(shown))

    def after_close(self, shown):
        self.require(not shown, "Contents close button failed")
        self.window.mode_changed("read")
        self.wait_mode(self.doc, "read", self.dark)

    def dark(self):
        self.window.set_theme("dark")
        self.delay(self.dark_checked, 200)

    def dark_checked(self):
        expression = """(()=>{const pre=document.querySelector('.code-block pre');
          return {background:getComputedStyle(pre).backgroundColor,
            comments:[...pre.querySelectorAll('.hljs-comment')].map(x=>getComputedStyle(x).color),
            callout:document.querySelector('.reading-callout .callout-label')?.textContent};})()"""
        def checked(value):
            self.require(value["comments"] and value["comments"][0] == "rgb(175, 182, 194)",
                         f"Dark comments still faint: {value}")
            self.require("Warning" in value["callout"], f"Dark callout lost its type: {value}")
            self.record("Dark code comments use the stronger palette", value)
            self.snapshot(self.doc, "native-dark-code.png", self.finish)
        self.evaluate(self.doc, expression, checked)

    def finish(self):
        self.require(sha(self.fixtures / "readability.md") == self.source_hash,
                     "Readability checks changed the original document")
        super().finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "work/native-readability")
    args = parser.parse_args()
    raise SystemExit(NativeReadability(args.output).run())
