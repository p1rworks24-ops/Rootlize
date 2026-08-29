# Rootlize v0.1.0-preview

This is the published Preview snapshot. It is not the current source-tree spec (`.ai/SPEC.md`).

Rootlize is a local-first Windows workspace for images already on your PC. This Prototype Preview is built around **Find → Narrow → Act → Automate**.

## Highlights

- Sign in to start, then point Rootlize at an existing local folder.
- Basic Search by filename, tags, or text visible inside images.
- Meaning Search by what an image shows. The model is bundled; no extra setup.
- Ask AI to find and organize in your own words (needs the internet after you agree).
- Organize in place and save a repeated flow as Automation.
- Capture a region or full screen with configurable save settings.
- Follow a first-run guide on the first packaged-app launch.

Your image library stays on this PC. Rootlize does not move it to a Rootlize cloud. Basic Search, OCR, and bundled Meaning Search run locally. Account features and Ask AI need sign-in and the internet.

## Install

Download `Rootlize-v0.1.0-preview-win64.zip`, extract it completely, and run `Rootlize.exe` inside the `Rootlize` folder. Keep the `_internal` folder beside the executable. Python is not required.

## Notes

- Windows 10/11 (64-bit) only.
- Portable, unsigned preview build; Windows may show a SmartScreen warning.
- No installer or automatic updater.
- Settings stay under `%APPDATA%\Capixe`; the local index stays under `%LOCALAPPDATA%\Capixe`.
