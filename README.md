# Markdown Reader

**Created by Codex, OpenAI's AI coding agent.** Codex designed, implemented, and
tested this application at the repository owner's request.

A free, local Markdown document reader for Ubuntu/GNOME. Documents stay in their
original folders. A native GTK window renders the document in Read mode without
loading or constructing the Milkdown editor. The bundled editor loads when you
choose Edit. Node is used to build the frontend, never to run the installed app.

The first Edit request prepares the editor and checks that it can preserve the
document. The native controls show “Preparing editor…” and block saving until
preparation finishes. Returning to Read shows unsaved edits; switching back to
Edit retains the same editor, document model, and Undo/Redo history. Save retains
the document-preservation and external-change checks.

The document tab stays visible even when it is the only open tab. Its close
button or **Close Document** (Ctrl+W) returns to Welcome without quitting.
Modified tabs show an unsaved mark, and closing one offers Save, Discard, or
Cancel. **Appearance**, **Reading Width**, and **Text Size** are in the window
menu. Comfortable width is the default; Wide gives technical documents more
room without changing their Markdown or PDF layout.

## Build and launch

Required native packages: Python 3, PyGObject, GTK 4, libadwaita 1, and WebKitGTK 6.
On Ubuntu, the corresponding packages are `python3-gi`, `gir1.2-gtk-4.0`,
`gir1.2-adw-1`, and `gir1.2-webkit-6.0`. Node.js and npm are development tools.
PDF export also requires an installed Chromium or Google Chrome executable.
Reading and editing use the native WebKit view and do not need that browser.

From this project directory:

```sh
npm --prefix frontend ci
npm --prefix frontend run build
/usr/bin/python3 -m markdown_reader '/absolute/path/document.md'
```

The application requires a graphical desktop session. Its JavaScript, CSS,
renderers, and maths fonts are bundled locally. Referenced web images use the network.
PDF export prints the rendered document through a temporary, isolated local
browser profile. Styles, fonts, and images are embedded in a static snapshot;
document scripts and network access are disabled in the print process. This
preserves clickable PDF links that the native WebKit print API currently omits
([upstream issue](https://bugs.webkit.org/show_bug.cgi?id=302265)).

## Install for your account

```sh
/usr/bin/python3 scripts/manage_install.py install
```

This copies the built app to `~/.local/share/markdown-reader/app`, adds
`~/.local/bin/markdown-reader`, an icon, and a desktop entry. It registers `.md`
and `.markdown` support without changing your default application. Respecting
`XDG_DATA_HOME` moves application data beneath that directory when it is set.

After checking that the app opens and renders your documents correctly:

```sh
/usr/bin/python3 scripts/manage_install.py set-default
```

The first default change records both previous Markdown handlers. Reinstallation
and repeated default changes do not overwrite that recovery record. You can then
double-click a Markdown document in Files or run `markdown-reader FILE...`.

Remove the application with:

```sh
~/.local/bin/markdown-reader-uninstall
```

Uninstall restores a previous handler only when the current handler is still
Markdown Reader. It removes only unchanged files recorded by the installer.
Original documents, Obsidian vaults, application settings, and recovery drafts
are retained. Modified or unknown installation files are retained and reported.

## Isolated packaging check

`--prefix` performs installation and MIME-default changes entirely under the
given staging directory. It does not change the user's actual MIME defaults.

```sh
/usr/bin/python3 scripts/manage_install.py --prefix "$PWD/work/staged-install" install
/usr/bin/python3 scripts/manage_install.py --prefix "$PWD/work/staged-install" set-default
/usr/bin/python3 scripts/manage_install.py --prefix "$PWD/work/staged-install" uninstall
/usr/bin/python3 -m unittest discover -s tests -v
npm --prefix frontend test
```

Actual desktop integration checks (run in a graphical desktop session):

```sh
/usr/bin/python3 tests/native_smoke.py --output work/native-check
/usr/bin/python3 tests/native_features.py --output work/native-features
/usr/bin/python3 tests/native_design.py --output work/native-design
/usr/bin/python3 tests/native_readability.py --output work/native-readability
/usr/bin/python3 tests/native_polish.py --output work/native-polish
/usr/bin/python3 tests/native_performance_correctness.py --output work/performance-correctness
/usr/bin/python3 tests/native_read_first.py --output work/native-read-first
/usr/bin/python3 tests/native_overflow.py --output work/native-overflow
/usr/bin/python3 tests/native_performance.py --output work/performance --sizes ordinary --wait-active
```

These checks use disposable fixtures and open this project's README without
changing it. Set `MR_TEST_DOCUMENT=/absolute/path/example.md` to also check a
different existing document. Test outputs and recovery state stay under `work/`.
Keep the performance test window in front: GNOME can throttle background paint
callbacks. Timings record foreground state and latency targets; `--enforce`
makes missed targets fail the run. A normal timing run reports measurements
without asserting that every target passed.

## Behaviour and verification

See [supported syntax](docs/supported-syntax.md), [privacy and data safety](docs/privacy.md),
and [verification status](docs/verification.md) for native runtime test results,
PDF checks, and the limits of automated interaction checks.
The [design references](docs/design-references.md) explain the Mac Markdown
applications considered for the reader's visual direction.
See [performance evidence](docs/performance.md) for measured responsiveness,
the benchmark procedure, and remaining delays. The measured 100 KB foreground
run opened in 1,449 ms; first entry into Edit took 1,790 ms. Editor preparation
is deferred, and not all latency targets have been met.

The project is MIT licensed. Third-party components retain their own licenses;
the frontend build includes dependency notices with its distributable assets.
