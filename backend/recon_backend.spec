# PyInstaller spec для запаковки бекенду в один directory.
#
# Збираємо ONEDIR (а не ONEFILE) — швидший старт і простіше debug, бо Flutter
# вантажить subprocess щоразу при запуску.
#
# Запуск локально:
#   cd backend && .venv/Scripts/pip install pyinstaller
#   .venv/Scripts/pyinstaller recon_backend.spec --clean --noconfirm
# На виході — dist/recon_backend/ з recon_backend.exe і всіма необхідними DLL.

# ruff: noqa
block_cipher = None

a = Analysis(
    ['recon_backend/launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # SQLAlchemy + aiosqlite — PyInstaller часом губить async-діалект
        'aiosqlite',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.ext.asyncio',
        # Pydantic v2 — деякі реcursive імпорти
        'pydantic',
        'pydantic_core',
        'pydantic_settings',
        # FastAPI / Starlette — для multipart upload
        'multipart',
        'python_multipart',
        # Парсери XLSX (pandas → openpyxl)
        'openpyxl',
        'xlsxwriter',
        # rapidfuzz внутрішні
        'rapidfuzz.distance',
        # uvicorn loops/protocols
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Викидаємо великі пакунки яких НЕ використовуємо
        'matplotlib', 'scipy', 'PIL', 'PyQt5', 'PyQt6', 'tkinter', 'IPython',
        'jupyter', 'notebook', 'pytest', 'sphinx',
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
    [],
    exclude_binaries=True,
    name='recon_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX іноді конфліктує з антивірусом
    console=False,       # без чорного вікна — UI запускає у фоні
    disable_windowed_traceback=False,
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
    name='recon_backend',
)
