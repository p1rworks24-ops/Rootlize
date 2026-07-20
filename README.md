# Capixe

Capture less. Find more.

Capixe is a Windows app for capturing and managing screenshots. It helps you save captures into a folder you choose, browse them later, add tags, and organize files — so screenshots stay findable instead of disappearing into the clipboard.

## Preview status

This is a **Prototype Preview** (`v0.1.0-preview`).

It is not a final release. Bugs, incomplete features, and breaking changes are expected.

## Features

Available in this preview:

- Region capture
- Full-screen capture
- Local screenshot folder management
- Folder browsing
- Tag management
- Search
- Bulk tag operations
- Bulk rename
- Configurable save location
- Configurable keyboard shortcuts

Not included yet:

- AI features (the AI page is a placeholder only)
- OCR

## Download

Download the Windows portable ZIP from GitHub Releases:

https://github.com/p1rworks24-ops/Capixe/releases

Look for `Capixe-v0.1.0-preview-win64.zip` when the preview Release is published.

## Installation

1. Download the ZIP from Releases.
2. Extract the ZIP completely to a folder you can write to.
3. Open the extracted `Capixe` folder and run `Capixe.exe`.
4. Keep `Capixe.exe` together with the `_internal` folder — do not move the EXE alone.

Python is **not** required for the Release ZIP build.

There is no installer. This is a portable preview build.

### Windows security warning

This preview build is **not code-signed**. Windows SmartScreen, Microsoft Defender, or your organization policy may show a warning when you download or run `Capixe.exe`.

Only continue if you trust this GitHub repository / Release and have verified the file you downloaded. Capixe does not ask you to bypass security tools blindly.

## Data storage

Capixe stores settings and tags under your user profile, not inside the app folder:

- Settings / tags: `%APPDATA%\Capixe`
- Default screenshot root (new installs): `%USERPROFILE%\Pictures\Capixe`

If you already chose another Root Folder in Settings, Capixe continues to use that path.

Expanding or moving the Capixe app folder does not move your screenshots or settings.

## Feedback

- [Bug report](https://github.com/p1rworks24-ops/Capixe/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/p1rworks24-ops/Capixe/issues/new?template=feature_request.yml)

Please do not post passwords, API keys, personal emails, or private file paths in Issues.

## Known limitations

- Windows only
- Prototype Preview — expect bugs and changes
- Unsigned build (SmartScreen may warn)
- No installer and no auto-update
- AI and OCR features are not included yet
- Capture shortcuts work only while Capixe is running

## Development

```text
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

Packaging (developers):

```text
python -m pip install -r requirements-dev.txt
python -m PyInstaller Capixe.spec --clean --noconfirm
powershell -ExecutionPolicy Bypass -File packaging\pack_release_zip.ps1
```

## License

Capixe is proprietary software.
Copyright © 2026 Capixe. All rights reserved.

This repository may be public for distribution and feedback, but that does **not** grant permission to copy, modify, redistribute, or sell the software or its source code.

See [LICENSE](LICENSE) for details.
