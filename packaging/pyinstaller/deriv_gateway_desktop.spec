# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path.cwd()


a = Analysis(
    [str(ROOT / "desktop_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "agent_prompts.json"), "."),
        (str(ROOT / "mcp_config.json"), "."),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "streamlit",
        "langgraph",
        "plotly",
        "pandas",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Deriv Smart Trading Gateway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Deriv Smart Trading Gateway",
)
app = BUNDLE(
    coll,
    name="Deriv Smart Trading Gateway.app",
    icon=None,
    bundle_identifier="com.deriv.gateway.desktop",
    info_plist={
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "NSHighResolutionCapable": "True",
    },
)
