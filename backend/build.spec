# -*- mode: python ; coding: utf-8 -*-
# PyInstaller build specification for CODE OS backend (v4.0.0 Fresh-Laptop Ready)
#
# Generates a standalone, fully-bundled directory (ONEDIR mode) containing all heavy
# AI dependencies, ONNX runtime engines, C-bindings, FastAPI/uvicorn runtimes, and
# OS hooks. Using --onedir prevents Windows Defender false-positive quarantines and
# achieves sub-second cold starts on end-user laptops without Python installed.

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

datas = []
binaries = []
hidden_imports = []

# ── 1. Heavy AI Libraries & C-Bindings Collection ─────────────────────────────

heavy_ai_packages = [
    'chromadb',
    'sentence_transformers',
    'onnxruntime',
    'faster_whisper',
    'ctranslate2',
    'pyttsx3',
    'pyautogui',
    'mss',
    'pynput',
    'fitz',
    'pymupdf',
    'selenium',
    'webdriver_manager',
    'PIL',
    'numpy',
]

for pkg in heavy_ai_packages:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden_imports += h
        print(f"[build.spec] Collected {pkg}: {len(d)} datas, {len(b)} binaries, {len(h)} hidden imports")
    except Exception as exc:
        print(f"[build.spec] Notice: collect_all('{pkg}') skipped: {exc}")

# ── 2. Core Server & Framework Packages ───────────────────────────────────────

core_packages = [
    'fastapi',
    'starlette',
    'uvicorn',
    'anyio',
    'h11',
    'httptools',
    'websockets',
    'watchfiles',
    'pydantic',
    'pydantic_core',
    'pydantic_settings',
    'aiosqlite',
    'sqlite3',
    'cryptography',
    'git',
    'psutil',
    'httpx',
    'httpcore',
    'watchdog',
]

for pkg in core_packages:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden_imports += h
    except Exception as exc:
        print(f"[build.spec] Notice: collect_all('{pkg}') skipped: {exc}")

# Platform-specific OS terminal emulation hooks
if sys.platform == 'win32':
    for pkg in ['winpty', 'pywinpty']:
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hidden_imports += h
        except Exception:
            pass
else:
    for pkg in ['ptyprocess']:
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hidden_imports += h
        except Exception:
            pass

# ── 3. Explicit FastAPI & Runtime Hidden Imports ───────────────────────────────

hidden_imports += [
    # Uvicorn logging, loops, protocols, lifecycle
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',

    # Starlette & FastAPI internals
    'starlette.middleware',
    'starlette.middleware.base',
    'starlette.middleware.cors',
    'starlette.routing',
    'starlette.responses',
    'fastapi.middleware',
    'fastapi.middleware.cors',

    # Concurrency & standard runtime
    'multiprocessing',
    'multiprocessing.spawn',
    'multiprocessing.synchronize',
    'multiprocessing.pool',
    'queue',
    'sqlite3',
    '_sqlite3',
    'email_validator',
    'email.mime',
    'email.mime.text',
    'email.mime.multipart',
    'multipart',
    'multipart.multipart',
    'anyio._backends._asyncio',
    'anyio._backends._trio',
    'sniffio',
    'click',
    'certifi',
    'idna',
    'charset_normalizer',
]

# ── 4. App Source Bundling ───────────────────────────────────────────────────

# When run from backend/ or project root, include backend/app as 'app'
app_dir = 'app' if os.path.exists('app') else 'backend/app'
datas += [
    (app_dir, 'app'),
]

# ── 5. PyInstaller Analysis & Collection (--onedir mode) ──────────────────────

launcher_script = 'watchdog_launcher.py' if os.path.exists('watchdog_launcher.py') else 'backend/watchdog_launcher.py'

a = Analysis(
    [launcher_script],
    pathex=['.', 'backend'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'test', '_tkinter', 'matplotlib',
        'PyQt5', 'PySide6', 'PyQt6', 'PySide2', 'qtpy',
        'IPython', 'notebook', 'scipy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# In ONEDIR mode, EXE excludes binaries which are placed into COLLECT
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='watchdog_launcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='backend',  # Produces dist/backend/ directory containing watchdog_launcher.exe and all libs
)
