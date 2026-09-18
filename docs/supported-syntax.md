# Supported syntax and document fidelity

The reading surface supports CommonMark paragraphs, headings, emphasis,
links, images, lists, quotes, horizontal rules, and code, plus GitHub tables,
strikethrough, task lists, and footnotes. Extended renderers handle KaTeX maths,
Mermaid fenced diagrams, and GitHub/Obsidian-style callouts.

Visual editing is explicit. Opening a document, reading it, and switching modes
without changes must not rewrite the original. Markdown formatting can normalize
after actual edits. Protected or unsupported constructs must not be silently
discarded; a document that cannot be round-tripped safely stays readable and
explains its editing limitation.

Frontmatter and HTML sources are preserved separately from their rendered view.
Code-fence languages and metadata, footnote associations, and image/link
destinations must survive edits. A `latex` code fence remains a code example;
math uses its own notation. Embedded HTML is sanitized before display.

Images are inserted using an existing local file or a URL. Image-file drag/drop
and binary image clipboard insertion are deferred. There is no cloud sync,
account, vault database, AI integration, collaborative editing, DOCX import,
or word-processor page layout.

Consult [verification status](verification.md) for tested behaviour and the
remaining manual interaction checks; do not infer a test pass from this list.
