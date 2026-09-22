# Design references

Markdown Reader is intended for daily work with Markdown written by people and
agents. This pass studied the published features of polished Mac applications,
then applied a small set of ideas that fit a free, local Ubuntu app.

| Application | Relevant published behavior | Choice here |
| --- | --- | --- |
| [Marked 2](https://marked2app.com/help/Previewing.html) | Preview styles, text zoom, and dark viewing; its [style settings](https://marked2app.com/help/Settings_Style.html) include a text-width limit. | Keep an explicit reading width and a visible text-size value. Live file updates remain central. |
| [Typora](https://typora.io/) | A quiet, rendered editing surface with themes and focused writing modes. | Keep Read as the default and reveal visual editing only when requested. |
| [iA Writer](https://ia.net/writer/support/basics/features) | Minimal controls, Focus Mode, and deliberate typography. Its [syntax highlight](https://ia.net/writer/support/editor/syntax-highlight/syntax-highlight-mac) changes presentation without changing source. | Use restrained semantic color and keep appearance choices separate from Markdown content. |

The name [MarkItDown](https://github.com/microsoft/markitdown/blob/main/README.md)
also refers to Microsoft's document-to-Markdown converter for LLM workflows. It
is useful in that pipeline, but is not a visual Markdown reader. The Mac
previewer the user had in mind may have been Marked 2.

These are references, not dependencies or claims of feature parity. Markdown
Reader uses free local components and keeps documents in their existing folders.
