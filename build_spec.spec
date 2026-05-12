# -*- mode: python ; coding: utf-8 -*-
"""
Shot Library - PyInstaller Spec File

Build command:
    pyinstaller build_spec.spec

Output:
    dist/ShotLibrary/
        ShotLibrary.exe
        _internal/
        storage/  (created by build.bat)
"""

import os
from pathlib import Path

block_cipher = None

# Get the project root directory
PROJECT_ROOT = Path(SPECPATH)

# Data files to include
datas = [
    # Assets (Icon.png for about/wizard)
    (str(PROJECT_ROOT / 'assets'), 'assets'),

    # Icons (SVG files)
    (str(PROJECT_ROOT / 'shot_library' / 'icons'), 'shot_library/icons'),

    # Folder preset icons
    (str(PROJECT_ROOT / 'shot_library' / 'icons' / 'folder_presets'), 'shot_library/icons/folder_presets'),

    # Themes (JSON files)
    (str(PROJECT_ROOT / 'shot_library' / 'themes' / 'built_in'), 'shot_library/themes/built_in'),
    (str(PROJECT_ROOT / 'shot_library' / 'themes' / 'custom'), 'shot_library/themes/custom'),

    # Blender plugin (for addon installer feature)
    (str(PROJECT_ROOT / 'SL_blender_plugin'), 'SL_blender_plugin'),

    # Installation script (must be physical file for Blender to run it)
    (str(PROJECT_ROOT / 'shot_library' / 'services' / 'utils' / 'install_addon.py'), 'shot_library/services/utils'),
]

# Version file (injected by build process)
version_file = PROJECT_ROOT / 'shot_library' / 'version.txt'
if version_file.exists():
    datas.append((str(version_file), 'shot_library'))

# Include ffmpeg binary if present (for video preview generation)
ffmpeg_path = PROJECT_ROOT / 'SL_blender_plugin' / 'bin' / 'ffmpeg.exe'
if ffmpeg_path.exists():
    datas.append((str(ffmpeg_path), 'SL_blender_plugin/bin'))

# Hidden imports that PyInstaller might miss
hiddenimports = [
    # PyQt6 modules
    'PyQt6.QtSvg',
    'PyQt6.QtSvgWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',

    # OpenCV for video processing
    'cv2',

    # NumPy internals that PyInstaller misses
    'numpy.core._multiarray_tests',

    # FastAPI for REST API server
    'fastapi',
    'fastapi.middleware',
    'fastapi.middleware.cors',
    'uvicorn',
    'uvicorn.config',
    'uvicorn.main',
    'starlette',
    'starlette.routing',
    'starlette.middleware',
    'starlette.middleware.cors',
    'pydantic',
    'pydantic.fields',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',

    # Standard library modules that might be dynamically imported
    'json',
    'sqlite3',
    'logging.handlers',
    'pathlib',
    'typing',

    # Watchdog for filesystem monitoring
    'watchdog',
    'watchdog.observers',
    'watchdog.events',

    # Shot library modules
    'shot_library',
    'shot_library.main',
    'shot_library.config',
    'shot_library.widgets',
    'shot_library.widgets.main_window',
    'shot_library.widgets.settings',
    'shot_library.widgets.settings.blender_integration_tab',
    'shot_library.services',
    'shot_library.services.database_service',
    'shot_library.services.addon_installer_service',
    'shot_library.themes',
    'shot_library.themes.theme_manager',
    'shot_library.models',
    'shot_library.views',
    'shot_library.utils',
    'shot_library.events',
    'shot_library.core',
]

a = Analysis(
    [str(PROJECT_ROOT / 'run.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unused modules to reduce size
        'tkinter',
        'matplotlib',
        'numpy.testing',
        'scipy',
        'pandas',
        # Exclude alternate Qt bindings — PyInstaller refuses to bundle multiple.
        # Some build environments (e.g. Anaconda) have PyQt5 alongside PyQt6.
        'PySide6',
        'shiboken6',
        'PyQt5',
        'PyQt5.sip',
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
    name='ShotLibrary',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (windowed mode)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'Icon.ico'),  # App icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ShotLibrary',
)
