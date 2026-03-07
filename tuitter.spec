# PyInstaller spec for tuitter
# Build: pyinstaller tuitter.spec  (from the tuitter/ directory)

import sys
import os
from pathlib import Path

block_cipher = None
HERE = Path(SPECPATH)  # directory containing this .spec file

a = Analysis(
    [str(HERE / "tuitter" / "main.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=[
        # Textual CSS theme
        (str(HERE / "tuitter" / "main.tcss"), "tuitter"),
        # Subway ASCII video frames
        (str(HERE / "tuitter" / "subway_ascii_frames"), "tuitter/subway_ascii_frames"),
    ],
    hiddenimports=[
        # Textual internals
        "textual",
        "textual.app",
        "textual.widgets",
        "textual.css",
        "textual.css.query",
        "textual.reactive",
        "textual._xterm_theme",
        # Requests / urllib3 transport adapters
        "requests",
        "urllib3",
        "urllib3.contrib",
        "certifi",
        "charset_normalizer",
        "idna",
        # Imaging
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        # Keyring backends (load dynamically, must be explicit)
        "keyring",
        "keyring.backends.fail",
        "keyring.backends.null",
        "keyring.backends.SecretService",
        "keyring.backends.macOS",
        "keyring.backends.Windows",
        "keyrings.alt",
        "keyrings.alt.file",
        # JWT / auth
        "jose",
        "jose.jwt",
        "jose.backends",
        # Websockets
        "websockets",
        "websockets.legacy",
        "websockets.legacy.client",
        # Python-dotenv
        "dotenv",
        # tkinter for file-open dialogs (platform-provided, may be absent)
        "tkinter",
        "tkinter.filedialog",
        # Win32 crypto (Windows only, soft dep)
        "win32crypt",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Not used by the client
        "sqlalchemy",
        "numpy",
        "cv2",
        "alembic",
        "uvicorn",
        "fastapi",
        "mangum",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="tuitter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # TUI app — must keep the terminal attached
    disable_windowed_traceback=False,
    target_arch=None,      # let PyInstaller auto-detect; override via --target-arch
    codesign_identity=None,
    entitlements_file=None,
    # icon="tuitter/assets/icon.ico",  # uncomment once an icon exists
)
