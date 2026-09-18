#!/usr/bin/env python3
"""Native design regression checks using isolated, disposable documents."""
from pathlib import Path
import argparse
import json

from native_features import NativeFeatures, PROJECT, GLib
from native_smoke import Gtk


SAMPLE = """# A place for clear thoughts

Normal text should feel natural. A little **emphasis** belongs here.

## A simple plan

Start with the essentials:

- Read a beautifully formatted document.
- Write a longer thought that wraps naturally onto another line while its bullet stays aligned with the first line and the continuation follows the text.
  - Keep related ideas together.
- [ ] Make a small change, then save when ready.

10. Review the details.
11. Keep every word safe.

| Detail | Purpose |
| --- | --- |
| Normal text | Write without ceremony |
| Clear headings | Find your way |
"""


class NativeDesign(NativeFeatures):
    def start(self):
        self.window = self.app.ensure_window()
        self.window.present()
        self.window_paintable = Gtk.WidgetPaintable.new(self.window)
        self.window.set_theme("light")
        other = self.fixtures / "Welcome.md"
        other.write_text("# Welcome\n")
        self.window.open_path(str(other))
        self.fixture("design", SAMPLE, self.baseline)
        return GLib.SOURCE_REMOVE

    def baseline(self, doc):
        expression = """(()=>{const p=document.querySelector('.ProseMirror');
        return {html:p.innerHTML,styles:[...p.querySelectorAll('h1,h2,p,.label-wrapper,.list-item')].slice(0,18).map(e=>{
          const s=getComputedStyle(e),r=e.getBoundingClientRect();return {tag:e.tagName,cl:e.className,text:e.textContent.slice(0,40),top:r.top,height:r.height,font:s.fontSize,line:s.lineHeight,margin:s.margin,padding:s.padding,color:s.color};})};})()"""
        def got(data):
            (self.output / "layout.json").write_text(json.dumps(data, indent=2))
            self.window_snapshot("native-design.png", lambda: self.geometry(doc))
        self.evaluate(doc, expression, got)

    def geometry(self, doc):
        expression = """[...document.querySelectorAll('.milkdown-list-item-block>.list-item')].map(item=>{
          const marker=item.querySelector(':scope>.label-wrapper'),p=item.querySelector(':scope>.children>.content-dom>p');
          const a=marker.getBoundingClientRect(),b=p.getBoundingClientRect(),s=getComputedStyle(p),svg=marker.querySelector('svg');
          return {error:Math.abs(a.top+a.height/2-(b.top+parseFloat(s.lineHeight)/2)),color:svg?getComputedStyle(svg).fill:getComputedStyle(marker).color,textColor:s.color};})"""
        def checked(rows):
            self.require(len(rows)>=6, "Missing list fixtures")
            self.require(all(r["error"]<1 for r in rows), f"Markers do not align with first text lines: {rows}")
            self.require(all(r["color"]==r["textColor"] for r in rows), f"List markers have low contrast: {rows}")
            self.record("Bullet, checkbox, nested and two-digit markers align with first line", rows)
            self.selection_check(doc)
        self.evaluate(doc, expression, checked)

    def selection_check(self, doc):
        def changed(_):
            self.act(doc, self.select("Normal text should feel natural."), selected)
        def selected(_):
            def checked(value):
                self.require(value == "0", f"Style control stayed at {value!r} after cursor moved to normal text")
                self.record("Style selector follows current paragraph")
                self.normal_and_clear(doc)
            self.evaluate(doc, "document.querySelector('#text-style').dataset.value", checked)
        self.act(doc, self.select("A simple plan") + self.choose("Paragraph style", "2"), changed)

    def normal_and_clear(self, doc):
        def heading(_):
            self.act(doc, self.choose("Paragraph style", "0"), normal)
        def normal(state):
            self.require("**emphasis**" in state["markdown"], "Normal text erased inline formatting")
            self.require("# Normal text should" not in state["markdown"], "Normal text remained a heading")
            self.act(doc, self.select("emphasis"), mark_selected)
        def mark_selected(_):
            def checked(pressed):
                self.require(pressed == "true", "Bold state did not follow the text selection")
                self.act(doc, self.click("Clear formatting"), cleared)
            self.evaluate(doc, "document.querySelector('[aria-label=\"Bold (Ctrl+B)\"]').getAttribute('aria-pressed')", checked)
        def cleared(state):
            self.require("**emphasis**" not in state["markdown"] and "emphasis" in state["markdown"], "Clear formatting did not retain the words")
            self.record("Normal text preserves emphasis; Clear formatting removes only marks")
            self.fixture("typing", "## A heading\n", self.heading_enter)
        self.act(doc, self.select("Normal text should feel natural.") + self.choose("Paragraph style", "1"), heading)

    def key(self, key):
        return "document.querySelector('.ProseMirror').dispatchEvent(new KeyboardEvent('keydown',{key:" + json.dumps(key) + ",bubbles:true,cancelable:true}));"

    def heading_enter(self, doc):
        def at_end(_):
            self.act(doc, self.key("Enter"), entered)
        def entered(_):
            def checked(value):
                self.require(value=="0", f"Enter after heading did not return to Normal text: {value}")
                self.record("Enter after heading returns to Normal text")
                self.fixture("list-exit", "- **First item**\n- Second item\n", self.list_exit)
            self.evaluate(doc, "document.querySelector('#text-style').dataset.value", checked)
        self.act(doc, "window.reader.testSelectRange(10);", at_end)

    def list_exit(self, doc):
        def normal(state):
            self.require(state["markdown"].startswith("**First item**") and any(marker + " Second item" in state["markdown"] for marker in ("-", "*")), f"Normal text failed to exit list safely: {state['markdown']}")
            self.record("Normal text exits list and preserves sibling and inline formatting")
            self.act(doc, self.select("First item") + self.click("Bullet list"), listed)
        def listed(_):
            self.act(doc, self.click("Bullet list"), toggled)
        def toggled(state):
            self.require(state["markdown"].startswith("**First item**"), "Clicking active list button did not exit the list")
            self.record("List button toggles back to ordinary text")
            self.fixture("design-final", SAMPLE, self.capture_variants)
        self.act(doc, self.select("First item") + self.choose("Paragraph style", "0"), normal)

    def capture_variants(self, doc):
        # Only keep the two presentation tabs; other test buffers are disposable.
        for other in list(self.window.documents):
            if other is not doc and other.path.name != "Welcome.md":
                other.dirty = False
                other.editable = False
                self.window.tabs.close_page(other.page)
        self.window.status("")
        self.act(doc, self.select("Normal text should feel natural."), lambda _: self.capture(doc, "native-light.png", lambda: self.menu_snapshot(doc)))

    def capture(self, doc, name, then):
        # Wait for WebKit compositing as well as GTK's frame; the DOM changes first.
        self.delay(lambda: self.snapshot(doc, "web-" + name, lambda: self.delay(lambda: self.window_snapshot(name, then), 350)), 800)

    def menu_snapshot(self, doc):
        def checked(_):
            def visible(result):
                self.require(result["open"], f"Text style menu did not stay open: {result}")
                self.capture(doc, "native-style-menu.png", lambda: self.dark(doc))
            self.evaluate(doc, "({open:document.querySelector('#text-style').getAttribute('aria-expanded')==='true',focus:document.activeElement.outerHTML})", visible)
        self.act(doc, self.click("Text style"), checked)

    def dark(self, doc):
        self.act(doc, "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));", lambda _: None)
        self.window.set_theme("dark")
        self.capture(doc, "native-dark.png", lambda: self.narrow(doc))

    def narrow(self, doc):
        self.window.set_theme("light")
        self.window.set_default_size(620, 800)
        self.window.zoom_by(.4)
        self.window.status("")
        self.capture(doc, "native-narrow.png", lambda: self.narrow_checked(doc))

    def narrow_checked(self, doc):
        def checked(result):
            self.require(result["width"]<=700 and result["width"]>=result["scroll"], f"Narrow page overflows or did not resize: {result}")
            self.require(result["theme"]=="light" and abs(float(result["size"].removesuffix("px"))-23.8)<.01, f"Theme or zoom was not applied: {result}")
            self.record("Narrow native window at enlarged text stays within viewport")
            self.serialize(doc, lambda _: self.finish())
        self.evaluate(doc, "({width:innerWidth,scroll:document.documentElement.scrollWidth,theme:document.documentElement.dataset.theme,size:getComputedStyle(document.querySelector('.ProseMirror')).fontSize})", checked)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "work/native-design")
    args = parser.parse_args()
    raise SystemExit(NativeDesign(args.output).run())
