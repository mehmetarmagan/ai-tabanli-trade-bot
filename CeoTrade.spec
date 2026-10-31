# -*- mode: python ; coding: utf-8 -*-

datas = [('.env', '.'), ('core', 'core'), ('ui', 'ui')]
binaries = []
hiddenimports = [
    'core', 'ui', 'ui.main',
    'core.config', 'core.data_engine', 'core.indicators', 'core.strategy', 'core.risk_manager',
    'core.adapters', 'core.adapters.paper_adapter', 'core.adapters.futures_adapter',
    'core.adapters.security.mode_guard', 'core.execution_engine', 'core.database',
    'core.signal_aggregator', 'core.notifications'
]


a = Analysis(
    ['main.py'],
    pathex=['C:\\Ceo-Trade'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='CeoTrade',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
