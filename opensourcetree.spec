# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for OpenSourceTree
#
# Build:   pyinstaller opensourcetree.spec
# Output:  dist/opensourcetree/   (onedir bundle)
#
# Size strategy (target < 100 MB)
# ────────────────────────────────
# • System Qt6 native libs  → declared as PKGBUILD deps, NOT bundled.
# • System X11/xcb/GL/ICU   → same.
# • numpy, pygments          → bundled (app depends on them, not always installed).
# • Unused Qt Python modules → excluded explicitly.
# • strip=True               → debug symbols removed from all .so files.

import os
from pathlib import Path

project_root = Path(SPECPATH)

# ── Shared-library name-prefixes that come from system packages ───────────────
# These will be declared as PKGBUILD dependencies so we don't bundle them.
_SYSTEM_LIB_PREFIXES = (
    # Qt6 native  (qt6-base, qt6-svg, qt6-declarative, …)
    "libQt6",
    # XCB / X11  (libxcb, xorg-server)
    "libxcb", "libX", "libxkb",
    # OpenGL / EGL / Vulkan  (mesa, vulkan-icd-loader)
    "libGL", "libEGL", "libvulkan", "libGLdispatch", "libGLX",
    # Wayland  (wayland)
    "libwayland",
    # DRM  (libdrm)
    "libdrm", "libgbm",
    # ICU  (icu) — can be 30+ MB; always present where Qt6 is installed
    "libicu",
    # Font stack  (fontconfig, freetype2, harfbuzz)
    "libfontconfig", "libfreetype", "libharfbuzz",
    # DBus / GLib  (dbus, glib2)
    "libdbus", "libglib", "libgobject", "libgio", "libgmodule", "libgthread",
    # Standard C/C++ runtime  (gcc-libs, glibc)
    "libstdc++", "libgcc_s", "libc.so", "libm.so", "libdl.so",
    "libpthread", "librt.so", "libresolv",
    # Compression  (zlib, zstd, brotli, lz4)
    "libz.so", "libzstd", "libbrotli", "liblz4", "liblzma",
    # Misc system
    "libexpat", "libuuid", "libsystemd", "libmount", "libblkid",
    "libpcre", "libpcre2", "libmd.so", "libbsd.so",
)


def _is_system_lib(name: str) -> bool:
    base = os.path.basename(name)
    return any(base.startswith(p) for p in _SYSTEM_LIB_PREFIXES)


# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "locales"),               "locales"),
        (str(project_root / "assets"),                "assets"),
        (str(project_root / "style.qss"),             "."),
        (str(project_root / "OpenSourceTreeIcon.png"), "."),
    ],
    hiddenimports=[
        # PyQt6 modules used by the app
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtNetwork",
        "PyQt6.QtSvg",
        "PyQt6.QtSvgWidgets",
        "PyQt6.QtPrintSupport",
        "PyQt6.QtDBus",
        # Pygments – the subset we actually use
        "pygments.lexers.diff",
        "pygments.lexers.shell",
        "pygments.lexers.python",
        "pygments.formatters.terminal256",
        "pygments.formatters.html",
        "pygments.styles.monokai",
    ],
    excludes=[
        # ── Unused Qt Python bindings ─────────────────────────────────────────
        "PyQt6.QtBluetooth",
        "PyQt6.QtMultimedia",
        "PyQt6.QtMultimediaWidgets",
        "PyQt6.QtNfc",
        "PyQt6.QtPositioning",
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "PyQt6.QtQuick3D",
        "PyQt6.QtQuickWidgets",
        "PyQt6.QtRemoteObjects",
        "PyQt6.QtSensors",
        "PyQt6.QtSerialPort",
        "PyQt6.QtSpatialAudio",
        "PyQt6.QtSql",
        "PyQt6.QtStateMachine",
        "PyQt6.QtTest",
        "PyQt6.QtTextToSpeech",
        "PyQt6.QtWebChannel",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebSockets",
        "PyQt6.QtXml",
        "PyQt6.QtHelp",
        "PyQt6.QtDesigner",
        "PyQt6.QtOpenGL",
        "PyQt6.QtOpenGLWidgets",
        "PyQt6.QtPdf",
        "PyQt6.QtPdfWidgets",
        # ── Unused stdlib ─────────────────────────────────────────────────────
        "tkinter",
        "unittest",
        "distutils",
        "lib2to3",
        "xmlrpc",
        "pydoc",
        "doctest",
        "turtle",
        "turtledemo",
        "antigravity",
        "this",
        "_msi",
        "winreg",
        "winsound",
        "msvcrt",
        "ensurepip",
        "venv",
        "idlelib",
    ],
    noarchive=False,
)

# ── Drop system-provided shared libraries ─────────────────────────────────────
# They are declared as PKGBUILD runtime dependencies; no need to bundle them.
a.binaries = TOC([
    entry for entry in a.binaries
    if not _is_system_lib(entry[0])
])

# ── Build ─────────────────────────────────────────────────────────────────────
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="opensourcetree",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,       # strip debug symbols → meaningfully smaller .so files
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project_root / "OpenSourceTreeIcon.png"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,
    name="opensourcetree",
)
