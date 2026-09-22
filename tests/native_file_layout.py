#!/usr/bin/env python3
"""Check annotated file trees in native WebKit.

Set MR_TEST_DOCUMENT to a README with an annotated file tree to check that file.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from native_smoke import ACTUAL_README, NativeSmoke, PROJECT, GLib, sha

SAMPLE = """## Layout

```
nsedata/            collector package (Python 3.11+, needs only `requests`)
  config.py         paths, hosts, politeness limits, retry policy
  eras.py           EVERY known format era, cutover date, header fingerprint, API limit
  http.py           archive downloader (2 hosts, retries) + cookie-managed API session
  store.py          sqlite ingest log: one row per (source, key), every attempt logged
  sources.py        one class per source: keys, URLs, fetch, validate
  collect.py        orchestration, index back-history walker, gap classification
  cli.py            command line
data/
  raw/<source>/<year>/...     collector-retained files; historical transformations need provenance
  quarantine/...              files whose header did not match the era registry
  ingest.sqlite               state + attempt log
  evidence/<run>/...          frozen copies, hashes, member inventory, ingestion-log exports
  audit/<run>/...             diagnostic profiles; not a standardized release
  logs/
.venv/              duckdb, polars, pyarrow, openpyxl (for the silver build; created with uv)
```
"""


class NativeFileLayout(NativeSmoke):
    def start(self):
        self.window = self.app.ensure_window()
        self.window.present()
        self.window.set_theme("light")
        self.window.set_default_size(1150, 850)
        self.target = ACTUAL_README if os.environ.get("MR_TEST_DOCUMENT") else self.fixtures / "file-layout.md"
        if self.target != ACTUAL_README:
            self.target.write_text(SAMPLE)
        self.target_hash = sha(self.target)
        self.doc = self.window.open_path(str(self.target))
        source = self.target.read_text()
        self.expected = re.search(r"## Layout\s+```\n(.*?)\n```", source, re.S).group(1)
        self.wait_for(lambda: self.doc.loaded, self.wide, "file tree document")
        return GLib.SOURCE_REMOVE

    def geometry(self, done):
        expression = """(()=>{const block=document.querySelector('.annotated-tree-block');
          if(!block)return null;const tree=block.querySelector('.annotated-tree');
          const rows=[...tree.querySelectorAll('.annotated-tree-row')];
          const clipped=[...tree.querySelectorAll('.annotated-tree-path,.annotated-tree-description')]
            .filter(el=>el.scrollWidth>el.clientWidth+1).map(el=>el.textContent);
          return {count:rows.length,first:rows[0]?.textContent,last:rows.at(-1)?.textContent,
            blockWidth:block.clientWidth,blockScroll:block.scrollWidth,treeWidth:tree.clientWidth,
            treeScroll:tree.scrollWidth,clipped,columns:getComputedStyle(rows[0]).gridTemplateColumns,
            descriptionInsets:rows.slice(0,3).map(row=>getComputedStyle(row.querySelector('.annotated-tree-description')).paddingLeft),
            text:tree.textContent,mode:window.reader.inspect().mode};})()"""
        self.evaluate(self.doc, expression, done)

    def check(self, result):
        self.require(result is not None, "The annotated file tree was not recognized")
        self.require(result["count"] == 16, f"Unexpected number of file-tree entries: {result}")
        self.require(result["mode"] == "read", "File tree was not shown in Read mode")
        self.require(result["blockScroll"] <= result["blockWidth"] + 1, f"Block still scrolls sideways: {result}")
        self.require(result["treeScroll"] <= result["treeWidth"] + 1 and not result["clipped"],
                     f"File tree text is clipped: {result}")
        self.require("header fingerprint, API limit" in result["text"], "Description was truncated")
        self.require("diagnostic profiles; not a standardized release" in result["text"], "Last description was truncated")

    def wide(self):
        self.geometry(self.wide_checked)

    def wide_checked(self, result):
        self.check(result)
        self.record("Annotated file tree fits normal window", result)
        self.evaluate(self.doc, "(document.querySelector('.annotated-tree-block').scrollIntoView(),true)",
                      lambda _: self.delay(lambda: self.snapshot(self.doc, "file-layout-wide.png", self.original), 300))

    def original(self):
        expression = """(()=>{const block=document.querySelector('.annotated-tree-block');
          block.querySelector('.code-actions button:first-child').click();
          return {original:block.querySelector('pre').textContent,
            visible:!block.querySelector('pre').hidden,layoutHidden:block.querySelector('.annotated-tree').hidden};})()"""
        self.evaluate(self.doc, expression, self.original_checked)

    def original_checked(self, result):
        self.require(result["original"].strip() == self.expected and result["visible"] and result["layoutHidden"],
                     "Original view did not preserve the exact source")
        self.record("Original control reveals unchanged code block")
        self.evaluate(self.doc, "(document.querySelector('.annotated-tree-block .code-actions button:first-child').click(),true)",
                      lambda _: self.narrow())

    def narrow(self):
        self.window.set_default_size(620, 850)
        self.delay(lambda: self.geometry(self.narrow_checked), 400)

    def narrow_checked(self, result):
        self.check(result)
        self.require(len(result["columns"].split()) == 1, f"Narrow rows did not stack: {result}")
        self.require(float(result["descriptionInsets"][1].removesuffix('px')) >
                     float(result["descriptionInsets"][0].removesuffix('px')),
                     "Nested descriptions did not follow file-tree indentation")
        self.record("Annotated file tree stacks without clipping in narrow window", result)
        self.snapshot(self.doc, "file-layout-narrow.png", self.finish)

    def finish(self):
        if hasattr(self, "target_hash"):
            unchanged = sha(self.target) == self.target_hash
            self.record("File layout source hash", "unchanged" if unchanged else "changed",
                        "passed" if unchanged else "failed")
            self.failed |= not unchanged
        super().finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT / "work/file-layout-check")
    args = parser.parse_args()
    raise SystemExit(NativeFileLayout(args.output).run())
