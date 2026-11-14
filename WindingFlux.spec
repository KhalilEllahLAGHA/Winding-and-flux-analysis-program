# Rebuild with: .venv/Scripts/python.exe -m PyInstaller --noconfirm WindingFlux.spec
from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'femm_validation' / 'run_validation.lua'), 'femm_validation'),
           (str(root / 'ui' / 'assets'), 'ui/assets')],
    hiddenimports=['openpyxl', 'femm', 'win32com.client'],
    hookspath=[],
    hooksconfig={'matplotlib': {'backends': ['QtAgg', 'Agg']}},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide2', 'PySide6', 'tkinter', 'IPython', 'notebook',
              'pytest', 'scipy.datasets', 'scipy.io.tests', 'pandas.tests'],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='WindingFlux',
    icon=str(root / 'ui' / 'assets' / 'app.ico'),
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
