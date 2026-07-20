# Capixe

Capture less. Find more.

## About

Capixe is a Windows screenshot manager. It helps you capture screenshots, save them into a Root Folder you choose, browse images, apply tags, and run organize tools — so captures become reusable assets instead of a clipboard dump.

## Current Status

**Prototype Preview** (`v0.1.0-preview`).

This repository holds Capixe **source code** (intended Private). Binary ZIP distribution is planned through a separate Public repository / Releases (no Python source there).

This build is under active development. Features, UI, and data layouts may change. Treat it as an early preview, not a finished product.

## Features

Implemented in this preview:

- Region Capture and Full Screen Capture
- Capture Panel (optional always-on-top controls)
- Screenshot Root Folder and save-folder management
- Image browsing (Images)
- Tags
- Organize tools (bulk tags / rename and related hub)
- Settings (paths, shortcuts, notifications, window size)
- Local user-data storage (config and tags under AppData)
- About page with version / feedback entry points

Not implemented / placeholder:

- AI page in the navigation is a placeholder only (no AI features yet)

## Requirements

- Windows 10 or Windows 11 (64-bit)
- No Python install required for the Release ZIP build
- From source: Python 3.13+ recommended (see Development)

Other OS platforms are not supported in this preview.

## Download

Download the Windows portable ZIP from GitHub Releases (when published):

`Capixe-v0.1.0-preview-win64.zip`

Repository URL: fill in `GITHUB_OWNER` / `GITHUB_REPO` in `app/repo_links.py` (currently unset → links resolve to `https://github.com/`).

## Installation

1. Download the ZIP from Releases
2. Extract the ZIP fully to any folder you can write to
3. Open the extracted `Capixe` folder and run `Capixe.exe`
4. Keep `Capixe.exe` together with the `_internal` folder — do not move the EXE alone

This is a portable **onedir** build. There is no installer.

## Data Locations

Settings and tags (default):

`%APPDATA%\Capixe`

Default screenshot root (new installs):

`%USERPROFILE%\Pictures\Capixe`

If you already chose another Root Folder in Settings, Capixe continues to use that path.

## Windows Security Warning

This Prototype Preview is **not code-signed**. Windows SmartScreen, Defender, or your organization policy may warn when you download or run `Capixe.exe`.

Only proceed if you trust the download source (this GitHub repository / Release) and have verified the file you obtained. Capixe does not ask you to ignore security tooling blindly.

## Known Limitations

- Prototype Preview — expect bugs and breaking changes
- No installer
- No code signing
- No auto-update
- AI features are not implemented (nav placeholder only)
- Windows only
- Global capture shortcuts are registered while the app is running

## Feedback

When the public repository URL is configured, use **GitHub Issues** (Bug Report / Feature Request forms under `.github/ISSUE_TEMPLATE/`).

Until `GITHUB_OWNER` / `GITHUB_REPO` are set in `app/repo_links.py`, in-app GitHub links point at `https://github.com/` only.

Do not paste passwords, API keys, personal emails, or private file paths into Issues.

## Development

```text
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

Optional packaging tools:

```text
python -m pip install -r requirements-dev.txt
```

## Building

```text
python -m pip install -r requirements-dev.txt
python -m PyInstaller Capixe.spec --clean --noconfirm
```

Output:

`dist/Capixe/Capixe.exe` (distribute the entire `dist/Capixe/` folder)

Release ZIP (gitignored under `release/`):

```text
powershell -ExecutionPolicy Bypass -File packaging\pack_release_zip.ps1
```

Produces `release/Capixe-v0.1.0-preview-win64.zip` with:

```text
Capixe/
  Capixe.exe
  _internal/
  README.txt
```

## License

Capixe is currently private and proprietary software.
Copyright © 2026 Capixe. All rights reserved.

Public licensing terms will be determined before any public source release.

See [LICENSE](LICENSE) for details.
