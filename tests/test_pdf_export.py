"""Static PDF input and publication safety, without launching a real browser."""

import base64
from email.message import Message
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from gi.repository import GLib

from markdown_reader.pdf_export import StaticDocument, bundled_styles, export_pdf


PDF = b"%PDF-1.7\nDisposable mocked browser PDF\n%%EOF\n"


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.frontend = self.directory / "frontend"
        self.assets = self.frontend / "assets"
        self.assets.mkdir(parents=True)
        (self.assets / "main.css").write_text('@font-face{font-family:Test;src:url("./test.woff2")}body{color:#123}')
        (self.assets / "test.woff2").write_bytes(b"bundled-test-font")
        self.base = self.directory / "document #%.md"
        self.base.write_text("# Original source\n")
        self.output = self.directory / "result.pdf"
        self.payload = {"html": '<article id="page"><h1>Rendered document</h1></article>', "title": "A <document> & title"}
        self.commands = []
        self.print_inputs = []
        self.browser = patch("markdown_reader.pdf_export.browser_path", return_value="/mock/browser")
        self.browser.start()
        self.addCleanup(self.browser.stop)

    def tearDown(self):
        self.temporary.cleanup()

    def fake_browser(self, command, **options):
        self.commands.append((command, options))
        source = Path(unquote(urlsplit(command[-1]).path))
        self.print_inputs.append(source.read_text())
        target = Path(next(value.split("=", 1)[1] for value in command if value.startswith("--print-to-pdf=")))
        target.write_bytes(PDF)
        return subprocess.CompletedProcess(command, 0, stderr=b"")

    def export(self, **options):
        return export_pdf(options.pop("payload", self.payload), options.pop("output", self.output),
                          options.pop("paper", "iso_a4"), self.frontend, self.base,
                          options.pop("resources", {}), **options)

    def static(self, source, resources=None, allow_missing=False):
        document = StaticDocument(self.base, resources or {}, allow_missing)
        document.feed(source)
        return "".join(document.parts)

    def test_static_local_images_embed_bytes_and_preserve_escaped_html(self):
        image = self.directory / "image & #%.png"
        image.write_bytes(b"local-image-bytes")
        source = '<p>Keep &amp; preserve &#35; text.</p><img alt="Example" src="image%20%26%20%23%25.png">'
        rendered = self.static(source)
        self.assertIn("data:image/png;base64," + base64.b64encode(image.read_bytes()).decode(), rendered)
        self.assertIn('<p>Keep &amp; preserve &#35; text.</p>', rendered)
        self.assertIn('alt="Example"', rendered)
        self.assertNotIn('src="image%', rendered)

    def test_html_entities_in_image_attributes_are_decoded_once(self):
        image = self.directory / "a&b.png"
        image.write_bytes(b"entity-image")
        rendered = self.static('<img src="a&amp;b.png">')
        self.assertIn(base64.b64encode(image.read_bytes()).decode(), rendered)

    def test_only_actual_image_attributes_are_changed(self):
        image = self.directory / "actual.png"
        image.write_bytes(b"image")
        rendered = self.static('<div>src="guide.md"</div><img title=\'src="untouched.png"\' src="actual.png">')
        self.assertIn('<div>src="guide.md"</div>', rendered)
        self.assertIn('title=\'src="untouched.png"\'', rendered)
        self.assertIn('src="data:image/png;base64,', rendered)

    def test_opaque_resource_and_svg_image_attributes_embed(self):
        image = self.directory / "figure.png"
        image.write_bytes(b"opaque-image")
        source = '<img src="reader://asset/token"><svg><image href="reader://asset/token"/></svg>'
        rendered = self.static(source, {"token": image})
        self.assertEqual(rendered.count("data:image/png;base64,"), 2)
        self.assertNotIn("reader://", rendered)
        self.assertIn("/></svg>", rendered)

    def test_relative_links_become_file_uris_and_web_and_anchors_survive(self):
        rendered = self.static('<a href="other%20%23.md#Section%20one">Local</a><a href="#inside">Inside</a><a href="https://example.com/?a=1&amp;b=2">Web</a>')
        self.assertIn((self.directory / "other #.md").as_uri() + "#Section%20one", rendered)
        self.assertIn('href="#inside"', rendered)
        self.assertIn('href="https://example.com/?a=1&amp;b=2"', rendered)

    def test_missing_resources_fail_unless_user_allows_incomplete_export(self):
        for source in ('<img src="missing.png">', '<img src="reader://asset/expired">'):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "image could not be prepared"):
                    self.static(source)
                self.assertIn('src=""', self.static(source, allow_missing=True))

    def test_remote_image_bytes_are_embedded_without_forwarding_cookies(self):
        class Response(io.BytesIO):
            url = "https://example.test/image.png"
            headers = Message()
        Response.headers["Content-Type"] = "image/png"
        response = Response(b"remote-image")
        with patch("markdown_reader.pdf_export.urlopen", return_value=response) as fetch:
            rendered = self.static('<img src="https://example.test/image.png">')
        request = fetch.call_args.args[0]
        self.assertIsNone(request.get_header("Cookie"))
        self.assertIn(base64.b64encode(b"remote-image").decode(), rendered)

    def test_nonimage_and_oversized_image_are_rejected(self):
        plain = self.directory / "secret.txt"
        plain.write_text("Not an image")
        with self.assertRaises(ValueError):
            self.static('<img src="secret.txt">')
        image = self.directory / "large.png"
        image.write_bytes(b"123456789")
        with patch("markdown_reader.pdf_export.MAX_IMAGE", 8):
            with self.assertRaises(ValueError):
                self.static('<img src="large.png">')

    def test_bundled_fonts_are_embedded(self):
        styles = bundled_styles(self.frontend)
        self.assertIn("data:font/woff2;base64,", styles)
        self.assertIn(base64.b64encode(b"bundled-test-font").decode(), styles)
        self.assertNotIn("./test.woff2", styles)

    def test_bundled_fonts_cannot_escape_through_traversal_or_symlink(self):
        outside = self.directory / "outside.woff2"
        outside.write_bytes(b"outside-data")
        for resource in ("../../outside.woff2", "link.woff2"):
            with self.subTest(resource=resource):
                if resource.startswith("link"):
                    (self.assets / resource).symlink_to(outside)
                (self.assets / "main.css").write_text(f'body{{src:url("{resource}")}}')
                with self.assertRaisesRegex(ValueError, "bundled print resource"):
                    bundled_styles(self.frontend)

    def test_missing_stylesheet_or_font_fails_before_browser(self):
        (self.assets / "test.woff2").unlink()
        with patch("markdown_reader.pdf_export.subprocess.run") as browser:
            with self.assertRaises(ValueError):
                self.export()
            browser.assert_not_called()
        (self.assets / "main.css").unlink()
        with self.assertRaisesRegex(ValueError, "stylesheet"):
            bundled_styles(self.frontend)

    def test_export_publishes_pdf_and_static_content_has_local_only_policy(self):
        original = self.base.read_bytes()
        with patch("markdown_reader.pdf_export.subprocess.run", side_effect=self.fake_browser):
            result = self.export(paper="na_letter")
        self.assertEqual(result, self.output)
        self.assertEqual(result.read_bytes(), PDF)
        self.assertEqual(self.base.read_bytes(), original)
        printed = self.print_inputs[0]
        self.assertIn("script-src 'none'", printed)
        self.assertIn("connect-src 'none'", printed)
        self.assertIn("img-src data:", printed)
        self.assertIn("@page{size:Letter", printed)
        self.assertIn("A &lt;document&gt; &amp; title", printed)
        command, options = self.commands[0]
        self.assertIn("--headless", command)
        self.assertIn("--host-resolver-rules=MAP * ~NOTFOUND", command)
        self.assertNotIn("--no-sandbox", command)
        self.assertEqual(options["timeout"], 45)
        self.assertFalse(Path(unquote(urlsplit(command[-1]).path)).exists())

    def test_existing_pdf_can_be_replaced_without_touching_source(self):
        self.output.write_bytes(b"%PDF-old")
        with patch("markdown_reader.pdf_export.subprocess.run", side_effect=self.fake_browser):
            self.export()
        self.assertEqual(self.output.read_bytes(), PDF)
        self.assertEqual(self.base.read_text(), "# Original source\n")

    def test_existing_pdf_changed_during_print_is_not_overwritten(self):
        self.output.write_bytes(b"%PDF-old")
        previous = self.output.stat()
        def competing_browser(*args, **kwargs):
            self.output.write_bytes(b"%PDF-external-change")
            os.utime(self.output, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
            return self.fake_browser(*args, **kwargs)
        with patch("markdown_reader.pdf_export.subprocess.run", side_effect=competing_browser):
            with self.assertRaises((GLib.Error, ValueError, OSError, RuntimeError)):
                self.export()
        self.assertEqual(self.output.read_bytes(), b"%PDF-external-change")

    def test_existing_pdf_deleted_during_print_is_not_recreated(self):
        self.output.write_bytes(b"%PDF-old")
        def competing_browser(*args, **kwargs):
            self.output.unlink()
            return self.fake_browser(*args, **kwargs)
        with patch("markdown_reader.pdf_export.subprocess.run", side_effect=competing_browser):
            with self.assertRaises((GLib.Error, ValueError, OSError, RuntimeError)):
                self.export()
        self.assertFalse(self.output.exists())

    def test_hash_detects_pdf_edit_with_unchanged_size_and_mtime(self):
        self.output.write_bytes(b"%PDF-old")
        previous = self.output.stat()
        def competing_browser(*args, **kwargs):
            self.output.write_bytes(b"%PDF-new")
            os.utime(self.output, ns=(previous.st_atime_ns, previous.st_mtime_ns))
            return self.fake_browser(*args, **kwargs)
        with patch("markdown_reader.pdf_export.subprocess.run", side_effect=competing_browser):
            with self.assertRaises((GLib.Error, ValueError, OSError, RuntimeError)):
                self.export()
        self.assertEqual(self.output.read_bytes(), b"%PDF-new")

    def test_new_destination_created_during_print_is_not_overwritten(self):
        def competing_browser(*args, **kwargs):
            self.output.write_bytes(b"external creation")
            return self.fake_browser(*args, **kwargs)
        with patch("markdown_reader.pdf_export.subprocess.run", side_effect=competing_browser):
            with self.assertRaises(FileExistsError):
                self.export()
        self.assertEqual(self.output.read_bytes(), b"external creation")
        self.assertFalse(list(self.directory.glob(".markdown-reader-*.pdf")))

    def test_source_and_symlink_destinations_are_rejected_before_browser(self):
        source_pdf = self.directory / "source.pdf"
        source_pdf.write_text("Protected source document")
        linked = self.directory / "linked.pdf"
        linked.symlink_to(self.base)
        with patch("markdown_reader.pdf_export.subprocess.run") as browser:
            with self.assertRaises(ValueError):
                self.export(output=self.base)
            with self.assertRaises(ValueError):
                export_pdf(self.payload, source_pdf, "iso_a4", self.frontend, source_pdf, {})
            with self.assertRaises(ValueError):
                self.export(output=linked)
            browser.assert_not_called()
        self.assertEqual(source_pdf.read_text(), "Protected source document")
        self.assertEqual(self.base.read_text(), "# Original source\n")

    def test_destination_retargeted_to_source_symlink_during_print_is_rejected(self):
        self.output.write_bytes(b"%PDF-old")
        def competing_browser(*args, **kwargs):
            self.output.unlink()
            self.output.symlink_to(self.base)
            return self.fake_browser(*args, **kwargs)
        with patch("markdown_reader.pdf_export.subprocess.run", side_effect=competing_browser):
            with self.assertRaises(ValueError):
                self.export()
        self.assertTrue(self.output.is_symlink())
        self.assertEqual(self.base.read_text(), "# Original source\n")

    def test_browser_failure_and_invalid_pdf_preserve_existing_output(self):
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                self.output.write_bytes(b"%PDF-original")
                def failed_browser(command, **options):
                    target = Path(next(value.split("=", 1)[1] for value in command if value.startswith("--print-to-pdf=")))
                    target.write_bytes(b"not-pdf")
                    return subprocess.CompletedProcess(command, 0 if invalid else 1, stderr=b"failed")
                with patch("markdown_reader.pdf_export.subprocess.run", side_effect=failed_browser):
                    with self.assertRaises(RuntimeError):
                        self.export()
                self.assertEqual(self.output.read_bytes(), b"%PDF-original")


if __name__ == "__main__":
    unittest.main()
