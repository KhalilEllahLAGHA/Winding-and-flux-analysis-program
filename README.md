# Winding and flux analysis

Python/PyQt6 application for winding design, MMF and magnetic flux simulation.

## Run

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe main.py
```

## Build the Windows app

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
.venv/Scripts/python.exe -m PyInstaller WindingFlux.spec
```

The executable is `dist/WindingFlux.exe`. FEMM is optional.

Winding generator: [Dolomites/Koil](https://gitlab.com/LuigiAlberti/dolomites-python),
Luigi Alberti and contributors, GPLv3. See [licence](third_party/dolomites/LICENSE).
Reference: [Koil, ICEM 2018](https://doi.org/10.1109/ICELMACH.2018.8507004).
