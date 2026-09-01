# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['f1_app.py'],
    pathex=[],
    binaries=[],
    datas=[('tracks', 'tracks'), ('web', 'web'), ('assets\\brendon_leigh_setups_v1_5.json', 'assets'), ('assets\\race_command_icon_v2.ico', 'assets'), ('assets\\race_command_icon_v2.png', 'assets')],
    hiddenimports=['f1_26_split_telemetry', 'f1_report', 'f1_compare', 'f1_championship', 'f1_race_report', 'f1_solo_report', 'f1_engineer', 'f1_track_data', 'f1_database', 'f1_session_studio', 'f1_strategy', 'f1_strategy_lab', 'f1_live_strategy', 'f1_race_control', 'f1_driver_learning', 'f1_community_reference', 'f1_setup_packages', 'f1_web_app', 'webview', 'f1_prerace', 'f1_setup_library', 'f1_theme', 'f1_ui', 'f1_ai_engineer', 'openpyxl', 'matplotlib.backends.backend_agg'],
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
    name='F1TelemetryHub',
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
    icon=['assets\\race_command_icon_v2.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='F1TelemetryHub',
)
