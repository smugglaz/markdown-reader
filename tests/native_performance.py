#!/usr/bin/env python3
"""Repeatable native timings; disposable files and state, no network assets.

Opening includes WebKit startup, parsing, layout and a paint checkpoint. Typing
uses actual editor transactions and their normal asynchronous listeners rather
than the smoke helper's forced serialization. Event-loop delay includes delayed
work after typing. Run with --enforce to assert the interactive latency budget.
"""
import argparse
import json
import time
from pathlib import Path

from native_smoke import NativeSmoke, PROJECT, GLib, WebKit, sha


def document(size):
    block = "## A useful section\n\nA readable paragraph with **important words**, a [reference](https://example.com), and `inline code`. This is a representative agent document with enough detail to occupy a few lines.\n\n- Keep the original document safe.\n- Make writing feel immediate.\n\n"
    return "# A responsive reader\n\n" + block * max(1, size // len(block))


class NativePerformance(NativeSmoke):
    def __init__(self, output, enforce, sizes=None, wait_active=False):
        super().__init__(output)
        self.enforce = enforce
        self.wait_active = wait_active
        self.timings = []
        available = {"small": 5_000, "ordinary": 100_000, "large": 500_000}
        self.cases = [(name, available[name]) for name in (sizes or available)]
        self.tab_peer = None

    def timing(self, name, ms, budget):
        data = {"name": name, "milliseconds": round(ms, 2), "budget_ms": budget, "within_budget": ms <= budget,"foreground":self.window.is_active()}
        self.timings.append(data)
        self.record(name, data, "passed" if data["within_budget"] else "slow")

    def start(self):
        self.window = self.app.ensure_window()
        self.window.present()
        self.window.set_theme("light")
        if self.wait_active:
            self.window.status("Performance check — keep this window in front")
            self.delay(lambda:self.poll(lambda:self.window.is_active(),self.next_case,"foreground test window"),3000)
        else:
            self.next_case()
        return GLib.SOURCE_REMOVE

    def poll(self, condition, then, label):
        deadline=time.monotonic()+90
        @self.guard
        def tick():
            if condition():
                then();return GLib.SOURCE_REMOVE
            if time.monotonic()>deadline:
                return self.fail("Timed out: "+label)
            return GLib.SOURCE_CONTINUE
        GLib.timeout_add(10,tick)

    def next_case(self):
        if not self.cases:
            return self.finish_performance()
        self.case, size = self.cases.pop(0)
        path = self.fixtures / (self.case+".md")
        path.write_text(document(size))
        self.started = time.monotonic()
        self.doc = self.window.open_path(str(path))
        self.poll(lambda:self.doc.loaded,self.painted,"document load")

    def painted(self):
        doc=self.doc
        # A native WebKit snapshot completes after the document's current layout.
        def captured(web, result, _data):
            web.get_snapshot_finish(result)
            self.timing(self.case+" open to paint",(time.monotonic()-self.started)*1000,1000 if self.case=='small' else 2000)
            self.require(doc.editable,"Document unexpectedly lost visual editing")
            self.evaluate(doc, "window.reader.performanceReport?.() ?? null", self.load_report)

        doc.web.get_snapshot(WebKit.SnapshotRegion.VISIBLE,WebKit.SnapshotOptions.NONE,None,self.guard(captured),None)

    def load_report(self, report):
        if report is not None:
            self.record(self.case + " frontend load stages", report, "diagnostic")
        self.started=time.monotonic()
        self.window.mode_changed("edit")
        self.wait_editor(self.start_typing_measurement)

    def wait_editor(self, then):
        deadline = time.monotonic() + 90
        doc = self.doc
        def inspected(state):
            if state['mode'] == 'edit' and not state['busy']:
                self.require(doc.mode == 'edit' and not doc.mode_busy, "Native editor controls did not reach Edit")
                then()
                return
            self.require(state['editable'], "Editor preparation rejected the document")
            self.require(time.monotonic() < deadline, "Editor preparation did not finish")
            self.delay(check, 10)
        def check():
            self.evaluate(doc, "(()=>{const s=window.reader.inspect();return {mode:s.mode,busy:!!s.busy,editable:s.editable};})()", inspected)
        check()

    def start_typing_measurement(self):
        self.timing(self.case+" enter Edit",(time.monotonic()-self.started)*1000,100)
        self.evaluate(self.doc,"(()=>{window.__perf={gaps:[],keys:[],last:performance.now()};window.__perf.timer=setInterval(()=>{const now=performance.now();window.__perf.gaps.push(Math.max(0,now-window.__perf.last-16));window.__perf.last=now;},16);return true;})()",lambda _:self.type_start())

    def type_start(self):
        expression="""(()=>{let i=0;window.__perf.finished=false;const type=()=>{const start=performance.now();window.reader.testInsertText('x',false);window.__perf.keys.push(performance.now()-start);if(++i<20)setTimeout(type,65);else setTimeout(()=>{window.__perf.finished=true;clearInterval(window.__perf.timer);},600);};type();return true;})()"""
        self.evaluate(self.doc,expression,lambda _:self.typing_done())

    def typing_done(self):
        def read(result):
            if not result["finished"]:
                self.delay(self.typing_done,150);return
            self.record(self.case+' editing stages',result.get('stages'), 'diagnostic')
            keys=sorted(result['keys']);gaps=sorted(result['gaps'])
            self.timing(self.case+" key transaction p95",keys[int(.95*(len(keys)-1))],16)
            self.timing(self.case+" event-loop delay p95",gaps[int(.95*(len(gaps)-1))],50)
            self.timing(self.case+" worst event-loop stall",max(gaps),100)
            # Flush via native request before measuring disk refresh. No saved original is edited.
            self.doc.request("serialize",self.guard(self.serialized))
        self.evaluate(self.doc,"({finished:window.__perf.finished,keys:window.__perf.keys,gaps:window.__perf.gaps,stages:window.reader.performanceReport?.()})",read)

    def serialized(self,message):
        self.require(message.get('ok',True),str(message.get('error')))
        self.doc.call('markSaved',message['markdown'])
        self.doc.dirty=False
        self.window.mode_changed('read')
        self.delay(self.refresh,200)

    def refresh(self):
        self.started=time.monotonic()
        self.refresh_revision=self.doc.revision
        self.refresh_marker = "Fresh agent update " + self.case + " " + str(time.time_ns())
        self.doc.path.write_text(self.doc.path.read_text()+"\n"+self.refresh_marker+"\n")
        self.poll(lambda:self.doc.loaded and self.doc.revision>self.refresh_revision,self.refresh_rendered,'refresh')

    def refresh_rendered(self):
        # A native revision increments before the asynchronous editor load. Also
        # require the new text in the DOM, completed fonts and a paint checkpoint.
        expression = "({ready:document.fonts.status==='loaded' && !document.querySelector('[aria-busy=\"true\"]'),contains:document.querySelector('#page')?.textContent.includes(" + json.dumps(self.refresh_marker) + ")})"
        def inspected(result):
            if not result['ready'] or not result['contains']:
                self.require(time.monotonic()-self.started < 90, "Refreshed document did not finish rendering")
                self.delay(self.refresh_rendered, 25)
                return
            self.paint_checkpoint(self.doc, self.refreshed)
        self.evaluate(self.doc, expression, inspected)

    def paint_checkpoint(self, doc, done):
        def captured(web, result, _data):
            web.get_snapshot_finish(result)
            done()
        doc.web.get_snapshot(WebKit.SnapshotRegion.VISIBLE, WebKit.SnapshotOptions.NONE,
                             None, self.guard(captured), None)

    def refreshed(self):
        self.timing(self.case+" agent refresh",(time.monotonic()-self.started)*1000,550 if self.case!='large' else 1500)
        self.source_hash = sha(self.doc.path)
        if self.tab_peer is None:
            path = self.fixtures / "tab-peer.md"
            path.write_text("# Another open document\n\nSwitch tabs without losing your place.\n")
            self.tab_peer = self.window.open_path(str(path))
            self.poll(lambda:self.tab_peer.loaded, self.prepare_tab_switches, 'tab peer load')
        else:
            self.prepare_tab_switches()

    def prepare_tab_switches(self):
        # Companion setup is outside the switch budget. Both target views are
        # already fully loaded before any measured switch begins.
        self.window.tabs.set_selected_page(self.doc.page)
        self.paint_checkpoint(self.doc, lambda:self.switch_tab(self.tab_peer, "idle switch away", self.idle_back))

    def switch_tab(self, target, label, done):
        started = time.monotonic()
        self.window.tabs.set_selected_page(target.page)
        def mapped():
            self.require(self.window.current is target, "Selected native tab is incorrect")
            # Wait for the mapped native view's frame before taking the visible
            # WebKit snapshot, so this includes selection, allocation and paint.
            def frame(_widget, _clock):
                self.paint_checkpoint(target, painted)
                return GLib.SOURCE_REMOVE
            target.web.add_tick_callback(self.guard(frame))
        def painted():
            self.require(self.window.current is target, "Tab changed during its paint checkpoint")
            self.timing(self.case + " " + label + " to paint", (time.monotonic()-started)*1000, 100)
            done()
        self.poll(lambda:target.web.get_mapped() and self.window.current is target, mapped, label)

    def idle_back(self):
        self.switch_tab(self.doc, "idle switch back", self.start_tab_typing)

    def start_tab_typing(self):
        self.tab_marker = "TABEDIT" + self.case + str(time.time_ns())
        self.window.mode_changed('edit')
        self.wait_editor(self.type_across_tabs)

    def type_across_tabs(self):
        expression = """(()=>{window.__tabPerf={count:0,finished:false};const type=()=>{window.reader.testInsertText(window.__tabPerf.count===0 ? %s : 'z',false);if(++window.__tabPerf.count<10)setTimeout(type,65);else setTimeout(()=>{window.__tabPerf.finished=true;},200);};type();return true;})()""" % json.dumps(self.tab_marker)
        self.evaluate(self.doc, expression, lambda _:self.delay(self.typing_switch, 80))

    def typing_switch(self):
        self.switch_tab(self.tab_peer, "typing switch away", lambda:self.switch_tab(self.doc, "typing switch back", self.tab_typing_done))

    def tab_typing_done(self):
        def inspected(result):
            if not result['finished']:
                self.delay(self.tab_typing_done, 50)
                return
            self.require(result['count'] == 10, "Scheduled typing did not complete across tab switches")
            self.doc.request('serialize', self.guard(self.tab_serialized))
        self.evaluate(self.doc, "({finished:window.__tabPerf.finished,count:window.__tabPerf.count})", inspected)

    def tab_serialized(self, message):
        self.require(message.get('ok',True), str(message.get('error')))
        self.require(self.window.current is self.doc, "Typing returned to the wrong native tab")
        self.require(message.get('dirty') and self.doc.dirty, "Tab switching lost the unsaved marker")
        self.require(self.tab_marker + 'z'*9 in message['markdown'], "Tab switching lost or reordered typed text")
        self.require(self.refresh_marker in message['markdown'], "Tab switching replaced the loaded document")
        self.require(sha(self.doc.path) == self.source_hash, "Tab switching or typing wrote the original file")
        self.record(self.case + " tab selection and unsaved buffer retained", "Native selection, serialized text, dirty status and original hash verified")
        self.next_case()

    def finish_performance(self):
        (self.output/'performance.json').write_text(json.dumps({'measurements':self.timings},indent=2))
        if self.enforce:
            self.require(all(t['foreground'] for t in self.timings),'Background paint timings are not a foreground performance check')
            self.require(all(t['within_budget'] for t in self.timings),'Interaction latency budget exceeded; see performance.json')
        self.finish()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=PROJECT/'work/performance/native')
    parser.add_argument('--enforce',action='store_true')
    parser.add_argument('--wait-active',action='store_true',help='Wait for the native test window to have focus before measuring')
    parser.add_argument('--sizes', default='small,ordinary,large',
                        help='Comma-separated cases: small,ordinary,large (default: all)')
    args=parser.parse_args()
    sizes = [name.strip() for name in args.sizes.split(',')]
    if not sizes or any(name not in {'small', 'ordinary', 'large'} for name in sizes):
        parser.error('--sizes must list small, ordinary, and/or large')
    if len(sizes) != len(set(sizes)):
        parser.error('--sizes must not repeat a case')
    raise SystemExit(NativePerformance(args.output,args.enforce,sizes,args.wait_active).run())
