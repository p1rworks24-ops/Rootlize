# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for Capixe (portable Windows build, slim Qt).

Capixe app code imports only:
  PySide6.QtCore / QtGui / QtWidgets
(PNG via QImage/QPixmap; no QtNetwork/Sql/WebEngine/Qml/Multimedia.)

Build:
  python -m PyInstaller Capixe.spec --clean --noconfirm

Distribute the entire dist/Capixe/ folder (not Capixe.exe alone).
"""

from __future__ import annotations

import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None

_SPEC_ROOT = os.path.abspath(SPECPATH)
_ICON_DIR = os.path.join(_SPEC_ROOT, "resources", "icons")
_FONT_DIR = os.path.join(_SPEC_ROOT, "resources", "fonts")
_OCR_MODEL_DIR = os.path.join(_SPEC_ROOT, "tools", "ocr_poc", "models")
_ICON_ICO = os.path.join(_ICON_DIR, "capixe.ico")

_rapidocr_datas, _rapidocr_binaries, _rapidocr_hiddenimports = collect_all("rapidocr")
_onnx_datas, _onnx_binaries, _onnx_hiddenimports = collect_all("onnxruntime")

# Qt modules Capixe never imports — keep them out of the graph when possible.
_UNUSED_QTPACKAGES = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtAsyncio",
    "PySide6.QtAxContainer",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDBus",
    "PySide6.QtDataVisualization",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickTest",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtWebView",
    "PySide6.QtXml",
]

# Path fragments under PySide6 / Qt that Capixe does not need at runtime.
# Keep: platforms, imageformats, styles, iconengines, generic (often needed).
_DENY_PATH_FRAGMENTS = (
    # User / VCS / tests (never ship)
    "/config.json",
    "\\config.json",
    "/tags.json",
    "\\tags.json",
    "/screenshots/",
    "\\screenshots\\",
    "/.pytest_cache/",
    "/.git/",
    "/__pycache__/",
    "/test_",
    # Heavy unused Qt surfaces
    "/qml/",
    "\\qml\\",
    "/translations/",  # Qt i18n catalogs; Capixe uses app.i18n Python strings
    "\\translations\\",
    "/sqldrivers/",
    "\\sqldrivers\\",
    "/multimedia/",
    "\\multimedia\\",
    "/position/",
    "\\position\\",
    "/sensors/",
    "\\sensors\\",
    "/geoservices/",
    "\\geoservices\\",
    "/canbus/",
    "\\canbus\\",
    "/designer/",
    "\\designer\\",
    "/assetimporters/",
    "\\assetimporters\\",
    "/geometryloaders/",
    "\\geometryloaders\\",
    "/sceneparsers/",
    "\\sceneparsers\\",
    "/renderers/",
    "\\renderers\\",
    "/renderplugins/",
    "\\renderplugins\\",
    "/scxmldatamodel/",
    "\\scxmldatamodel\\",
    "/texttospeech/",
    "\\texttospeech\\",
    "/webview/",
    "\\webview\\",
    "/qmllint/",
    "\\qmllint\\",
    "/qmltooling/",
    "\\qmltooling\\",
    "/vectorimageformats/",
    "\\vectorimageformats\\",
    # Unused Qt6 module DLLs / helpers (substring match on collected names)
    "qt6webengine",
    "qt6webchannel",
    "qt6webview",
    "qt6qml",
    "qt6quick",
    "qt6multimedia",
    "qt6bluetooth",
    "qt6positioning",
    "qt6location",
    "qt6pdf",
    "qt6sql",
    "qt6test",
    "qt6designer",
    "qt6help",
    "qt6charts",
    "qt6datavisualization",
    "qt6graphs",
    "qt6remoteobjects",
    "qt6sensors",
    "qt6serialbus",
    "qt6serialport",
    "qt6spatialaudio",
    "qt6statemachine",
    "qt6texttospeech",
    "qt6virtualkeyboard",
    "qt6websockets",
    "qt6networkauth",
    "qt6nfc",
    "qt6httpserver",
    "qt6protobuf",
    "qt6grpc",
    "qt63d",
    "qt6shadertools",
    "qt6scxml",
    "qt6canvaspainter",
    # Keep Qt6Network / OpenGL / Svg / DBus / PrintSupport / Xml if Analysis pulls
    # them as C++ deps of QtGui/QtWidgets — do not deny those DLL name stems.
    "pyside6design",
    "metatypes",
    "typesystems",
    "/glue/",
    "/doc/",
    "/include/",
)


def _denied(path_str: str) -> bool:
    lower = path_str.replace("\\", "/").lower()
    # Always allow essential plugin dirs even if a deny token overlaps oddly
    essential = (
        "/plugins/platforms/",
        "/plugins/imageformats/",
        "/plugins/styles/",
        "/plugins/iconengines/",
        "/plugins/generic/",
        "/plugins/platforminputcontexts/",
    )
    if any(tok in lower for tok in essential):
        # Still drop non-windows platforms if present
        if "/plugins/platforms/" in lower and not any(
            x in lower for x in ("qwindows", "qminimal", "qoffscreen")
        ):
            # keep only windows-related platform plugins
            base = os.path.basename(lower)
            if base.endswith(".dll") and not base.startswith("qwindows"):
                if base not in ("qminimal.dll", "qoffscreen.dll"):
                    return True
        return False
    return any(frag in lower for frag in _DENY_PATH_FRAGMENTS)


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[*_rapidocr_binaries, *_onnx_binaries],
    datas=[
        # Official app mark (ICO + PNG sizes) for window / splash / About
        (_ICON_DIR, "resources/icons"),
        *([(_FONT_DIR, "resources/fonts")] if os.path.isdir(_FONT_DIR) else []),
        *([(_OCR_MODEL_DIR, "resources/ocr_models")] if os.path.isdir(_OCR_MODEL_DIR) else []),
        *_rapidocr_datas,
        *_onnx_datas,
    ] if os.path.isdir(_ICON_DIR) else [],
    hiddenimports=[
        # Runtime Qt (app uses these only)
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "shiboken6",
        # Locale modules loaded by string / registry
        "app.i18n.en",
        "app.i18n.ja",
        "app.ui.app_icon",
        *_rapidocr_hiddenimports,
        *_onnx_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "tkinter",
        "unittest",
        "test",
        "tests",
        *_UNUSED_QTPACKAGES,
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.binaries = [b for b in a.binaries if not _denied(str(b[0])) and not _denied(str(b[1]))]
a.datas = [d for d in a.datas if not _denied(str(d[0])) and not _denied(str(d[1]))]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Capixe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON_ICO if os.path.isfile(_ICON_ICO) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Capixe",
)
