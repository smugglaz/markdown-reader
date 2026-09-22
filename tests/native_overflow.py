#!/usr/bin/env python3
"""Check real WebKit table/code scrolling and resized table controls."""
import argparse
from pathlib import Path

from native_features import NativeFeatures, PROJECT, GLib


class NativeOverflow(NativeFeatures):
    def start(self):
        self.window = self.app.ensure_window()
        self.window.set_default_size(620, 800)
        self.window.present()
        self.window.set_theme("light")
        header = "| " + " | ".join(f"Column {i}" for i in range(1, 11)) + " |\n"
        rule = "| " + " | ".join("---" for _ in range(10)) + " |\n"
        row = "| " + " | ".join(f"value{i:02d}" for i in range(1, 11)) + " |\n"
        source = "# Wide content\n\n" + header + rule + row + "\n```text\n" + "long-code-" * 90 + "\n```\n"
        self.fixture("overflow", source, self.check_scrolling)
        return GLib.SOURCE_REMOVE

    def check_scrolling(self, doc):
        expression = """(()=>{
          // A passing result must come from component containment, not a page clip.
          document.body.style.overflowX='visible';
          const table=document.querySelector('.milkdown-table-block'),code=document.querySelector('.code-block>pre');
          const handle=table.querySelector('[data-role=x-line-drag-handle]');
          handle.style.width='1800px';handle.dataset.show='false';
          table.scrollLeft=100;code.scrollLeft=100;
          return {width:innerWidth,page:document.documentElement.scrollWidth,
            table:{width:table.clientWidth,scroll:table.scrollWidth,left:table.scrollLeft},
            code:{width:code.clientWidth,scroll:code.scrollWidth,left:code.scrollLeft},
            hidden:getComputedStyle(handle).display};})()"""
        def checked(result):
            self.require(result["page"] <= result["width"], f"Inactive table control widened page: {result}")
            self.require(result["hidden"] == "none", f"Inactive table control still occupies layout: {result}")
            for name in ("table", "code"):
                self.require(result[name]["scroll"] > result[name]["width"] and result[name]["left"] > 0, f"Wide {name} cannot scroll internally: {result}")
            self.record("Wide table and code scroll internally without clipping the page", result)
            self.evaluate(doc, "(()=>{const table=document.querySelector('.milkdown-table-block'),handle=table.querySelector('[data-role=x-line-drag-handle]');handle.dataset.show='true';return {width:innerWidth,page:document.documentElement.scrollWidth,offsetParent:handle.offsetParent.className};})()", active)
        def active(result):
            self.require(result["page"] <= result["width"] and "milkdown-table-block" in result["offsetParent"], f"Active table control escaped its scroll container: {result}")
            self.record("Active table controls stay inside the table scroll region", result)
            self.act(doc, self.select("value01") + self.choose("Insert", "row"), added)
        def added(_state):
            self.evaluate(doc, "document.querySelector('table.children').rows.length", rows)
        def rows(count):
            self.require(count == 3, f"Table toolbar did not add a row: {count}")
            self.record("Table toolbar remains usable with contained controls")
            self.serialize(doc, lambda _: self.read_scrolling(doc))
        self.evaluate(doc, expression, checked)

    def read_scrolling(self, doc):
        self.window.mode_changed("read")
        expression = """(()=>{
          document.body.style.overflowX='visible';
          const table=document.querySelector('.reading-table'),code=document.querySelector('.code-block>pre');
          table.scrollLeft=100;code.scrollLeft=100;
          return {width:innerWidth,page:document.documentElement.scrollWidth,
            table:{width:table.clientWidth,scroll:table.scrollWidth,left:table.scrollLeft},
            code:{width:code.clientWidth,scroll:code.scrollWidth,left:code.scrollLeft}};})()"""
        def checked(result):
            self.require(result["page"] <= result["width"], f"Reading content widened the page: {result}")
            for name in ("table", "code"):
                self.require(result[name]["scroll"] > result[name]["width"] and result[name]["left"] > 0,
                             f"Wide reading {name} cannot scroll internally: {result}")
            self.record("Reading table and code scroll inside their own containers", result)
            self.finish()
        self.wait_mode(doc, "read", lambda: self.evaluate(doc, expression, checked))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "work/native-overflow")
    args = parser.parse_args()
    raise SystemExit(NativeOverflow(args.output).run())
