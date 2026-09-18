import sys

from . import __version__

if "--version" in sys.argv:
    print(f"Markdown Reader {__version__}")
    raise SystemExit(0)

from .app import ReaderApplication

raise SystemExit(ReaderApplication().run(sys.argv))
