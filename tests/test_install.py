"""Meaningful isolated install/uninstall tests; never alter the user's MIME defaults."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/manage_install.py"
spec = importlib.util.spec_from_file_location("manage_install", SCRIPT)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="markdown-reader-packaging-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        files = {
            "markdown_reader/__init__.py": "",
            "markdown_reader/__main__.py": "import json,sys; print(json.dumps(sys.argv[1:]))\n",
            "frontend/dist/index.html": "<!doctype html><title>fixture</title>",
            "frontend/dist/assets/app.js": "// bundled fixture",
            "assets/icon.svg": '<svg xmlns="http://www.w3.org/2000/svg"/>',
            "LICENSE": "Fixture license",
            "README.md": "Fixture documentation",
            "docs/guide.md": "Fixture guide",
        }
        for relative, contents in files.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        self.prefix = self.base / "prefix with spaces"
        self.installation = manager.Installation(self.prefix, self.source)
        self.installation.refresh_databases = lambda: None
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def test_install_does_not_set_defaults_and_uninstall_restores_once(self):
        i = self.installation
        i.assign_default("text/markdown", "apostrophe.desktop")
        i.assign_default("text/x-markdown", "org.gnome.TextEditor.desktop")
        i.install()
        self.assertEqual(i.query_default("text/markdown"), "apostrophe.desktop")
        self.assertTrue((i.app / "frontend/dist/index.html").is_file())
        i.set_default()
        i.set_default()
        i.install()
        self.assertEqual(i.state()["previous_defaults"]["text/markdown"], "apostrophe.desktop")
        i.uninstall()
        self.assertEqual(i.query_default("text/markdown"), "apostrophe.desktop")
        self.assertEqual(i.query_default("text/x-markdown"), "org.gnome.TextEditor.desktop")
        self.assertFalse((self.prefix / "bin/markdown-reader").exists())
        self.assertFalse(i.app.exists())

    def test_later_user_default_and_unknown_documents_are_preserved(self):
        i = self.installation
        i.install()
        i.set_default()
        i.assign_default("text/markdown", "user-choice.desktop")
        unknown = i.app / "my-document.md"
        unknown.write_text("# Do not delete me\n")
        recovery = i.config / "markdown-reader/recovery/draft.md"
        recovery.parent.mkdir(parents=True)
        recovery.write_text("unsaved work")
        i.uninstall()
        self.assertEqual(i.query_default("text/markdown"), "user-choice.desktop")
        self.assertEqual(i.query_default("text/x-markdown"), "")
        self.assertEqual(unknown.read_text(), "# Do not delete me\n")
        self.assertEqual(recovery.read_text(), "unsaved work")

    def test_refuses_unowned_existing_launcher_before_installing_payload(self):
        path = self.prefix / "bin/markdown-reader"
        path.parent.mkdir(parents=True)
        path.write_text("existing user program")
        with self.assertRaisesRegex(RuntimeError, "unowned or modified"):
            self.installation.install()
        self.assertEqual(path.read_text(), "existing user program")
        self.assertFalse(self.installation.app.exists())

    def test_modified_files_survive_uninstall(self):
        i = self.installation
        i.install()
        path = i.app / "README.md"
        path.write_text("User edited this file")
        i.uninstall()
        self.assertEqual(path.read_text(), "User edited this file")
        self.assertIn(str(path), i.state()["files"])

    def test_launcher_preserves_relative_paths_and_file_uris(self):
        i = self.installation
        i.install()
        names = ["sample # 50% λ.md", "sample:colon.md"]
        uri = (self.base / "document # two.md").as_uri()
        result = subprocess.check_output([str(self.prefix / "bin/markdown-reader"), *names, uri], cwd=self.base, text=True)
        self.assertEqual(json.loads(result), [str(self.base / p) for p in names] + [uri])
        result = subprocess.check_output([str(self.prefix / "bin/markdown-reader"), "--", "-leading-dash.md"], cwd=self.base, text=True)
        self.assertEqual(json.loads(result), ["--", str(self.base / "-leading-dash.md")])

    @unittest.skipUnless(shutil.which("desktop-file-validate") and shutil.which("update-mime-database"), "desktop packaging tools unavailable")
    def test_real_desktop_and_mime_database_registration(self):
        i = self.installation
        i.refresh_databases = lambda: manager.Installation.refresh_databases(i)
        i.install()
        subprocess.run(["desktop-file-validate", str(i.data / "applications" / manager.DESKTOP_ID)], check=True)
        self.assertTrue((i.data / "mime/mime.cache").is_file())
        document = self.base / "test.markdown"
        document.write_text("# Markdown\n")
        environment = dict(os.environ, XDG_DATA_HOME=str(i.data), XDG_CONFIG_HOME=str(i.config))
        result = subprocess.check_output(["xdg-mime", "query", "filetype", str(document)], env=environment, text=True)
        self.assertEqual(result.strip(), "text/markdown")
        i.uninstall()

    def test_symlink_payload_is_rejected(self):
        (self.source / "frontend/dist/assets/unsafe.js").symlink_to("/etc/passwd")
        with self.assertRaisesRegex(RuntimeError, "symlink"):
            self.installation.install()
        self.assertFalse(self.installation.app.exists())

    def test_default_update_keeps_unrelated_configuration(self):
        i = self.installation
        path = i.config / "mimeapps.list"
        path.parent.mkdir(parents=True)
        original = "# keep this comment\n[Default Applications]\ntext/plain=editor.desktop;\n\n[Added Associations]\nimage/png=viewer.desktop;\n"
        path.write_text(original)
        i.assign_default("text/markdown", "our-handler.desktop")
        self.assertIn("# keep this comment", path.read_text())
        self.assertIn("text/plain=editor.desktop;", path.read_text())
        self.assertIn("image/png=viewer.desktop;", path.read_text())
        self.assertEqual(i.query_default("text/markdown"), "our-handler.desktop")
        i.edit_association(path, "text/markdown", None)
        self.assertEqual(path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
