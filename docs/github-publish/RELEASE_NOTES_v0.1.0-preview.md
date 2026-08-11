# Capixe v0.1.0-preview

Capixe is a local-first Windows screenshot capture and retrieval app. This refreshed Prototype Preview centers the product on a simple **Folder -> Analyze -> Search** flow.

## Highlights

- Select an Images folder and browse its PNG screenshots.
- Analyze images locally with bundled OCR models.
- Search by filename or text visible inside screenshots.
- Use grid/list views, grouping, image preview, and zoom.
- Capture a region or full screen with configurable save settings.
- Follow a lightweight first-run guide on the first packaged-app launch.

## Install

Download `Capixe-v0.1.0-preview-win64.zip`, extract it completely, and run `Capixe.exe` inside the `Capixe` folder. Keep the `_internal` folder beside the executable. Python is not required.

## Notes

- Windows 10/11 (64-bit) only.
- Portable, unsigned preview build; Windows may show a SmartScreen warning.
- No installer or automatic updater.
- Image analysis currently supports PNG files and runs locally.
- Settings are stored under `%APPDATA%\Capixe`; the analysis index is stored under `%LOCALAPPDATA%\Capixe`.
