#! -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None

project_root = os.path.abspath(os.path.dirname(sys.argv[0]))

def _safe_collect_all(module_name: str):
    try:
        return collect_all(module_name)
    except Exception:
        return ([], [], [])


_pydantic_core = _safe_collect_all("pydantic_core")
_cffi = _safe_collect_all("cffi")
_clr_loader = _safe_collect_all("clr_loader")

a = Analysis(
    ["pdm_api/server.py"],
    pathex=[project_root],
    binaries=(_pydantic_core[1] or []) + (_cffi[1] or []) + (_clr_loader[1] or []),
    datas=[
        ("pdm_api/resources/*", "resources"),
    ] + _pydantic_core[0],
    hiddenimports=[
        "clr",
        "pythonnet",
        "pywintypes",
        "pythoncom",
        "win32com",
        "win32com.client",
    ] + (_pydantic_core[2] or [])
      + (_cffi[2] or [])
      + (_clr_loader[2] or [])
      + (["pydantic_core._pydantic_core"] if _pydantic_core[1] else [])
      + (["_cffi_backend"] if _cffi[1] else []),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="pdm-api-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="pdm-api-server",
)
