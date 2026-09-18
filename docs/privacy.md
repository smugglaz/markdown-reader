# Privacy and file safety

The native application owns file reads and writes. There is no local HTTP server
or runtime dependency download. The frontend receives document text and scoped
references to assets rather than unrestricted filesystem access.

PDF export uses the installed local Chromium or Google Chrome print engine. It
creates a private temporary profile and a static snapshot of the rendered
document, with its styles, fonts, and images embedded. A restrictive content
policy disables scripts, remote resources, objects, and frames in that snapshot.
The temporary profile and snapshot are removed after printing. This process
does not use your normal browser profile or an online PDF service.

HTTP and HTTPS images referenced by a document load automatically. Their hosts
receive an ordinary image request, so reading an online image is not an offline
operation. External links open only after an explicit click through the desktop
handler. Document scripts, event handlers, and frames are not executable.
Preparing a PDF can fetch referenced HTTP/HTTPS images again to embed their
bytes in the local snapshot. It does not upload the document.

Saving is explicit. A disk change while there are unsaved edits must retain the
user's buffer and block an ordinary overwrite. Local recovery drafts retain
unsaved text after a crash and are not a cloud backup. Keep the user's normal
backup system for durable document history.

Uninstall removes app-owned program files. Documents, settings, and recovery
drafts remain. The install record retains previous default handlers and restores
them only while this application still owns the respective association.
