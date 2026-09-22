"""Native desktop shell. The document frontend has no filesystem privileges."""
from __future__ import annotations

import difflib
import json
import mimetypes
import os
from pathlib import Path
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, unquote

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
gi.require_version("Soup", "3.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Soup, WebKit

from .storage import (
    ConflictError, ReadOnlyError, StateStore, read_document, save_document,
    save_copy, resolve_local_reference,
)
from .pdf_export import export_pdf

APP_ID = "local.markdownreader.Reader"
ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "dist"
POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="markdown-reader")


def later(fn, *args):
    def call():
        fn(*args)
        return GLib.SOURCE_REMOVE
    GLib.idle_add(call)


def job(fn, done):
    future = POOL.submit(fn)
    def complete(f):
        try:
            value, error = f.result(), None
        except Exception as exc:
            value, error = None, exc
        later(done, value, error)
    future.add_done_callback(complete)


def alert(parent, title, detail, buttons, callback, default=0, cancel=0):
    dialog = Gtk.AlertDialog(message=title, detail=detail, buttons=buttons,
                             default_button=default, cancel_button=cancel)
    def chosen(d, result):
        try:
            callback(d.choose_finish(result))
        except GLib.Error:
            callback(cancel)
    dialog.choose(parent, None, chosen)


class ReaderApplication(Adw.Application):
    def __init__(self, *, application_id=APP_ID, state_dir=None, restore=True):
        super().__init__(application_id=application_id, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.store = StateStore(base_dir=state_dir)
        self.restore = restore
        self.window = None
        self.resources = {}
        self.web_context = WebKit.WebContext.new()
        self.web_context.register_uri_scheme("reader", self._resource)
        security = self.web_context.get_security_manager()
        security.register_uri_scheme_as_secure("reader")
        security.register_uri_scheme_as_local("reader")
        security.register_uri_scheme_as_cors_enabled("reader")
        self.network_session = WebKit.NetworkSession.new_ephemeral()
        self.connect("shutdown", lambda *_: self.window.persist() if self.window else None)

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_data(b".reader-banner {padding:8px 14px;background:alpha(@warning_color,.12);} .reader-mode {border-radius:8px;} .reader-mode button {min-height:28px;padding:0 13px;font-size:13px;} .reader-mode button:checked {background:@accent_bg_color;color:@accent_fg_color;} .reader-tabs tab {min-width:120px;} .reader-title {font-weight:600;}")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        actions = {
            "open": (lambda: self.window.choose_open(), ["<Control>o"]),
            "new": (lambda: self.window.new_document(), ["<Control>n"]),
            "save": (lambda: self.window.save_current(), ["<Control>s"]),
            "save-as": (lambda: self.window.save_as(), ["<Control><Shift>s"]),
            "export": (lambda: self.window.export_current(), ["<Control><Shift>e"]),
            "find": (lambda: self.window.show_find(), ["<Control>f"]),
            "edit": (lambda: self.window.toggle_edit(), ["<Control>e"]),
            "close-tab": (lambda: self.window.close_current(), ["<Control>w"]),
            "zoom-in": (lambda: self.window.zoom_by(.1), ["<Control>plus", "<Control>equal"]),
            "zoom-out": (lambda: self.window.zoom_by(-.1), ["<Control>minus"]),
            "zoom-reset": (lambda: self.window.zoom_by(0, reset=True), ["<Control>0"]),
            "outline": (lambda: self.window.toggle_outline(), ["<Control><Shift>o"]),
            "about": (lambda: self.window.about(), []),
            "quit": (lambda: self.window.close(), ["<Control>q"]),
        }
        for name, (callback, accelerators) in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda a, p, cb=callback: cb())
            self.add_action(action)
            self.set_accels_for_action("app." + name, accelerators)
        for name, initial, callback in (("theme", "system", "set_theme"),
                                        ("reading-width", "comfortable", "set_width_mode")):
            action = Gio.SimpleAction.new_stateful(name, GLib.VariantType.new("s"), GLib.Variant("s", initial))
            action.connect("change-state", lambda a, value, method=callback:
                           getattr(self.ensure_window(), method)(value.get_string()))
            self.add_action(action)

    def ensure_window(self):
        if not self.window:
            self.window = ReaderWindow(self)
            if self.restore:
                self.window.restore_session()
        return self.window

    def do_activate(self):
        self.ensure_window().present()

    def do_open(self, files, n_files, hint):
        window = self.ensure_window()
        for file in files:
            window.open_path(file.get_path() or file.get_uri())
        window.present()

    def _resource(self, request):
        uri = urlsplit(request.get_uri())
        if os.environ.get("MR_DEBUG"):
            print("Resource:", request.get_uri(), flush=True)
        try:
            if uri.netloc == "app":
                relative = unquote(uri.path).lstrip("/") or "index.html"
                path = (FRONTEND / relative).resolve()
                if not path.is_relative_to(FRONTEND.resolve()):
                    raise PermissionError("Invalid application resource")
                data = path.read_bytes()
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                if path.suffix in (".js", ".mjs"):
                    mime = "text/javascript"
            elif uri.netloc == "asset":
                token = uri.path.lstrip("/")
                path = self.resources[token][1]
                mime = mimetypes.guess_type(path.name)[0] or ""
                if not mime.startswith("image/"):
                    raise PermissionError("Only image resources can be displayed")
                if path.stat().st_size > 40 * 1024 * 1024:
                    raise ValueError("Image exceeds 40 MB")
                data = path.read_bytes()
            else:
                raise FileNotFoundError("Unknown resource")
            stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
            response = WebKit.URISchemeResponse.new(stream, len(data))
            response.set_content_type(mime)
            response.set_status(200, "OK")
            headers = Soup.MessageHeaders.new(Soup.MessageHeadersType.RESPONSE)
            headers.append("Access-Control-Allow-Origin", "*")
            headers.append("Cache-Control", "no-cache")
            response.set_http_headers(headers)
            request.finish_with_response(response)
        except Exception as exc:
            if os.environ.get("MR_DEBUG"):
                print("Resource failed:", request.get_uri(), exc, flush=True)
            request.finish_error(GLib.Error.new_literal(Gio.io_error_quark(), str(exc), Gio.IOErrorEnum.NOT_FOUND))

    def register_asset(self, doc, source):
        resolved = resolve_local_reference(doc.path or Path.cwd() / "Untitled.md", source)
        if not resolved:
            raise ValueError("Invalid local image")
        path, _fragment = resolved
        mime = mimetypes.guess_type(str(path))[0] or ""
        if not mime.startswith("image/") or not path.is_file():
            raise ValueError("Local image is unavailable")
        token = uuid.uuid4().hex
        self.resources[token] = (doc.id, path)
        doc.watch_asset(path)
        return "reader://asset/" + token


