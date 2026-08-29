# Build Rootlize-v0.1.0-preview-win64.zip from dist/Rootlize + packaging/README.txt
# Prerequisite: .build-venv\Scripts\python.exe tools\build_official_prototype.py
# Output: release/Rootlize-v0.1.0-preview-win64.zip  (gitignored)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VersionLabel = "v0.1.0-preview"
$ZipName = "Rootlize-$VersionLabel-win64.zip"
$Dist = Join-Path $Root "dist\Rootlize"
$Readme = Join-Path $Root "packaging\README.txt"
$ReleaseDir = Join-Path $Root "release"
$Stage = Join-Path $ReleaseDir "_stage\Rootlize"
$ZipPath = Join-Path $ReleaseDir $ZipName

if (-not (Test-Path (Join-Path $Dist "Rootlize.exe"))) {
    throw "Missing dist\Rootlize\Rootlize.exe — run PyInstaller first."
}
if (-not (Test-Path (Join-Path $Dist "_internal"))) {
    throw "Missing dist\Rootlize\_internal — run PyInstaller first."
}
if (-not (Test-Path $Readme)) {
    throw "Missing packaging/README.txt"
}

if (Test-Path (Join-Path $ReleaseDir "_stage")) {
    Remove-Item (Join-Path $ReleaseDir "_stage") -Recurse -Force
}
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
Copy-Item (Join-Path $Dist "Rootlize.exe") $Stage -Force
Copy-Item (Join-Path $Dist "_internal") (Join-Path $Stage "_internal") -Recurse -Force
Copy-Item $Readme (Join-Path $Stage "README.txt") -Force

New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }

Compress-Archive -Path $Stage -DestinationPath $ZipPath -Force
Remove-Item (Join-Path $ReleaseDir "_stage") -Recurse -Force

$item = Get-Item $ZipPath
Write-Host "Created: $($item.FullName)"
Write-Host ("Size: {0:N2} MB" -f ($item.Length / 1MB))
