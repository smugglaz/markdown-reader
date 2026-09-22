#!/usr/bin/env python3
"""Native tab, welcome, appearance, width, and light/dark polish regression.

Only disposable files are edited. Screenshots come from the actual GTK/WebKit
window. Physical file-manager and screen-reader use still need human checks.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from native_smoke import NativeSmoke, PROJECT, GLib, Gtk, sha
import markdown_reader.app as shell


SAMPLE = """# A document with room to breathe

The same paragraph should stay visible when the reading width changes. This
sentence has a [useful link](https://example.com) and enough words to show the
difference between comfortable and wide page layouts.

> [!WARNING] Check before saving
> An agent might update the file while it is open.

> [!IMPORTANT] Keep your changes
> The document remains yours to review.

- [x] A completed task
- [ ] An incomplete task

| Capability | Reason | Status |
| --- | --- | --- |
| Wide layout | Technical documents need more room | Ready |

```python
# A useful explanation in a code comment.
print("A long technical line should remain available when the page grows")
```

## A later section

""" + ("More prose helps verify scrolling and reading position.\n\n" * 28)


class NativePolish(NativeSmoke):
    def start(self):
        self.window = self.app.ensure_window()
        self.window.present()
        self.window.set_default_size(1600, 900)
        self.window_paintable = Gtk.WidgetPaintable.new(self.window)
        self.require(not self.window.tab_bar.get_visible(), "Welcome shows an empty tab bar")
        for name in ("close-tab", "save", "save-as", "export", "find", "outline", "edit"):
            self.require(not self.app.lookup_action(name).get_enabled(), f"{name} is active on Welcome")
        self.record("Welcome hides tabs and disables document-only actions")
        self.path = self.fixtures / "polish source.md"
        self.path.write_text(SAMPLE)
        self.before = sha(self.path)
        self.doc = self.window.open_path(str(self.path))
        self.wait_for(lambda: self.doc.loaded, self.one_tab, "first document")
        return GLib.SOURCE_REMOVE

    def one_tab(self):
        self.require(self.window.tab_bar.get_visible(), "The final tab has no visible close control")
        self.require(self.app.lookup_action("close-tab").get_enabled(), "Close Document is unavailable")
        self.require(self.window.title_widget.get_title() == "Markdown Reader", "Filename is repeated in the header")
        self.require("polish source.md" in self.doc.page.get_title(), "Tab lost its document name")
        self.require(self.app.lookup_action("reading-width").get_state().get_string() == "comfortable", "Default width is not comfortable")
        self.record("Single document retains its tab and Close Document action")
        self.doc.request("prepareExport", self.guard(self.ready))

    def ready(self, message):
        self.doc.call("exportFinished")
        self.require(not message.get("issues"), f"Fixture did not finish rendering: {message.get('issues')}")
        self.evaluate(self.doc, """(()=>{const p=document.querySelector('#page');
          const code=document.querySelector('.hljs-comment');
          const warning=document.querySelector('.callout[data-callout=warning]');
          return {width:p.getBoundingClientRect().width,viewport:innerWidth,scroll:document.documentElement.scrollWidth,
            code:getComputedStyle(code).color,warning:getComputedStyle(warning).backgroundColor,
            title:getComputedStyle(warning.querySelector('.callout-label')).color,
            link:getComputedStyle(document.querySelector('a[href^=https]')).color};})()""", self.comfortable)

    def comfortable(self, result):
        self.comfortable_width = result["width"]
        self.require(result["scroll"] <= result["viewport"] + 2, "Comfortable page scrolls sideways")
        self.require(result["code"] == "rgb(95, 101, 112)", f"Light code palette missing: {result}")
        self.require(result["warning"] == "rgb(255, 247, 231)", f"Light warning surface missing: {result}")
        self.require(result["title"] == "rgb(133, 86, 0)", f"Light warning title missing: {result}")
        self.record("Light semantic palette", result)
        self.window_snapshot("native-comfortable-light.png", self.wide)

    def wide(self):
        self.app.lookup_action("reading-width").activate(GLib.Variant("s", "wide"))
        self.require(self.app.lookup_action("reading-width").get_state().get_string() == "wide", "Wide menu is not selected")
        self.delay(lambda: self.evaluate(self.doc,
            "({width:document.querySelector('#page').getBoundingClientRect().width,viewport:innerWidth,scroll:document.documentElement.scrollWidth,mode:document.documentElement.dataset.width})",
            self.wide_checked), 180)

    def wide_checked(self, result):
        self.require(result["mode"] == "wide", "WebKit did not receive Wide mode")
        self.require(result["width"] > self.comfortable_width + 150, f"Wide mode is not meaningfully wider: {result}")
        self.require(result["scroll"] <= result["viewport"] + 2, "Wide page scrolls sideways")
        self.require(self.app.store.load_session()["width"] == "wide", "Width was not persisted")
        self.record("Wide reading width and persisted choice", result)
        self.window_snapshot("native-wide-light.png", self.dark)

    def dark(self):
        self.app.lookup_action("theme").activate(GLib.Variant("s", "dark"))
        self.require(self.app.lookup_action("theme").get_state().get_string() == "dark", "Dark menu is not selected")
        self.delay(lambda: self.evaluate(self.doc,
            "({theme:document.documentElement.dataset.theme,comment:getComputedStyle(document.querySelector('.hljs-comment')).color,warning:getComputedStyle(document.querySelector('.callout[data-callout=warning]')).backgroundColor})",
            self.dark_checked), 180)

    def dark_checked(self, result):
        self.require(result == {"theme": "dark", "comment": "rgb(175, 182, 194)",
                                "warning": "rgb(58, 48, 34)"}, f"Dark palette regressed: {result}")
        self.record("Dark semantic palette and selected theme", result)
        self.window_snapshot("native-wide-dark.png", self.narrow)

    def narrow(self):
        self.app.lookup_action("theme").activate(GLib.Variant("s", "light"))
        self.window.set_default_size(620, 820)
        self.window.zoom_by(1.0)
        label = self.window.menu.get_item_attribute_value(self.window.zoom_menu_index, "label", None).get_string()
        self.require("200%" in label, f"Text Size menu did not show current value: {label}")
        self.delay(lambda: self.evaluate(self.doc,
            """(()=>{const page=document.querySelector('#page'),h=document.querySelector('h1'),p=document.querySelector('p');
              const rect=x=>({left:x.getBoundingClientRect().left,right:x.getBoundingClientRect().right,width:x.getBoundingClientRect().width,scroll:x.scrollWidth,client:x.clientWidth,white:getComputedStyle(x).whiteSpace});
              return {viewport:innerWidth,scroll:document.documentElement.scrollWidth,width:page.getBoundingClientRect().width,mode:document.documentElement.dataset.width,page:rect(page),heading:rect(h),paragraph:rect(p)};})()""",
            self.narrow_checked), 260)

    def narrow_checked(self, result):
        self.require(result["viewport"] <= 700 and result["scroll"] <= result["viewport"] + 2,
                     f"Wide mode at 200% overflows a narrow window: {result}")
        self.require(result["mode"] == "wide", "Narrow window silently changed width preference")
        self.record("Wide at narrow window and 200% text remains contained", result)
        self.snapshot(self.doc, "webkit-wide-narrow.png",
                      lambda: self.window_snapshot("native-wide-narrow.png", self.edit))

    def edit(self):
        self.window.set_default_size(1600, 900)
        self.window.zoom_by(0, reset=True)
        self.window.mode_changed("edit")
        self.wait_mode(self.doc, "edit", self.edit_checked)

    def edit_checked(self):
        self.evaluate(self.doc,
            "({width:document.querySelector('#page').getBoundingClientRect().width,mode:document.documentElement.dataset.width,scroll:document.documentElement.scrollWidth,viewport:innerWidth})",
            self.edit_measured)

    def edit_measured(self, result):
        self.require(result["mode"] == "wide" and result["width"] > self.comfortable_width + 150,
                     f"Edit mode lost Wide layout: {result}")
        self.require(result["scroll"] <= result["viewport"] + 2, "Wide Edit scrolls sideways")
        self.record("Read and Edit share Wide layout", result)
        self.window.show_find()
        self.window.search.set_text("later section")
        self.require(self.window.searchbar.get_search_mode(), "Find did not open")
        self.wait_for(lambda: self.window.search_results.get_text() == "1 match",
                      self.find_counted, "Find results")

    def find_counted(self):
        self.require(self.window.search_results.get_text() == "1 match", "Find did not show the match count")
        self.window.search.set_text("notpresenttoken")
        self.wait_for(lambda: self.window.search_results.get_text() == "No matches",
                      self.find_empty, "Find no-match result")

    def find_empty(self):
        self.record("Find shows a match count and a clear no-match state")
        other = self.fixtures / "another document.md"
        other.write_text("# Another document\n\nNo stale query belongs here.\n")
        self.other = self.window.open_path(str(other))
        self.wait_for(lambda: self.other.loaded, self.switched, "second document")

    def switched(self):
        self.require(not self.window.searchbar.get_search_mode() and not self.window.search.get_text(),
                     "Find carried a stale query into another document")
        self.require(self.window.tab_bar.get_visible() and len(self.window.documents) == 2,
                     "Opening a second document hid the tabs")
        self.record("Switching documents dismisses the previous Find query")
        self.window.close_current()
        self.wait_for(lambda: len(self.window.documents) == 1, self.one_remaining, "second tab close")

    def one_remaining(self):
        self.require(self.window.tab_bar.get_visible(), "One remaining tab lost its close control")
        self.record("Two tabs become one without hiding the last tab")
        self.window.close_current()
        self.wait_for(lambda: not self.window.documents, self.welcome, "last tab close")

    def welcome(self):
        self.require(not self.window.tab_bar.get_visible(), "Welcome retained the tab strip")
        self.require(self.window.stack.get_visible_child_name() == "welcome", "Last tab close quit instead of showing Welcome")
        self.require(not self.window.searchbar.get_search_mode(), "Find remained over Welcome")
        self.require(self.window.status_toast is None, "A stale document toast remained on Welcome")
        labels = []
        child = self.window.recent_list.get_first_child()
        while child:
            labels.append(child.get_label())
            child = child.get_next_sibling()
        self.require(any("another document.md" in label for label in labels), f"Recent files stayed stale: {labels}")
        for name in ("close-tab", "save", "save-as", "export", "find", "outline", "edit"):
            self.require(not self.app.lookup_action(name).get_enabled(), f"{name} stayed active on Welcome")
        self.require(sha(self.path) == self.before, "Layout, theme, or closing changed the document")
        self.record("Final tab returns to Welcome with current recents and safe controls", labels)
        self.delay(lambda: self.window_snapshot("native-welcome-after-close.png", self.dirty), 350)

    def dirty(self):
        self.doc = self.window.open_path(str(self.path))
        self.wait_for(lambda: self.doc.loaded, lambda: (self.window.mode_changed("edit"),
                      self.wait_mode(self.doc, "edit", self.make_dirty)), "reopened document")

    def make_dirty(self):
        self.doc.call("testInsertText", " Local unsaved change.")
        self.wait_for(lambda: self.doc.dirty, self.cancel_close, "dirty document")

    def cancel_close(self):
        self.require(self.doc.page.get_title().startswith("● "), "Dirty tab has no visible marker")
        self.require("Unsaved changes" in self.doc.page.get_tooltip(), "Dirty tab has no descriptive tooltip")
        self.require(self.window.save_button.get_visible(), "Save action is hidden for unsaved edits")
        self.record("Dirty final tab retains visible and descriptive status")
        self.original_alert = shell.alert
        self.choices = [0, 2]
        def choose(parent, title, detail, buttons, callback, default=0, cancel=0):
            if title.startswith("Save changes to "):
                callback(self.choices.pop(0))
            else:
                self.original_alert(parent, title, detail, buttons, callback, default, cancel)
        shell.alert = choose
        self.window.close_current()
        self.delay(self.cancel_checked, 200)

    def cancel_checked(self):
        self.require(self.doc in self.window.documents and self.doc.dirty,
                     "Cancel discarded or closed the unsaved document")
        self.require(sha(self.path) == self.before, "Cancel wrote the original file")
        self.record("Cancel keeps dirty last tab open and source unchanged")
        self.window.close_current()
        self.wait_for(lambda: not self.window.documents, self.discard_checked, "discarded dirty tab")

    def discard_checked(self):
        shell.alert = self.original_alert
        self.require(sha(self.path) == self.before, "Discard wrote the original file")
        self.require(self.window.stack.get_visible_child_name() == "welcome", "Discard did not return to Welcome")
        self.record("Discard closes dirty last tab without writing the source")
        self.save_case = self.fixtures / "save on close.md"
        self.save_case.write_text("# Save on close\n\nOriginal text.\n")
        self.save_before = sha(self.save_case)
        self.doc = self.window.open_path(str(self.save_case))
        self.wait_for(lambda: self.doc.loaded, lambda: (self.window.mode_changed("edit"),
                      self.wait_mode(self.doc, "edit", self.prepare_save_close)), "save-close fixture")

    def prepare_save_close(self):
        self.doc.call("testInsertText", " Saved through Close.")
        self.wait_for(lambda: self.doc.dirty, self.save_close, "dirty save-close fixture")

    def save_close(self):
        def choose(parent, title, detail, buttons, callback, default=0, cancel=0):
            if title.startswith("Save changes to "):
                callback(1)
            else:
                self.original_alert(parent, title, detail, buttons, callback, default, cancel)
        shell.alert = choose
        self.window.close_current()
        self.wait_for(lambda: not self.window.documents, self.save_close_checked, "saved final tab")

    def save_close_checked(self):
        shell.alert = self.original_alert
        self.require(sha(self.save_case) != self.save_before, "Save on close left the source unchanged")
        self.require("Saved through Close." in self.save_case.read_text(), "Save on close lost the edit")
        self.require(self.window.stack.get_visible_child_name() == "welcome", "Save on close did not return to Welcome")
        self.record("Save on dirty final tab writes the edit and returns to Welcome")
        self.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "work/native-polish")
    args = parser.parse_args()
    raise SystemExit(NativePolish(args.output).run())