class Document:
    def __init__(self, window, path=None):
        self.window = window
        self.app = window.app
        self.id = uuid.uuid4().hex
        self.path = Path(path).absolute() if path else None
        self.snapshot = None
        self.text = ""
        self.dirty = False
        self.conflict = False
        self.mode = "read"
        self.requested_mode = "read"
        self.mode_busy = False
        self.reload_deferred = False
        self.editable = True
        self.edit_reason = None
        self.revision = 0
        self.read_generation = 0
        self.edit_serial = 0
        self.ready = False
        self.loaded = False
        self.closed = False
        self.saving = False
        self.monitors = {}
        self.watched_assets = set()
        self.reload_timer = 0
        self.draft_timer = 0
        self.retry_count = 0
        self.pending = {}
        self.issues = []
        self.anchor = None
        self.recovery = None
        self.fragment = None
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.banner = Gtk.Box(spacing=8, css_classes=["reader-banner"])
        self.banner_label = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self.banner.append(self.banner_label)
        self.retry_button = Gtk.Button(label="Retry")
        self.retry_button.connect("clicked", lambda *_: self.reload())
        self.banner.append(self.retry_button)
        self.compare_button = Gtk.Button(label="Compare")
        self.compare_button.connect("clicked", lambda *_: self.window.compare(self))
        self.banner.append(self.compare_button)
        self.reload_button = Gtk.Button(label="Reload from Disk")
        self.reload_button.connect("clicked", lambda *_: self.discard_reload())
        self.banner.append(self.reload_button)
        self.copy_button = Gtk.Button(label="Save a Copy")
        self.copy_button.connect("clicked", lambda *_: self.window.save_as(self))
        self.banner.append(self.copy_button)
        self.banner.set_visible(False)
        self.box.append(self.banner)
        manager = WebKit.UserContentManager.new()
        manager.register_script_message_handler("reader", None)
        manager.connect("script-message-received::reader", self._message)
        settings = WebKit.Settings.new()
        settings.set_enable_javascript(True)
        # The trusted app page loads the bundled editor via a module script.
        # Document HTML is sanitized; CSP permits scripts only from app resources.
        settings.set_enable_javascript_markup(True)
        settings.set_enable_media(False)
        settings.set_enable_html5_local_storage(False)
        settings.set_enable_write_console_messages_to_stdout(bool(os.environ.get("MR_DEBUG")))
        self.web = WebKit.WebView(web_context=self.app.web_context,
                                 network_session=self.app.network_session,
                                 user_content_manager=manager, settings=settings)
        find_controller = self.web.get_find_controller()
        find_controller.connect("found-text", lambda _controller, count: self.window.find_result(self, count))
        find_controller.connect("failed-to-find-text", lambda _controller: self.window.find_result(self, 0))
        self.web.set_vexpand(True)
        self.web.connect("decide-policy", self._policy)
        self.web.connect("web-process-terminated", self._terminated)
        self.web.connect("load-failed", self._load_failed)
        self.web.connect("permission-request", lambda web, req: (req.deny(), True)[1])
        self.box.append(self.web)
        self.page = window.tabs.append(self.box)
        self.page.set_title(self.name)
        self.page.set_tooltip(str(self.path) if self.path else "Unsaved document")
        self.web.load_uri("reader://app/index.html")
        if self.path:
            self.reload()
        else:
            self.text = "# Untitled\n\n"

    @property
    def name(self):
        return self.path.name if self.path else "Untitled"

    def js(self, expression, callback=None):
        if self.closed:
            return
        def complete(web, result, _data):
            try:
                value = web.evaluate_javascript_finish(result)
                if callback:
                    callback(value, None)
            except Exception as exc:
                if callback:
                    callback(None, exc)
                elif os.environ.get("MR_DEBUG"):
                    print("JavaScript:", exc, flush=True)
        self.web.evaluate_javascript(expression, -1, None, None, None, complete, None)

    def call(self, method, *args):
        encoded = ",".join(json.dumps(x, ensure_ascii=True) for x in args)
        self.js(f"void window.reader?.{method}({encoded})")

    def request(self, method, done, *extra):
        request_id = uuid.uuid4().hex
        self.pending[request_id] = done
        self.call(method, request_id, *extra)
        def timeout():
            callback = self.pending.pop(request_id, None)
            if callback:
                callback({"ok": False, "error": "The document did not respond. Please retry."})
            return GLib.SOURCE_REMOVE
        GLib.timeout_add_seconds(25, timeout)

    def _message(self, manager, value):
        if self.closed:
            return
        try:
            message = json.loads(value.to_string())
            kind = message.get("type")
            if kind != "ready" and message.get("documentId") not in (None, self.id):
                return
            if kind != "ready" and message.get("revision", self.revision) != self.revision:
                callback = self.pending.pop(message.get("requestId"), None)
                if callback:
                    callback({"ok": False, "error": "The document changed. Please retry this action."})
                return
            if kind == "ready":
                self.ready = True
                if self.snapshot or self.path is None:
                    self.load_frontend()
            elif kind == "loaded":
                if message.get("revision", self.revision) != self.revision:
                    return
                self.loaded = True
                self.mode_busy = False
                if not self.saving:
                    self.web.set_sensitive(True)
                self.editable = message.get("editable", True) and (not self.snapshot or self.snapshot.editable)
                self.edit_reason = message.get("reason")
                self.issues = message.get("issues", [])
                if self.fragment:
                    self.call("scrollToHeading", self.fragment)
                    self.fragment = None
                if not self.editable:
                    self.requested_mode = "read"
                self.set_mode(self.requested_mode)
                self.window.update_controls()
                if self.window.current is self:
                    self.window.status("Preparing editor…" if self.mode_busy else "Ready" if self.editable else (self.edit_reason or "Reading only"))
                self.window.persist()
                if self.recovery is not None:
                    draft = self.recovery
                    self.recovery = None
                    self.offer_recovery(draft)
            elif kind == "mode":
                # A mode request can import and construct the editor. Only the
                # current revision's completion may expose editable controls.
                next_mode = message.get("mode")
                if next_mode not in ("read", "edit"):
                    return
                self.mode = next_mode
                self.mode_busy = bool(message.get("busy", False))
                self.editable = message.get("editable", self.editable) and (not self.snapshot or self.snapshot.editable)
                self.edit_reason = message.get("reason")
                if not self.mode_busy:
                    self.requested_mode = self.mode
                self.window.update_controls()
                if self.window.current is self:
                    self.window.status("Preparing editor…" if self.mode_busy else self.edit_reason or "Ready")
                if not self.mode_busy and self.reload_deferred:
                    self.reload_deferred = False
                    self.reload()
            elif kind == "dirty":
                if message.get("revision", self.revision) != self.revision:
                    return
                self.text = message.get("markdown", self.text)
                self.dirty = message.get("dirty", True)
                self.edit_serial += 1
                self.update_title()
                self.queue_draft()
                self.window.update_controls()
            elif kind in ("serialized", "exportReady", "state", "rebased"):
                callback = self.pending.pop(message.get("requestId"), None)
                if callback:
                    callback(message)
            elif kind == "openLink":
                self.window.open_link(self, message.get("href", ""))
            elif kind == "resolveAsset":
                try:
                    url = self.app.register_asset(self, message.get("src", ""))
                except Exception:
                    url = None
                self.call("assetResolved", message.get("requestId"), url)
            elif kind == "chooseImage":
                self.window.choose_image(self, message.get("requestId"))
            elif kind == "status":
                self.window.status(message.get("message", ""))
            elif kind == "copyText":
                self.web.get_clipboard().set(message.get("text", ""))
            elif kind == "save":
                self.window.save(self)
            elif kind == "saveAs":
                self.window.save_as(self)
            elif kind == "scroll":
                self.anchor = message.get("state")
        except Exception as exc:
            if os.environ.get("MR_DEBUG"):
                print("Bridge:", exc, flush=True)

    def load_frontend(self):
        if not self.ready or self.closed:
            return
        self.loaded = False
        # Keep the user's intended mode across a new disk revision, but never
        # let the previous editor's pending completion enable its controls.
        if not self.mode_busy:
            self.requested_mode = self.mode
        self.mode = "read"
        self.mode_busy = False
        self.window.update_controls()
        self.call("load", {"documentId": self.id, "revision": self.revision,
                            "markdown": self.text, "editable": not self.snapshot or self.snapshot.editable,
                            "savedMarkdown": self.snapshot.text if self.snapshot else "",
                            "theme": self.window.effective_theme(), "zoom": self.window.zoom,
                            "width": self.window.width_mode,
                            "scrollState": self.anchor, "filename": self.name})

    def set_mode(self, mode):
        if self.closed or not self.loaded or self.saving:
            return
        if mode == "edit" and not self.editable:
            return
        self.requested_mode = mode
        self.mode_busy = self.mode_busy or mode != self.mode
        self.call("setMode", mode)
        self.window.update_controls()

    def reload(self, force=False):
        if not self.path or self.closed or self.saving:
            return
        requested_path = str(self.path)
        self.read_generation += 1
        generation = self.read_generation
        def done(snapshot, error):
            if self.closed or generation != self.read_generation or self.saving:
                return
            if error:
                self.notice(f"Cannot read {self.name}: {error}", retry=True)
                if self.retry_count < 3:
                    self.retry_count += 1
                    GLib.timeout_add(400 * self.retry_count, lambda: (self.reload(), False)[1])
                return
            self.retry_count = 0
            if self.snapshot and snapshot.digest == self.snapshot.digest and snapshot.canonical_path == self.snapshot.canonical_path:
                self.reload_deferred = False
                self.snapshot = snapshot
                self.watch()
                return
            def apply_update(synced=True):
                if self.closed or generation != self.read_generation or self.saving:
                    return
                if not synced:
                    if getattr(self, "loaded", False):
                        self.web.set_sensitive(True)
                    return
                self.reload_deferred = False
                if self.dirty and not force:
                    self.conflict = True
                    self.notice("This file changed on disk. Your unsaved edits are safe.", conflict=True)
                    self.window.update_controls()
                    if getattr(self, "loaded", False):
                        self.web.set_sensitive(True)
                    return
                self.snapshot = snapshot
                self.path = snapshot.path
                self.text = snapshot.text
                self.revision += 1
                self.conflict = False
                self.dirty = False
                self.banner.set_visible(False)
                if snapshot.warning:
                    self.notice(snapshot.warning)
                self.watch()
                self.update_title()
                self.load_frontend()
            # Flush WebKit's latest transaction before replacing an edit buffer.
            # Its dirty notification may still be queued when this read finishes.
            if not force and getattr(self, "loaded", False) and getattr(self, "mode", "read") == "edit":
                if getattr(self, "mode_busy", False):
                    # A mode transition cannot be flushed safely yet. Read
                    # again once it completes, coalescing bursts and retaining
                    # the ordinary version/dirty-buffer checks for fresh data.
                    self.reload_deferred = True
                    return
                self.window.sync_edits(self, apply_update)
            else:
                apply_update()
        job(lambda: read_document(requested_path), done)

    def watch(self):
        if not self.path:
            return
        directories = {self.path.parent}
        if self.snapshot:
            directories.add(self.snapshot.canonical_path.parent)
        for asset in self.watched_assets:
            directories.add(asset.parent)
        for directory in directories:
            if str(directory) in self.monitors:
                continue
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
                monitor.connect("changed", self.changed)
                self.monitors[str(directory)] = monitor
            except GLib.Error:
                pass

    def watch_asset(self, path):
        self.watched_assets.add(path)
        self.watch()

    def changed(self, monitor, file, other, event):
        if self.closed:
            return
        paths = {Path(p) for p in (file.get_path() if file else None, other.get_path() if other else None) if p}
        targets = {self.path}
        if self.snapshot:
            targets.add(self.snapshot.canonical_path)
        if not paths.intersection(targets | self.watched_assets):
            return
        if self.reload_timer:
            GLib.source_remove(self.reload_timer)
        asset_change = bool(paths.intersection(self.watched_assets))
        def refresh():
            self.reload_timer = 0
            if asset_change:
                self.call("refreshAssets")
            self.reload()
            return GLib.SOURCE_REMOVE
        self.reload_timer = GLib.timeout_add(250, refresh)

    def notice(self, message, conflict=False, retry=False):
        self.banner_label.set_text(message)
        self.retry_button.set_visible(retry)
        self.compare_button.set_visible(conflict)
        self.reload_button.set_visible(conflict)
        self.copy_button.set_visible(conflict)
        self.banner.set_visible(True)

    def update_title(self):
        self.window.update_titles()

    def queue_draft(self):
        if self.draft_timer:
            GLib.source_remove(self.draft_timer)
        self.draft_timer = GLib.timeout_add(500, self.write_draft)

    def write_draft(self):
        self.draft_timer = 0
        try:
            if self.dirty:
                self.app.store.write_draft(self.id, {"path": str(self.path) if self.path else None,
                    "text": self.text, "base_digest": self.snapshot.digest if self.snapshot else None,
                    "time": time.time()})
            else:
                self.app.store.remove_draft(self.id)
        except Exception as exc:
            self.window.status(f"Recovery copy unavailable: {exc}")
        return GLib.SOURCE_REMOVE

    def offer_recovery(self, draft):
        def choose(answer):
            if answer == 1:
                self.text = draft.get("text", "")
                self.dirty = True
                self.mode = "edit"
                self.requested_mode = "edit"
                self.conflict = bool(self.snapshot and self.snapshot.digest != draft.get("base_digest"))
                self.revision += 1
                self.load_frontend()
                self.update_title()
                if self.conflict:
                    self.notice("Recovered edits differ from the current file on disk.", conflict=True)
                self.queue_draft()
            else:
                self.app.store.remove_draft(self.id)
        alert(self.window, "Recover unsaved edits?", f"An unsaved draft of {self.name} is available.", ["Discard Draft", "Recover"], choose, 1, 0)

    def discard_reload(self):
        alert(self.window, "Reload from disk?", "This discards your unsaved edits in this tab.",
              ["Cancel", "Reload"], lambda answer: self._discard() if answer == 1 else None, 0, 0)

    def _discard(self):
        self.dirty = False
        self.conflict = False
        self.app.store.remove_draft(self.id)
        self.snapshot = None
        self.reload(force=True)

    def _policy(self, web, decision, kind):
        if kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            uri = action.get_request().get_uri()
            if uri.startswith("reader://app/"):
                decision.use()
            else:
                decision.ignore()
                if action.is_user_gesture():
                    self.window.open_link(self, uri)
            return True
        if kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        return False

    def _terminated(self, web, reason):
        self.write_draft()
        self.loaded = False
        self.mode_busy = False
        self.window.update_controls()
        self.notice("The document renderer stopped. Your draft is preserved. Reopen the tab to recover it.")

    def _load_failed(self, web, event, uri, error):
        self.notice(f"Could not load the document view: {error.message}")
        return False

    def cleanup(self):
        self.closed = True
        self.read_generation += 1
        self.pending.clear()
        for monitor in self.monitors.values():
            monitor.cancel()
        for source in (self.reload_timer, self.draft_timer):
            if source:
                GLib.source_remove(source)
        self.app.resources = {k: v for k, v in self.app.resources.items() if v[0] != self.id}


class ReaderWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Markdown Reader", default_width=1120, default_height=820)
        self.app = app
        self.documents = []
        self.session = app.store.load_session()
        self.zoom = float(self.session.get("zoom", 1.0))
        self.theme = self.session.get("theme", "system")
        self.width_mode = self.session.get("width", "comfortable")
        if self.width_mode not in ("comfortable", "wide"):
            self.width_mode = "comfortable"
        self.app.lookup_action("reading-width").set_state(GLib.Variant("s", self.width_mode))
        self.recents = self.session.get("recent", [])
        self.closing = False
        self.checking_close = False
        self.syncing_controls = False
        self.set_theme(self.theme)
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.theme_changed())
        self.connect("close-request", self.close_request)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Markdown Reader")
        self.title_widget = title
        header.set_title_widget(title)
        open_button = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Open document (Ctrl+O)")
        self.open_button = open_button
        open_button.set_action_name("app.open")
        header.pack_start(open_button)
        self.mode_box = Gtk.Box(css_classes=["linked", "reader-mode"])
        self.read_button = Gtk.ToggleButton(label="Read", active=True)
        self.edit_button = Gtk.ToggleButton(label="Edit")
        self.edit_button.set_group(self.read_button)
        self.read_button.connect("toggled", lambda btn: self.mode_changed("read") if btn.get_active() else None)
        self.edit_button.connect("toggled", lambda btn: self.mode_changed("edit") if btn.get_active() else None)
        self.mode_box.append(self.read_button)
        self.mode_box.append(self.edit_button)
        header.pack_start(self.mode_box)
        self.save_button = Gtk.Button(label="Save", action_name="app.save", css_classes=["suggested-action"])
        header.pack_end(self.save_button)
        menu = Gio.Menu()
        for label, action in [("New Document", "new"), ("Close Document", "close-tab"),
                              ("Save As…", "save-as"), ("Export PDF…", "export"),
                              ("Find…", "find"), ("Toggle Outline", "outline")]:
            menu.append(label, "app." + action)
        zoom_menu = Gio.Menu()
        for label, action in [("Zoom In", "zoom-in"), ("Zoom Out", "zoom-out"), ("Actual Size", "zoom-reset")]:
            zoom_menu.append(label, "app." + action)
        self.menu = menu
        self.zoom_menu = zoom_menu
        self.zoom_menu_index = menu.get_n_items()
        menu.append_submenu(f"Text Size · {round(self.zoom * 100)}%", zoom_menu)
        themes = Gio.Menu()
        for label, name in [("Follow System", "system"), ("Light", "light"), ("Dark", "dark")]:
            themes.append(label, "app.theme::" + name)
        menu.append_submenu("Appearance", themes)
        widths = Gio.Menu()
        widths.append("Comfortable", "app.reading-width::comfortable")
        widths.append("Wide", "app.reading-width::wide")
        menu.append_submenu("Reading Width", widths)
        menu.append("About Markdown Reader", "app.about")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_button)
        outline = Gtk.Button(icon_name="view-list-symbolic", tooltip_text="Toggle outline (Ctrl+Shift+O)", action_name="app.outline")
        self.outline_button = outline
        header.pack_end(outline)
        find = Gtk.Button(icon_name="edit-find-symbolic", tooltip_text="Find (Ctrl+F)", action_name="app.find")
        self.find_button = find
        header.pack_end(find)
        root.append(header)
        self.tabs = Adw.TabView()
        self.tabs.set_vexpand(True)
        self.tabs.connect("notify::selected-page", lambda *_: self.selected_page_changed())
        self.tabs.connect("close-page", self.close_page)
        bar = Adw.TabBar(view=self.tabs, autohide=False)
        bar.set_expand_tabs(False)
        bar.add_css_class("reader-tabs")
        bar.set_visible(False)
        self.tab_bar = bar
        root.append(bar)
        self.searchbar = Gtk.SearchBar()
        search_box = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(hexpand=True, placeholder_text="Find in document")
        self.search.connect("search-changed", self.search_changed)
        self.find_document = None
        self.search_results = Gtk.Label(css_classes=["dim-label"])
        self.search_results.set_visible(False)
        self.search.connect("next-match", lambda *_: self.current.web.get_find_controller().search_next() if self.current else None)
        self.search.connect("previous-match", lambda *_: self.current.web.get_find_controller().search_previous() if self.current else None)
        search_box.append(self.search)
        search_box.append(self.search_results)
        self.searchbar.set_child(search_box)
        self.searchbar.connect_entry(self.search)
        self.searchbar.connect("notify::search-mode-enabled", lambda bar, *_:
                               self.dismiss_find() if not bar.get_search_mode() and self.find_document else None)
        # Find opens explicitly with Ctrl+F. Capturing the whole window here
        # would let ordinary typing open search instead of editing the document.
        root.append(self.searchbar)
        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(self.tabs, "documents")
        self.welcome = self.make_welcome()
        self.stack.add_named(self.welcome, "welcome")
        self.stack.set_visible_child_name("welcome")
        root.append(self.stack)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(root)
        self.status_toast = None
        self.set_content(self.toast_overlay)
        self.update_controls()

    @property
    def current(self):
        page = self.tabs.get_selected_page()
        return next((doc for doc in self.documents if doc.page == page), None)

    def make_welcome(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        outer.append(Gtk.Image(icon_name="text-x-generic-symbolic", pixel_size=64))
        outer.append(Gtk.Label(label="A little clarity for your documents.", css_classes=["title-1"]))
        outer.append(Gtk.Label(label="Open a Markdown file to read, edit, or export it.", css_classes=["dim-label"]))
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        buttons.append(Gtk.Button(label="Open Document…", action_name="app.open", css_classes=["suggested-action", "pill"]))
        buttons.append(Gtk.Button(label="New Document", action_name="app.new", css_classes=["pill"]))
        outer.append(buttons)
        self.recent_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        outer.append(self.recent_list)
        self.refresh_recents()
        return outer

    def refresh_recents(self):
        while child := self.recent_list.get_first_child():
            self.recent_list.remove(child)
        for path in self.recents[:6]:
            if not Path(path).is_file():
                continue
            location = Path(path)
            button = Gtk.Button(label=location.name + "  ·  " + location.parent.name, css_classes=["flat"])
            button.set_tooltip_text(path)
            button.connect("clicked", lambda btn, p=path: self.open_path(p))
            self.recent_list.append(button)

    def restore_session(self):
        drafts = self.app.store.load_drafts()
        used = set()
        for item in self.session.get("tabs", []):
            path = item.get("path")
            if path and Path(path).is_file():
                doc = self.open_path(path)
                doc.anchor = item.get("anchor")
                if item.get("id") in drafts:
                    old_id = doc.id
                    doc.id = item["id"]
                    doc.recovery = drafts[doc.id]
                    used.add(doc.id)
        for draft_id, draft in drafts.items():
            if draft_id in used:
                continue
            path = draft.get("path")
            doc = self.open_path(path) if path and Path(path).is_file() else self.new_document()
            doc.id = draft_id
            doc.recovery = draft
        selected = self.session.get("selected")
        for doc in self.documents:
            if str(doc.path) == selected:
                self.tabs.set_selected_page(doc.page)

    def open_path(self, path, fragment=None):
        file = Gio.File.new_for_commandline_arg(str(path))
        if not file.is_native():
            self.status("Only local documents can be opened.")
            return None
        opened = Path(file.get_path()).absolute()
        canonical = opened.resolve()
        for doc in self.documents:
            if doc.path and doc.path.resolve() == canonical:
                self.tabs.set_selected_page(doc.page)
                if fragment:
                    doc.call("scrollToHeading", fragment)
                return doc
        doc = Document(self, opened)
        doc.fragment = fragment
        self.documents.append(doc)
        self.tabs.set_selected_page(doc.page)
        self.stack.set_visible_child_name("documents")
        self.recents = [str(opened)] + [p for p in self.recents if p != str(opened)]
        self.recents = self.recents[:20]
        self.update_titles()
        self.update_controls()
        self.status("Opening " + opened.name + "…")
        return doc

    def new_document(self):
        doc = Document(self)
        self.documents.append(doc)
        self.tabs.set_selected_page(doc.page)
        self.stack.set_visible_child_name("documents")
        self.update_controls()
        return doc

    def choose_open(self):
        filters = Gio.ListStore.new(Gtk.FileFilter)
        markdown = Gtk.FileFilter(name="Markdown documents")
        markdown.add_pattern("*.md")
        markdown.add_pattern("*.markdown")
        filters.append(markdown)
        all_files = Gtk.FileFilter(name="All files")
        all_files.add_pattern("*")
        filters.append(all_files)
        dialog = Gtk.FileDialog(title="Open Markdown documents", filters=filters)
        def chosen(d, result):
            try:
                files = d.open_multiple_finish(result)
                for i in range(files.get_n_items()):
                    self.open_path(files.get_item(i).get_path())
            except GLib.Error:
                pass
        dialog.open_multiple(self, None, chosen)

    def update_titles(self):
        for doc in self.documents:
            name = doc.name
            if doc.path and sum(other.name == name for other in self.documents) > 1:
                name += " · " + doc.path.parent.name
            doc.page.set_title(("● " if doc.dirty else "") + name)
            path = str(doc.path) if doc.path else "Untitled document"
            doc.page.set_tooltip(("Unsaved changes · " if doc.dirty else "") + path)
            doc.page.update_property([Gtk.AccessibleProperty.DESCRIPTION],
                                     [("Unsaved changes. " if doc.dirty else "Saved. ") + path])
        self.update_controls()

    def selected_page_changed(self):
        if self.find_document is not self.current:
            self.dismiss_find()
        self.update_controls()

    def update_controls(self):
        if not hasattr(self, "tabs"):
            return
        doc = self.current
        self.syncing_controls = True
        self.tab_bar.set_visible(bool(doc))
        self.mode_box.set_visible(bool(doc))
        self.outline_button.set_visible(bool(doc))
        self.find_button.set_visible(bool(doc))
        self.mode_box.set_sensitive(bool(doc and doc.loaded))
        self.edit_button.set_sensitive(bool(doc and doc.loaded and doc.editable and not doc.mode_busy and not doc.saving))
        self.edit_button.set_tooltip_text(doc.edit_reason if doc and not doc.editable else "Edit document (Ctrl+E)")
        if doc and (doc.requested_mode if doc.mode_busy else doc.mode) == "edit":
            self.edit_button.set_active(True)
        else:
            self.read_button.set_active(True)
        self.save_button.set_visible(bool(doc and (doc.mode == "edit" or doc.dirty)))
        self.save_button.set_sensitive(bool(doc and doc.loaded and doc.editable and not doc.saving and not doc.mode_busy and (doc.dirty or not doc.path)))
        self.title_widget.set_title("Markdown Reader")
        self.title_widget.set_subtitle("Preparing editor…" if doc and doc.mode_busy else "")
        self.title_widget.set_tooltip_text(str(doc.path) if doc and doc.path else "Unsaved document" if doc else "Markdown Reader")
        self.set_title((doc.name + " — " if doc else "") + "Markdown Reader")
        available = bool(doc and doc.loaded and not doc.saving and not doc.mode_busy)
        enabled = {
            "close-tab": bool(doc and not doc.saving),
            "save": bool(available and doc.editable and (doc.dirty or not doc.path)),
            "save-as": bool(available and doc.editable),
            "export": available,
            "find": available,
            "edit": bool(available and doc.editable),
            "outline": available,
            "zoom-in": bool(doc), "zoom-out": bool(doc), "zoom-reset": bool(doc),
        }
        for name, value in enabled.items():
            self.app.lookup_action(name).set_enabled(value)
        self.syncing_controls = False

    def mode_changed(self, mode):
        if self.syncing_controls:
            return
        doc = self.current
        if doc and doc.loaded and not doc.saving and (mode != "edit" or (doc.editable and not doc.mode_busy)):
            doc.set_mode(mode)

    def toggle_edit(self):
        if self.current:
            self.mode_changed("read" if self.current.mode == "edit" or self.current.mode_busy else "edit")

    def show_find(self):
        if self.current:
            self.find_document = self.current
            self.searchbar.set_search_mode(True)
            self.search.grab_focus()

    def dismiss_find(self):
        previous = self.find_document
        self.find_document = None
        if previous and not previous.closed:
            previous.web.get_find_controller().search_finish()
        self.searchbar.set_search_mode(False)
        self.search.set_text("")
        self.search_results.set_text("")
        self.search_results.set_visible(False)

    def find_result(self, doc, count):
        if doc is not self.current or doc is not self.find_document or not self.search.get_text():
            return
        self.search_results.set_text("No matches" if not count else f"{count} match" + ("" if count == 1 else "es"))
        self.search_results.set_visible(True)

    def search_changed(self, entry):
        if not self.current:
            return
        controller = self.current.web.get_find_controller()
        if entry.get_text():
            self.find_document = self.current
            self.search_results.set_text("Searching…")
            self.search_results.set_visible(True)
            controller.search(entry.get_text(), WebKit.FindOptions.CASE_INSENSITIVE | WebKit.FindOptions.WRAP_AROUND, 1000)
        else:
            controller.search_finish()
            self.search_results.set_text("")
            self.search_results.set_visible(False)

    def toggle_outline(self):
        if self.current:
            self.current.call("toggleOutline")

    def zoom_by(self, delta, reset=False):
        self.zoom = 1.0 if reset else max(.75, min(2.0, round(self.zoom + delta, 2)))
        self.menu.remove(self.zoom_menu_index)
        self.menu.insert_submenu(self.zoom_menu_index, f"Text Size · {round(self.zoom * 100)}%", self.zoom_menu)
        for doc in self.documents:
            doc.call("setZoom", self.zoom)
        self.status(f"Text size: {round(self.zoom * 100)}%")
        self.persist()

    def set_theme(self, theme):
        if theme not in ("system", "light", "dark"):
            return
        self.theme = theme
        action = self.app.lookup_action("theme")
        if action:
            action.set_state(GLib.Variant("s", theme))
        modes = {"system": Adw.ColorScheme.DEFAULT, "light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}
        Adw.StyleManager.get_default().set_color_scheme(modes.get(theme, Adw.ColorScheme.DEFAULT))
        if hasattr(self, "documents"):
            self.theme_changed()
        if hasattr(self, "tabs"):
            self.persist()

    def set_width_mode(self, mode):
        if mode not in ("comfortable", "wide"):
            return
        self.width_mode = mode
        self.app.lookup_action("reading-width").set_state(GLib.Variant("s", mode))
        for doc in self.documents:
            doc.call("setWidth", mode)
        self.persist()

    def effective_theme(self):
        return "dark" if Adw.StyleManager.get_default().get_dark() else "light"

    def theme_changed(self):
        for doc in self.documents:
            doc.call("setTheme", self.effective_theme())

    def status(self, message):
        if self.status_toast:
            self.status_toast.dismiss()
            self.status_toast = None
        if not message or message == "Ready":
            return
        self.status_toast = Adw.Toast.new(str(message)[:300])
        self.status_toast.set_timeout(5)
        self.toast_overlay.add_toast(self.status_toast)

    def save_current(self, done=None):
        doc = self.current
        if doc:
            self.save(doc, done=done)

    def save(self, doc, done=None):
        if doc.mode_busy:
            self.status("Wait for the editor to finish preparing before saving.")
            if done:
                done(False)
            return
        if not doc.path:
            self.save_as(doc, done=done)
            return
        if doc.conflict:
            doc.notice("This file changed on disk. Compare the versions or save a copy.", conflict=True)
            if done:
                done(False)
            return
        if not doc.editable or not doc.loaded or doc.saving:
            if done:
                done(False)
            return
        self.begin_save(doc)
        base_snapshot = doc.snapshot
        def serialized(message):
            if not message.get("ok", True):
                self.end_save(doc)
                doc.notice("Save stopped: " + message.get("error", "Document preservation check failed."))
                if done:
                    done(False)
                return
            text = message.get("markdown", doc.text)
            if not message.get("dirty", doc.dirty):
                self.end_save(doc)
                if done:
                    done(True)
                self.status("No unsaved changes")
                return
            saved_edit_serial = doc.edit_serial
            self.update_controls()
            def saved(snapshot, error):
                self.end_save(doc)
                if error:
                    if isinstance(error, ConflictError):
                        doc.conflict = True
                        doc.notice("The file changed before saving. Your edits are preserved.", conflict=True)
                    else:
                        doc.notice(f"Could not save: {error}")
                    self.update_controls()
                    if done:
                        done(False)
                    return
                doc.snapshot = snapshot
                if doc.edit_serial == saved_edit_serial:
                    doc.text = snapshot.text
                    doc.dirty = False
                doc.conflict = False
                doc.banner.set_visible(False)
                doc.call("markSaved", snapshot.text)
                doc.update_title()
                doc.write_draft()
                self.status("Saved " + doc.name)
                self.persist()
                if done:
                    done(True)
            job(lambda: save_document(base_snapshot, text), saved)
        doc.request("serialize", serialized)

    def begin_save(self, doc):
        doc.saving = True
        doc.read_generation += 1
        doc.web.set_sensitive(False)
        self.update_controls()

    def end_save(self, doc):
        doc.saving = False
        doc.web.set_sensitive(True)
        self.update_controls()

    def save_as(self, doc=None, done=None):
        doc = doc or self.current
        if not doc or not doc.loaded or doc.saving or doc.mode_busy:
            if doc and doc.mode_busy:
                self.status("Wait for the editor to finish preparing before saving.")
            if done:
                done(False)
            return
        dialog = Gtk.FileDialog(title="Save Markdown As", initial_name=doc.name if doc.path else "Untitled.md")
        if doc.path:
            dialog.set_initial_folder(Gio.File.new_for_path(str(doc.path.parent)))
        def chosen(d, result):
            try:
                destination = Path(d.save_finish(result).get_path())
                expected = read_document(destination) if destination.exists() else None
            except GLib.Error:
                if done:
                    done(False)
                return
            except Exception as exc:
                doc.notice(str(exc))
                if done:
                    done(False)
                return
            self.save_to(doc, destination, expected, done)
        dialog.save(self, None, chosen)

    def save_to(self, doc, destination, expected=None, done=None):
        if doc.closed or not doc.loaded or doc.saving or doc.mode_busy:
            if doc.mode_busy:
                self.status("Wait for the editor to finish preparing before saving.")
            if done:
                done(False)
            return
        self.begin_save(doc)
        base_snapshot = doc.snapshot
        def serialized(message):
            if not message.get("ok", True):
                self.end_save(doc)
                doc.notice(message.get("error", "Document cannot be saved safely."))
                if done:
                    done(False)
                return
            text = message.get("markdown", doc.text)
            def write(rebased):
                if not rebased.get("ok", True):
                    self.end_save(doc)
                    doc.notice(rebased.get("error", "Could not update relative links."))
                    if done:
                        done(False)
                    return
                output = rebased.get("markdown", text)
                def saved(snapshot, error):
                    self.end_save(doc)
                    if error:
                        doc.notice(f"Could not save a copy: {error}")
                        if done:
                            done(False)
                        return
                    doc.path = snapshot.path
                    doc.snapshot = snapshot
                    doc.text = snapshot.text
                    doc.dirty = False
                    doc.conflict = False
                    doc.banner.set_visible(False)
                    doc.revision += 1
                    doc.load_frontend()
                    doc.watch()
                    doc.update_title()
                    doc.write_draft()
                    self.status("Saved " + doc.name)
                    self.persist()
                    if done:
                        done(True)
                job(lambda: save_copy(base_snapshot, output, destination, expected_snapshot=expected), saved)
            if doc.path and doc.path.parent != destination.parent:
                doc.request("rebase", write, str(doc.path.parent), str(destination.parent))
            else:
                write({"ok": True, "markdown": text})
        doc.request("serialize", serialized)

    def compare(self, doc):
        try:
            disk = read_document(doc.path).text
        except Exception as exc:
            doc.notice(f"Cannot compare: {exc}", conflict=True)
            return
        diff = "".join(difflib.unified_diff(disk.splitlines(True), doc.text.splitlines(True), fromfile="Current file on disk", tofile="Your unsaved edits"))
        dialog = Adw.Window(title="Compare changes", transient_for=self, modal=True, default_width=900, default_height=640)
        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        layout.append(Adw.HeaderBar())
        text = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                            top_margin=16, bottom_margin=16, left_margin=16, right_margin=16)
        text.get_buffer().set_text(diff or "The document contents are identical.")
        scroll = Gtk.ScrolledWindow(vexpand=True, child=text)
        layout.append(scroll)
        dialog.set_content(layout)
        dialog.present()

    def choose_image(self, doc, request_id):
        dialog = Gtk.FileDialog(title="Insert an existing image")
        def chosen(d, result):
            try:
                path = Path(d.open_finish(result).get_path())
                base = doc.path.parent if doc.path else Path.home()
                source = os.path.relpath(path, base) if doc.path else str(path)
                from urllib.parse import quote
                doc.call("imageChosen", request_id, quote(source, safe="/"))
            except GLib.Error:
                doc.call("imageChosen", request_id, None)
        dialog.open(self, None, chosen)

    def open_link(self, doc, href):
        if not isinstance(href, str) or not href:
            return
        parsed = urlsplit(href)
        if href.startswith("#"):
            doc.call("scrollToHeading", unquote(href[1:]))
        elif parsed.scheme.lower() in ("https", "http", "mailto"):
            Gtk.UriLauncher.new(href).launch(self, None, None)
        elif parsed.scheme.lower() in ("", "file") and doc.path:
            try:
                resolved = resolve_local_reference(doc.path, href)
                if not resolved:
                    return
                path, fragment = resolved
                if path.suffix.lower() in (".md", ".markdown"):
                    self.open_path(path, fragment)
                else:
                    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(path)))
                    launcher.open_containing_folder(self, None, None)
            except Exception as exc:
                self.status(f"Cannot open link: {exc}")

    def export_current(self):
        doc = self.current
        if not doc or not doc.loaded:
            return
        def choose_paper(answer):
            if answer == 0:
                return
            paper = "iso_a4" if answer == 1 else "na_letter"
            filters = Gio.ListStore.new(Gtk.FileFilter)
            pdf_filter = Gtk.FileFilter(name="PDF documents")
            pdf_filter.add_pattern("*.pdf")
            filters.append(pdf_filter)
            dialog = Gtk.FileDialog(title="Export PDF", initial_name=Path(doc.name).stem + ".pdf", filters=filters)
            def chosen(d, result):
                try:
                    output = d.save_finish(result).get_path()
                except GLib.Error:
                    return
                self.prepare_pdf(doc, output, paper)
            dialog.save(self, None, chosen)
        alert(self, "Export PDF", "Choose the page size. Unsaved edits are included without saving the original file.",
              ["Cancel", "A4", "Letter"], choose_paper, 1, 0)

    def prepare_pdf(self, doc, path, paper="iso_a4", done=None):
        self.status("Preparing document for export…")
        def prepared(message):
            issues = message.get("issues", [])
            if not message.get("ok", True):
                issues.append(message.get("error", "Rendering did not finish."))
            if issues:
                def answer(choice):
                    if choice == 1:
                        self.print_pdf(doc, path, paper, done, message, allow_missing=True)
                    else:
                        doc.call("exportFinished")
                        if done:
                            done(False)
                alert(self, "Some content could not be rendered", "\n".join(str(x) for x in issues[:8]),
                      ["Cancel", "Export as Displayed"], answer, 0, 0)
            else:
                self.print_pdf(doc, path, paper, done, message)
        doc.request("prepareExport", prepared)

    def print_pdf(self, doc, path, paper="iso_a4", done=None, payload=None, allow_missing=False):
        if payload is None:
            return self.prepare_pdf(doc, path, paper, done)
        resources = {key: value[1] for key, value in self.app.resources.items() if value[0] == doc.id}
        base_path = doc.path or Path.cwd() / "Untitled.md"
        def finished(output, error):
            doc.call("exportFinished")
            if error:
                self.status("PDF export failed: " + str(error))
                doc.notice("PDF export failed: " + str(error))
            else:
                self.status("PDF exported to " + str(output))
            if done:
                done(error is None)
        job(lambda: export_pdf(payload, Path(path), paper, FRONTEND, base_path, resources, allow_missing), finished)

    def close_current(self):
        if self.current:
            self.tabs.close_page(self.current.page)

    def close_page(self, view, page):
        doc = next((d for d in self.documents if d.page == page), None)
        if not doc:
            return False
        if doc.saving:
            self.status("Wait for this document to finish saving.")
            view.close_page_finish(page, False)
            return True
        def synced(ok):
            if doc.closed:
                return
            if not ok:
                self.finish_close(doc, False)
            elif doc.dirty:
                def answer(choice):
                    if choice == 1:
                        self.save(doc, done=lambda success: self.finish_close(doc, success))
                    else:
                        self.finish_close(doc, choice == 2)
                alert(self, "Save changes to " + doc.name + "?", "Your original file has not been changed.",
                      ["Cancel", "Save", "Discard"], answer, 1, 0)
            else:
                self.finish_close(doc, True)
        self.sync_edits(doc, synced)
        return True

    def sync_edits(self, doc, done):
        """Flush the editor before decisions that can destroy an unsaved buffer."""
        if getattr(doc, "mode_busy", False):
            self.status("Wait for the editor to finish preparing, or switch to Read.")
            done(False)
            return
        doc.web.set_sensitive(False)
        revision, read_generation = doc.revision, doc.read_generation
        if not doc.loaded or not doc.editable:
            done(True)
            return
        def received(message):
            if doc.closed or doc.revision != revision or doc.read_generation != read_generation or doc.saving:
                done(False)
                return
            if not message.get("ok", True):
                doc.notice(message.get("error", "Could not check unsaved edits. Please retry."))
                doc.web.set_sensitive(True)
                done(False)
                return
            doc.text = message.get("markdown", doc.text)
            doc.dirty = message.get("dirty", doc.dirty)
            doc.update_title()
            doc.write_draft()
            done(True)
        doc.request("serialize", received)

    def finish_close(self, doc, confirm):
        if doc.closed:
            return
        if confirm:
            if self.find_document is doc:
                self.dismiss_find()
            doc.cleanup()
            self.app.store.remove_draft(doc.id)
            self.documents.remove(doc)
        else:
            if not doc.saving:
                doc.web.set_sensitive(True)
        self.tabs.close_page_finish(doc.page, confirm)
        if not self.documents:
            self.dismiss_find()
            self.status("Ready")
            self.refresh_recents()
            self.stack.set_visible_child_name("welcome")
        self.update_titles()
        self.persist()

    def close_request(self, *_args):
        if self.closing:
            return False
        if self.checking_close:
            return True
        if any(d.saving for d in self.documents):
            self.status("Wait for the document to finish saving before closing.")
            return True
        self.checking_close = True
        docs = list(self.documents)
        for doc in docs:
            doc.web.set_sensitive(False)
        def cancel():
            self.checking_close = False
            for doc in docs:
                if not doc.closed and not doc.saving:
                    doc.web.set_sensitive(True)
        def decide():
            dirty = [d for d in docs if d.dirty]
            if not dirty:
                self.persist()
                self.closing = True
                self.close()
                return
            def answer(choice):
                if choice == 2:
                    for doc in dirty:
                        self.app.store.remove_draft(doc.id)
                        doc.dirty = False
                    self.closing = True
                    self.close()
                elif choice == 1:
                    def next_save(index=0):
                        if index == len(dirty):
                            self.closing = True
                            self.close()
                        else:
                            doc = dirty[index]
                            def saved(ok):
                                if ok:
                                    doc.web.set_sensitive(False)
                                    next_save(index + 1)
                                else:
                                    cancel()
                            self.save(doc, done=saved)
                    next_save()
                else:
                    cancel()
            alert(self, "Save changes before closing?", f"{len(dirty)} document(s) have unsaved changes.",
                  ["Cancel", "Save All", "Discard"], answer, 1, 0)
        def next_sync(index=0):
            if index == len(docs):
                decide()
            else:
                self.sync_edits(docs[index], lambda ok: next_sync(index + 1) if ok else cancel())
        next_sync()
        return True

    def persist(self):
        if not hasattr(self, "tabs"):
            return
        try:
            self.app.store.save_session({"tabs": [{"id": d.id, "path": str(d.path) if d.path else None,
                "anchor": d.anchor} for d in self.documents if d.path or d.dirty],
                "selected": str(self.current.path) if self.current and self.current.path else None,
                "recent": self.recents, "theme": self.theme, "zoom": self.zoom,
                "width": self.width_mode})
        except Exception as exc:
            self.status(f"Could not remember session: {exc}")

    def about(self):
        dialog = Adw.AboutDialog(application_name="Markdown Reader", application_icon=APP_ID,
            version="0.1.0", developer_name="Codex by OpenAI", license_type=Gtk.License.MIT_X11,
            comments="A quiet place to read and edit your Markdown documents.\nGTK · WebKit · Milkdown · KaTeX · Mermaid")
        dialog.present(self)
