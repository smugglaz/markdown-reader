"""Exercise real Gio/file operations in disposable directories."""

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from gi.repository import Gio, GLib

from markdown_reader.storage import (
    APP_ID, ConflictError, ReadOnlyError, StateStore, local_path,
    read_document, resolve_local_reference, save_copy, save_document,
)


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "document.md"
        self.path.write_text("# Hello\n\nOriginal text.\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_utf8_bom_crlf_roundtrip_preserves_mode(self):
        self.path.write_bytes(b"\xef\xbb\xbf# Hello\r\n\r\nOriginal text.\r\n")
        self.path.chmod(0o640)
        snapshot = read_document(self.path)
        self.assertTrue(snapshot.bom)
        self.assertEqual(snapshot.newline, "\r\n")
        self.assertNotIn("\r", snapshot.text)
        saved = save_document(snapshot, snapshot.text.replace("Original", "नमस्ते"))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.path.read_bytes(), b"\xef\xbb\xbf# Hello\r\n\r\n" + "नमस्ते text.\r\n".encode())
        self.assertNotEqual(snapshot.digest, saved.digest)
        self.assertEqual(saved.text, "# Hello\n\nनमस्ते text.\n")

    def test_noop_keeps_bytes_inode_and_mtime(self):
        self.path.write_bytes(b"\xef\xbb\xbf# Hello\r\n")
        before = self.path.stat()
        snapshot = read_document(self.path)
        with patch("markdown_reader.storage._replace_existing") as replacement:
            saved = save_document(snapshot, snapshot.text)
            replacement.assert_not_called()
        self.assertEqual(saved.digest, snapshot.digest)
        self.assertEqual(self.path.stat().st_ino, before.st_ino)
        self.assertEqual(self.path.stat().st_mtime_ns, before.st_mtime_ns)

    def test_read_and_file_uri_handle_special_filenames(self):
        path = self.directory / "a # 100% नमस्ते.md"
        path.write_text("unicode ✓", encoding="utf-8")
        self.assertEqual(read_document(path).text, "unicode ✓")
        self.assertEqual(read_document(path.as_uri()).path, path)
        self.assertEqual(local_path(str(path)), path)
        with self.assertRaises(ValueError):
            read_document("file://remote-host/etc/passwd")
        with self.assertRaises(ValueError):
            read_document("https://example.com/file.md")

    def test_external_write_conflicts_and_preserves_external_bytes(self):
        snapshot = read_document(self.path)
        self.path.write_text("Agent changed this.\n")
        with self.assertRaises(ConflictError):
            save_document(snapshot, "My unsaved edits.\n")
        self.assertEqual(self.path.read_text(), "Agent changed this.\n")

    def test_atomic_external_replace_conflicts(self):
        snapshot = read_document(self.path)
        replacement = self.directory / "replacement.md"
        replacement.write_text("Atomic agent update")
        replacement.replace(self.path)
        with self.assertRaises(ConflictError):
            save_document(snapshot, "user edits")
        self.assertEqual(self.path.read_text(), "Atomic agent update")

    def test_hash_detects_external_write_with_restored_mtime(self):
        snapshot = read_document(self.path)
        before = self.path.stat()
        self.path.write_bytes(self.path.read_bytes().replace(b"Hello", b"World"))
        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(ConflictError):
            save_document(snapshot, "new user text")
        self.assertIn("World", self.path.read_text())

    def test_deleted_source_conflicts_without_recreation(self):
        snapshot = read_document(self.path)
        self.path.unlink()
        with self.assertRaises(ConflictError):
            save_document(snapshot, "user text")
        self.assertFalse(self.path.exists())

    def test_noop_does_not_hide_a_conflict(self):
        snapshot = read_document(self.path)
        self.path.write_text("agent update")
        with self.assertRaises(ConflictError):
            save_document(snapshot, snapshot.text)

    def test_symlink_preserved_and_target_modified(self):
        linked = self.directory / "link.md"
        linked.symlink_to(self.path.name)
        snapshot = read_document(linked)
        self.assertEqual(snapshot.path, linked)
        self.assertEqual(snapshot.canonical_path, self.path)
        self.assertEqual(snapshot.identity, read_document(self.path).identity)
        save_document(snapshot, "user edit\n")
        self.assertTrue(linked.is_symlink())
        self.assertEqual(self.path.read_text(), "user edit\n")

    def test_retargeted_symlink_does_not_write_either_file(self):
        linked = self.directory / "link.md"
        other = self.directory / "other.md"
        other.write_text("Other document")
        linked.symlink_to(self.path)
        snapshot = read_document(linked)
        linked.unlink()
        linked.symlink_to(other)
        with self.assertRaises(ConflictError):
            save_document(snapshot, "user edit")
        self.assertEqual(self.path.read_text(), snapshot.text)
        self.assertEqual(other.read_text(), "Other document")

    def test_invalid_encoding_binary_and_mixed_newlines_are_readonly(self):
        for content in (b"caf\xe9\n", b"\xff\xfeH\0i\0", b"a\r\nb\nc\r"):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                snapshot = read_document(self.path)
                self.assertFalse(snapshot.editable)
                self.assertTrue(snapshot.warning)
                with self.assertRaises(ReadOnlyError):
                    save_document(snapshot, "replacement")
                self.assertEqual(self.path.read_bytes(), content)

    def test_readonly_permissions_prevent_save(self):
        snapshot = read_document(self.path)
        self.path.chmod(0o444)
        try:
            with self.assertRaises(ReadOnlyError):
                save_document(snapshot, "changed")
            self.assertEqual(self.path.read_text(), snapshot.text)
        finally:
            self.path.chmod(0o644)

    def test_failed_gio_replace_preserves_original(self):
        snapshot = read_document(self.path)
        error = GLib.Error.new_literal(Gio.io_error_quark(), "Simulated full disk", Gio.IOErrorEnum.NO_SPACE)
        with patch.object(Gio.File, "replace_contents", side_effect=error):
            with self.assertRaises(GLib.Error):
                save_document(snapshot, "changed")
        self.assertEqual(self.path.read_text(), snapshot.text)

    def test_gio_etag_conflict_maps_to_conflict_error(self):
        snapshot = read_document(self.path)
        error = GLib.Error.new_literal(Gio.io_error_quark(), "Changed", Gio.IOErrorEnum.WRONG_ETAG)
        with patch.object(Gio.File, "replace_contents", side_effect=error):
            with self.assertRaises(ConflictError):
                save_document(snapshot, "changed")
        self.assertEqual(self.path.read_text(), snapshot.text)

    def test_real_gio_rejects_write_between_precheck_and_replace(self):
        snapshot = read_document(self.path)
        original_replace = Gio.File.replace_contents
        def write_after_precheck(file, *args):
            previous = self.path.stat()
            self.path.write_text("agent wins the race")
            os.utime(self.path, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
            return original_replace(file, *args)
        with patch.object(Gio.File, "replace_contents", new=write_after_precheck):
            with self.assertRaises(ConflictError):
                save_document(snapshot, "user edits")
        self.assertEqual(self.path.read_text(), "agent wins the race")

    def test_save_copy_can_rescue_buffer_after_source_update(self):
        snapshot = read_document(self.path)
        self.path.write_text("external update")
        target = self.directory / "copy #%.md"
        saved = save_copy(snapshot, "my unsaved buffer", target)
        self.assertEqual(saved.path, target)
        self.assertEqual(target.read_text(), "my unsaved buffer")
        self.assertEqual(self.path.read_text(), "external update")

    def test_save_new_document_uses_utf8_lf_without_bom(self):
        target = self.directory / "new document.md"
        saved = save_copy(None, "# नमस्ते\r\n\r\nNew document.\r\n", target)
        self.assertEqual(target.read_bytes(), "# नमस्ते\n\nNew document.\n".encode())
        self.assertFalse(saved.bom)
        self.assertEqual(saved.newline, "\n")
        self.assertTrue(saved.editable)
        self.assertEqual(saved.path, target)

    def test_save_new_document_protects_existing_destination(self):
        before = self.path.read_bytes()
        with self.assertRaises(ConflictError):
            save_copy(None, "unsaved new document", self.path)
        self.assertEqual(self.path.read_bytes(), before)
        expected = read_document(self.path)
        saved = save_copy(None, "confirmed new document", self.path, expected)
        self.assertEqual(saved.text, "confirmed new document")
        with self.assertRaises(ConflictError):
            save_copy(None, "stale overwrite", self.path, expected)
        self.assertEqual(self.path.read_text(), "confirmed new document")

    def test_save_copy_refuses_existing_and_broken_symlink(self):
        snapshot = read_document(self.path)
        with self.assertRaises(ConflictError):
            save_copy(snapshot, "replacement", self.path)
        broken = self.directory / "broken.md"
        broken.symlink_to(self.directory / "missing.md")
        with self.assertRaises(ConflictError):
            save_copy(snapshot, "replacement", broken)
        self.assertTrue(broken.is_symlink())
        self.assertEqual(self.path.read_text(), snapshot.text)
        self.assertFalse(list(self.directory.glob(".*.tmp")))

    def test_confirmed_copy_checks_expected_version(self):
        snapshot = read_document(self.path)
        target = self.directory / "existing.md"
        target.write_text("expected destination")
        expected = read_document(target)
        save_copy(snapshot, "saved copy", target, expected)
        self.assertEqual(target.read_text(), "saved copy")
        with self.assertRaises(ConflictError):
            save_copy(snapshot, "second overwrite", target, expected)
        self.assertEqual(target.read_text(), "saved copy")

    def test_copy_race_cannot_overwrite_new_destination(self):
        snapshot = read_document(self.path)
        target = self.directory / "copy.md"
        real_link = os.link
        def compete(source, destination):
            Path(destination).write_text("external creation")
            return real_link(source, destination)
        with patch("markdown_reader.storage.os.link", side_effect=compete):
            with self.assertRaises(ConflictError):
                save_copy(snapshot, "user copy", target)
        self.assertEqual(target.read_text(), "external creation")
        self.assertFalse(list(self.directory.glob(".*.tmp")))

    def test_failed_copy_does_not_publish_partial_file(self):
        snapshot = read_document(self.path)
        target = self.directory / "copy.md"
        with patch("markdown_reader.storage.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_copy(snapshot, "user copy", target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.directory.glob(".*.tmp")))

    def test_relative_reference_resolution_keeps_encoded_filename_and_fragment(self):
        base = self.directory / "notes" / "doc.md"
        resolved = resolve_local_reference(base, "../assets/a%20%23%20100%25.png#hello%20world")
        self.assertEqual(resolved, (self.directory / "assets" / "a # 100%.png", "hello world"))
        self.assertEqual(resolve_local_reference(base, "#a%23b"), (base, "a#b"))
        self.assertEqual(resolve_local_reference(base, self.path.as_uri() + "#intro"), (self.path, "intro"))
        for uri in ("https://example.com/p.png", "mailto:user@example.com", "//remote-host/file", "file://remote/file", "http://[broken"):
            self.assertIsNone(resolve_local_reference(base, uri))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.store = StateStore(self.directory / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def test_reading_empty_state_creates_nothing(self):
        self.assertEqual(self.store.load_session(), {})
        self.assertEqual(self.store.load_drafts(), {})
        self.assertFalse(self.store.base_dir.exists())

    def test_atomic_session_and_private_drafts_roundtrip(self):
        self.store.save_session({"tabs": ["/tmp/space #%.md"], "theme": "system"})
        self.store.write_draft("../../not-a-path", {"text": "नमस्ते", "path": "/tmp/file.md", "revision": 2})
        self.assertEqual(self.store.load_session()["theme"], "system")
        self.assertEqual(self.store.load_drafts()["../../not-a-path"]["text"], "नमस्ते")
        files = list(self.store.base_dir.rglob("*.json"))
        self.assertEqual(len(files), 2)
        for path in files:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.store.remove_draft("../../not-a-path")
        self.store.remove_draft("../../not-a-path")
        self.assertEqual(self.store.load_drafts(), {})

    def test_corrupt_state_is_ignored_and_valid_drafts_retained(self):
        self.store.write_draft("valid", {"text": "unsaved"})
        (self.store.base_dir / "session.json").write_text("broken json")
        (self.store.drafts_dir / "corrupt.json").write_text("{")
        (self.store.drafts_dir / "spoofed.json").write_text('{"docid":"valid","metadata":{"text":"wrong"}}')
        self.assertEqual(self.store.load_session(), {})
        self.assertEqual(self.store.load_drafts(), {"valid": {"text": "unsaved"}})

    def test_failed_session_save_preserves_previous_file(self):
        self.store.save_session({"tabs": ["one.md"]})
        with patch("markdown_reader.storage.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.save_session({"tabs": ["two.md"]})
        self.assertEqual(self.store.load_session(), {"tabs": ["one.md"]})
        self.assertFalse(list(self.store.base_dir.glob(".*.tmp")))

    def test_default_state_location_obeys_xdg(self):
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(self.directory / "custom")}):
            self.assertEqual(StateStore().base_dir, self.directory / "custom" / APP_ID)
        self.assertFalse((self.directory / "custom").exists())


if __name__ == "__main__":
    unittest.main()
