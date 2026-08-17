# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CODE OS backend server
# Bundles the entire FastAPI/uvicorn backend into a standalone binary
# so end-users do NOT need Python installed.

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collect all data and binaries for tricky packages
datas = []
binaries = []
hidden_imports = []

# FastAPI + Starlette + uvicorn
for pkg in ['uvicorn', 'starlette', 'fastapi', 'anyio', 'h11', 'httptools', 'websockets', 'watchfiles']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden_imports += h

# Pydantic
for pkg in ['pydantic', 'pydantic_core', 'pydantic_settings']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden_imports += h

# aiosqlite + sqlite
for pkg in ['aiosqlite', 'sqlite3']:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden_imports += h

# cryptography
d, b, h = collect_all('cryptography')
datas += d
binaries += b
hidden_imports += h

# gitpython
d, b, h = collect_all('git')
datas += d
binaries += b
hidden_imports += h

# psutil
d, b, h = collect_all('psutil')
datas += d
binaries += b
hidden_imports += h

# httpx
d, b, h = collect_all('httpx')
datas += d
binaries += b
hidden_imports += h

# watchdog
d, b, h = collect_all('watchdog')
datas += d
binaries += b
hidden_imports += h

# pywinpty / winpty (Windows terminal emulation — required by terminal service)
try:
    d, b, h = collect_all('winpty')
    datas += d
    binaries += b
    hidden_imports += h
except Exception:
    pass

try:
    d, b, h = collect_all('pywinpty')
    datas += d
    binaries += b
    hidden_imports += h
except Exception:
    pass

# keyring (optional, skip if not available)
try:
    d, b, h = collect_all('keyring')
    datas += d
    binaries += b
    hidden_imports += h
except Exception:
    pass

# Extra hidden imports that PyInstaller misses
hidden_imports += [
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
    'starlette.middleware',
    'starlette.middleware.base',
    'starlette.middleware.cors',
    'starlette.routing',
    'starlette.responses',
    'fastapi.middleware',
    'fastapi.middleware.cors',
    'anyio._backends._asyncio',
    'anyio._backends._trio',
    'email.mime',
    'email.mime.text',
    'email.mime.multipart',
    'multipart',
    'multipart.multipart',
    'aiosqlite',
    'sqlite3',
    '_sqlite3',
    'cryptography.hazmat',
    'cryptography.hazmat.bindings._rust',
    'sniffio',
    'click',
    'gitdb',
    'smmap',
    'httpcore',
    'certifi',
    'idna',
    'winpty',
]

# Include the app source as data (the backend/app directory)
datas += [
    ('backend/app', 'app'),
]

a = Analysis(
    ['scripts/backend_main.py'],
    pathex=['backend'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'test', '_tkinter', 'matplotlib', 'PIL', 'numpy'],
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
    name='backend-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
