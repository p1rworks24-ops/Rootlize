# Rootlize v0.1.0-preview

Prototype Preview for Windows. This is not a finished product.

Rootlize is a local-first Windows workspace for images already on your PC. The current Prototype is built around **Find → Organize → Automate**.

## Highlights

- No sign-up required. Continue as Guest.
- Windows 10 / 11, 64-bit only.
- Portable ZIP. Extract it completely, then run `Rootlize.exe`. Keep `_internal` beside it.
- Find images by filename, text, Meaning Search, or Ask AI.
- Organize what you find with tags, favorites, rename, and move.
- Save Select / Search / Action as a Workflow and run it again. You can describe the work in your own words; AI builds an editable Workflow. Confirmation stays in place before execute. Rootlize does not organize files on its own.
- Local-first: point Rootlize at a folder you already have. It is not a cloud photo library.
- Ask AI asks for consent first. After you agree, the first analysis may send images to an external AI. Later Meaning Search uses saved facts instead of resending images every time.
- AI usage is limited during the Prototype. Local search and organize still work after the limit.

## Notes

- Unsigned portable build. Windows SmartScreen may show a warning. Continue only if you downloaded this ZIP from this GitHub Release or rootlize.com, then choose More info → Run anyway.
- No installer or automatic updater.
- Python is not required.
- macOS is not available in this Prototype.
- Settings stay under `%APPDATA%\Capixe`; the local index stays under `%LOCALAPPDATA%\Capixe`.
