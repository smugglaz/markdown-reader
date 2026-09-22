"""Document-controller regression tests without starting a desktop session."""

import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from markdown_reader.app import Document, ReaderWindow
from markdown_reader.storage import DiskSnapshot


class ReloadTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = DiskSnapshot(Path("/tmp/reader-test.md"), Path("/tmp/reader-test.md"),
                                     "Disk text", "old-etag", "old-digest")
        self.doc = SimpleNamespace(
            id="example", name="reader-test.md", path=self.snapshot.path,
            snapshot=self.snapshot, text=self.snapshot.text, closed=False,
            saving=False, dirty=False, conflict=False, revision=7,
            mode_busy=False, reload_deferred=False, pending={},
            read_generation=0, edit_serial=0, retry_count=3,
            banner=SimpleNamespace(set_visible=Mock()),
            window=SimpleNamespace(update_controls=Mock()),
            notice=Mock(), watch=Mock(), update_title=Mock(),
            queue_draft=Mock(), load_frontend=Mock(),
        )
        self.jobs = []
        self.worker = patch("markdown_reader.app.job", new=lambda function, done: self.jobs.append((function, done)))
        self.worker.start()
        self.addCleanup(self.worker.stop)
        self.doc.reload = lambda: Document.reload(self.doc)
        self.doc.window.current = self.doc
        self.doc.window.status = Mock()

    def snapshot_with(self, text="Agent update", etag="new-etag", digest="new-digest"):
        return DiskSnapshot(self.snapshot.path, self.snapshot.canonical_path, text, etag, digest)

    def notify_dirty(self, text="Latest user edit"):
        message = {"type": "dirty", "documentId": self.doc.id, "revision": 7,
                   "markdown": text, "dirty": True}
        Document._message(self.doc, None, SimpleNamespace(to_string=lambda: json.dumps(message)))

    def enable_editor_sync(self):
        self.doc.loaded = True
        self.doc.editable = True
        self.doc.mode = "edit"
        self.doc.web = SimpleNamespace(set_sensitive=Mock())
        self.doc.write_draft = Mock()
        self.requests = []
        self.doc.request = lambda method, done, *extra: self.requests.append((method, done))
        self.doc.window.sync_edits = lambda doc, done: ReaderWindow.sync_edits(self.doc.window, doc, done)

    def notify_mode(self, mode="read", busy=False, revision=7):
        message = {"type": "mode", "documentId": self.doc.id, "revision": revision,
                   "mode": mode, "busy": busy, "editable": True}
        Document._message(self.doc, None, SimpleNamespace(to_string=lambda: json.dumps(message)))

    def test_mode_completion_retries_coalesced_disk_updates_once(self):
        self.enable_editor_sync()
        self.doc.mode_busy = True
        for index in range(2):
            Document.reload(self.doc)
            self.jobs[index][1](self.snapshot_with(text=f"Deferred update {index}"), None)
        self.assertTrue(self.doc.reload_deferred)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.doc.snapshot, self.snapshot)
        self.doc.load_frontend.assert_not_called()
        self.notify_mode("edit", busy=True)
        self.assertEqual(len(self.jobs), 2)
        self.notify_mode()
        self.assertFalse(self.doc.reload_deferred)
        self.assertEqual(len(self.jobs), 3)
        self.notify_mode()
        self.assertEqual(len(self.jobs), 3)
        self.jobs[2][1](self.snapshot_with(text="Latest disk version", etag="latest"), None)
        self.assertEqual(self.doc.text, "Latest disk version")
        self.assertEqual(self.doc.snapshot.etag, "latest")
        self.assertEqual(self.doc.revision, 8)
        self.doc.load_frontend.assert_called_once()

    def test_deferred_refresh_preserves_edits_flushed_by_mode_transition(self):
        self.enable_editor_sync()
        self.doc.mode_busy = True
        Document.reload(self.doc)
        self.jobs[0][1](self.snapshot_with(), None)
        self.notify_dirty("User edit flushed before Read completes")
        self.notify_mode()
        self.jobs[1][1](self.snapshot_with(text="Newest agent update"), None)
        self.assertEqual(self.doc.text, "User edit flushed before Read completes")
        self.assertTrue(self.doc.dirty)
        self.assertTrue(self.doc.conflict)
        self.assertEqual(self.doc.snapshot, self.snapshot)
        self.assertEqual(self.doc.revision, 7)
        self.doc.load_frontend.assert_not_called()

    def test_obsolete_or_closed_mode_completion_cannot_resume_deferred_refresh(self):
        self.enable_editor_sync()
        self.doc.mode_busy = True
        Document.reload(self.doc)
        self.jobs[0][1](self.snapshot_with(), None)
        self.notify_mode(revision=6)
        self.assertTrue(self.doc.reload_deferred)
        self.assertTrue(self.doc.mode_busy)
        self.assertEqual(len(self.jobs), 1)
        self.doc.closed = True
        self.notify_mode()
        self.assertEqual(len(self.jobs), 1)
        self.doc.load_frontend.assert_not_called()

    def test_user_edit_during_async_read_is_preserved_as_conflict(self):
        Document.reload(self.doc)
        self.notify_dirty()
        self.jobs[0][1](self.snapshot_with(), None)
        self.assertEqual(self.doc.text, "Latest user edit")
        self.assertTrue(self.doc.dirty)
        self.assertTrue(self.doc.conflict)
        self.assertEqual(self.doc.revision, 7)
        self.assertEqual(self.doc.snapshot, self.snapshot)
        self.doc.load_frontend.assert_not_called()

    def test_overlapping_noop_reads_keep_revision_and_refresh_etag(self):
        Document.reload(self.doc)
        Document.reload(self.doc)
        self.jobs[0][1](self.snapshot_with(etag="obsolete-etag"), None)
        same_contents = self.snapshot_with(text=self.snapshot.text, etag="latest-etag", digest=self.snapshot.digest)
        self.jobs[1][1](same_contents, None)
        self.assertEqual(self.doc.revision, 7)
        self.assertEqual(self.doc.snapshot.etag, "latest-etag")
        self.assertEqual(self.doc.text, self.snapshot.text)
        self.doc.load_frontend.assert_not_called()
        self.notify_dirty()
        self.assertTrue(self.doc.dirty)

    def test_clean_external_update_advances_document_revision_once(self):
        Document.reload(self.doc)
        Document.reload(self.doc)
        self.jobs[1][1](self.snapshot_with(), None)
        self.jobs[0][1](self.snapshot, None)
        self.assertEqual(self.doc.text, "Agent update")
        self.assertEqual(self.doc.revision, 8)
        self.assertFalse(self.doc.dirty)
        self.doc.load_frontend.assert_called_once()

    def test_failed_read_keeps_revision_and_accepts_later_edit(self):
        Document.reload(self.doc)
        self.jobs[0][1](None, FileNotFoundError("atomic replacement in progress"))
        self.assertEqual(self.doc.revision, 7)
        self.assertEqual(self.doc.text, self.snapshot.text)
        self.notify_dirty()
        self.assertEqual(self.doc.text, "Latest user edit")
        self.assertTrue(self.doc.dirty)

    def test_read_finishing_after_save_begins_cannot_replace_buffer(self):
        Document.reload(self.doc)
        self.doc.saving = True
        self.doc.read_generation += 1
        self.jobs[0][1](self.snapshot_with(), None)
        self.assertEqual(self.doc.text, self.snapshot.text)
        self.assertEqual(self.doc.snapshot, self.snapshot)
        self.doc.load_frontend.assert_not_called()

    def test_closed_document_ignores_late_read(self):
        Document.reload(self.doc)
        self.doc.closed = True
        self.jobs[0][1](self.snapshot_with(), None)
        self.assertEqual(self.doc.text, self.snapshot.text)
        self.doc.load_frontend.assert_not_called()

    def test_reload_flushes_queued_webkit_edit_before_replacing_buffer(self):
        self.enable_editor_sync()
        Document.reload(self.doc)
        self.jobs[0][1](self.snapshot_with(), None)
        self.doc.web.set_sensitive.assert_called_with(False)
        self.doc.load_frontend.assert_not_called()
        self.assertEqual(self.requests[0][0], "serialize")
        # The transaction exists in WebKit, but no native dirty message arrived.
        self.requests[0][1]({"ok": True, "markdown": "Queued WebKit edit", "dirty": True})
        self.assertEqual(self.doc.text, "Queued WebKit edit")
        self.assertEqual(self.doc.snapshot, self.snapshot)
        self.assertTrue(self.doc.dirty)
        self.assertTrue(self.doc.conflict)
        self.assertEqual(self.doc.revision, 7)
        self.doc.load_frontend.assert_not_called()
        self.doc.web.set_sensitive.assert_called_with(True)

    def test_clean_reload_keeps_webview_frozen_until_new_frontend_load(self):
        self.enable_editor_sync()
        Document.reload(self.doc)
        self.jobs[0][1](self.snapshot_with(), None)
        self.requests[0][1]({"ok": True, "markdown": self.snapshot.text, "dirty": False})
        self.assertEqual(self.doc.text, "Agent update")
        self.assertEqual(self.doc.revision, 8)
        self.doc.load_frontend.assert_called_once()
        self.doc.web.set_sensitive.assert_called_with(False)

    def test_stale_sync_cannot_unfreeze_newer_pending_reload(self):
        self.enable_editor_sync()
        Document.reload(self.doc)
        self.jobs[0][1](self.snapshot_with(text="Older update"), None)
        Document.reload(self.doc)
        self.jobs[1][1](self.snapshot_with(text="Newest update", etag="latest", digest="latest"), None)
        self.requests[0][1]({"ok": True, "markdown": self.snapshot.text, "dirty": False})
        self.assertEqual(self.doc.text, self.snapshot.text)
        self.doc.load_frontend.assert_not_called()
        self.doc.web.set_sensitive.assert_called_with(False)
        self.requests[1][1]({"ok": True, "markdown": self.snapshot.text, "dirty": False})
        self.assertEqual(self.doc.text, "Newest update")
        self.assertEqual(self.doc.revision, 8)
        self.doc.load_frontend.assert_called_once()

    def test_pending_sync_cannot_apply_after_save_claims_document(self):
        self.enable_editor_sync()
        Document.reload(self.doc)
        self.jobs[0][1](self.snapshot_with(), None)
        self.doc.saving = True
        self.doc.read_generation += 1
        self.requests[0][1]({"ok": True, "markdown": self.snapshot.text, "dirty": False})
        self.assertEqual(self.doc.snapshot, self.snapshot)
        self.assertEqual(self.doc.revision, 7)
        self.doc.load_frontend.assert_not_called()
        self.doc.web.set_sensitive.assert_called_with(False)

    def test_stale_sync_does_not_overwrite_newer_loaded_recovery_text(self):
        self.enable_editor_sync()
        finished = Mock()
        self.doc.window.sync_edits(self.doc, finished)
        self.doc.revision += 1
        self.doc.text = "Newer loaded document"
        self.requests[0][1]({"ok": True, "markdown": "Obsolete editor text", "dirty": True})
        self.assertEqual(self.doc.text, "Newer loaded document")
        self.assertFalse(self.doc.dirty)
        self.doc.write_draft.assert_not_called()
        finished.assert_called_once_with(False)

    def test_stale_sync_does_not_replace_newer_save_buffer(self):
        self.enable_editor_sync()
        finished = Mock()
        self.doc.window.sync_edits(self.doc, finished)
        self.doc.read_generation += 1
        self.doc.saving = True
        self.doc.text = "Current save buffer"
        self.requests[0][1]({"ok": True, "markdown": "Obsolete editor text", "dirty": True})
        self.assertEqual(self.doc.text, "Current save buffer")
        self.doc.write_draft.assert_not_called()
        self.doc.web.set_sensitive.assert_called_with(False)
        finished.assert_called_once_with(False)

    def test_closed_sync_cannot_recreate_deleted_recovery_draft(self):
        self.enable_editor_sync()
        finished = Mock()
        self.doc.window.sync_edits(self.doc, finished)
        self.doc.closed = True
        self.requests[0][1]({"ok": True, "markdown": "Closed editor text", "dirty": True})
        self.assertEqual(self.doc.text, self.snapshot.text)
        self.doc.write_draft.assert_not_called()
        finished.assert_called_once_with(False)


if __name__ == "__main__":
    unittest.main()
