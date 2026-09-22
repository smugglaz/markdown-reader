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

## Writing and formatting

Choose **Edit** to show the formatting toolbar. Its first control displays the
style at the cursor: **Normal text**, a heading level, or Code block. A selection
spanning different styles displays Mixed styles. Open the control to preview
heading sizes and choose a style. Its descriptions distinguish body text, the
main title, sections, and subsections. At narrow widths, common controls remain
visible and **More** holds less frequent formatting commands.

- **Normal text** (Ctrl+Alt+0) returns a heading or list item to ordinary text.
  Existing bold, italic, and links remain intact.
- **Clear formatting** removes inline styles from selected text, or from the
  current paragraph when there is no selection. It does not change heading or
  list structure. The **More** menu calls this **Clear inline formatting**.
- The bold, italic, code, link, and list controls indicate the cursor's current
  formatting. Click an active list control to return the selected items to text.
- Enter after a heading continues with Normal text.
- **Insert** contains tables, images, quotes, rules, code blocks, equations, and
  Mermaid diagrams. The **Table** menu appears inside a table and provides row
  and column actions.
- Use the arrow keys to navigate an open menu; Escape closes it.

Saving remains explicit with **Save** or Ctrl+S. Short confirmations appear
temporarily; save conflicts and document errors retain their persistent banners.

In **Read**, select **Contents** to navigate headings. In a narrow window or at
larger text sizes it opens over the page; **Close** and Escape return to the
document. The current section is marked. Long code blocks offer **Wrap lines**
for reading and **Expand** for a larger view. Tables and diagrams can also be
expanded. **Copy** and **Original** continue to use the original code text.
Wrapping and expanding change only the view, not the Markdown file.

The window menu offers **Reading Width → Comfortable / Wide**. Comfortable
keeps prose in a focused column; Wide gives tables and technical layouts more
room. The choice applies in both Read and Edit and persists across launches.
**Text Size** shows the current percentage. **Appearance** follows the system
or uses Light or Dark, with the selected choice marked in the menu. These view
settings do not edit the document or change its PDF page size.

One or more open documents always have visible tabs. Close a tab with its × or
**Close Document** (Ctrl+W); closing the final tab shows Welcome and current
recent files. A dot on a tab means unsaved edits. The close dialog offers Save,
Discard, and Cancel. Find shows a match count or “No matches”; switching tabs
closes Find so its query cannot appear to describe the wrong document.

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
