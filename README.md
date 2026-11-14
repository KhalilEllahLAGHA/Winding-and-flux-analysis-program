# Winding and flux analysis program

A PyQt6 desktop application for multiphase electrical-machine winding design
and magnetic-field analysis. It generates signed coil connections, calculates
magnetomotive force (MMF), builds a polar reluctance network and displays flux
density and magnetic flux contours.

## Run from source

From the project directory on Windows:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe main.py
```

The main dependencies are PyQt6, NumPy, SciPy, pandas, Matplotlib, OpenPyXL and
PyQtGraph. FEMM is an optional separate installation for reference comparisons.
The application can run without FEMM.

## Workflow

| Stage | Purpose | Shortcut |
|---|---|---|
| Winding layout | Set phases, slots, total poles, coil span and layers | Ctrl+1 |
| MMF curves | Inspect phase/resultant MMF and the connection matrix | Ctrl+2 |
| Machine geometry | Set dimensions and preview the cross-section | Ctrl+3 |
| Mesh | Generate and inspect the polar mesh | Ctrl+4 |
| Field analysis | Solve, inspect, export, animate and compare with FEMM | Ctrl+5 |

**Hide settings** expands the results; **Show settings** restores the controls.
Field analysis becomes available after mesh generation. Geometry changes clear
the mesh and require it to be generated again.

## Winding and excitation conventions

- Select 1-26 phases, identified as A-Z, and an even total pole count.
- Coil span is measured in slots. Single-layer windings require an odd span;
  an even entry is reduced by one, following the upstream generator.
- Odd phase counts use phase-current spacing of 360/m degrees; even counts
  use 180/m degrees, where m is the number of phases.
- The configured current is a peak value. In this model, double-layer excitation
  assigns I/2 to each layer; N is the coil-side turn multiplier.
- The drawing, MMF and field calculations use the same physical connection
  matrix with explicit phase/layer metadata. Invalid or incomplete layouts
  display an explanation instead of silently changing the requested layers.

The default MMF view shows instantaneous phase contributions at the selected
angle Wt. **Resultant** adds their sum; **Peak phase references** compares phase
winding functions at peak current. In the field view, click a solved cell to
inspect Br, Btheta and |B| in tesla, or use the plot toolbar to pan and zoom.

## Solutions and animation

The solver reuses a cached sparse LU factorisation for networks up to 100,000
cells, with checked PCG fallback. Excitation changes reuse the network;
geometry, material or axial-length changes rebuild it. Accepted solutions pass
a full-network residual check.

In **Field analysis -> Animation**, select a display mode and click
**Prepare animation**. Preparation runs in a cancellable background worker.
Two signed reference solutions preserve all phase currents and provide the
continuous field at arbitrary electrical angles. The app combines signed
components before calculating magnitude and vector-potential contours, with a
fixed density colour scale over the cycle.

A signed electrical cycle is 360 degrees, independently of pole count. The
magnitude and undirected contours repeat after 180 degrees. Pole count sets
the intended spatial winding order, not the number of electrical phases.

The model is a 2D cross-section with prescribed permeabilities. It does not
calculate saturation, losses or efficiency. Physical accuracy depends on
geometry, materials and mesh resolution, separately from the solver residual.

## Optional FEMM comparison

Generate the mesh, then choose **Validate in FEMM** in the field-analysis stage.
The app builds a reference model from the active winding, currents, geometry,
materials and axial length, and compares air-gap radial induction and sector
flux on a common sample ring.

On Windows, the app searches common FEMM locations and PATH. Set `FEMM_EXE` if
FEMM is installed elsewhere. Native execution does not require pyfemm; the
optional pyfemm/COM bridge is a fallback. Validation runs in a background process
and leaves the solved FEMM window open for inspection.

Source runs save validation output under `femm_validation/runs/`. A standalone
build uses `%LOCALAPPDATA%/WindingFlux/femm_validation/runs/`. The required Lua
template is `femm_validation/run_validation.lua`; generated models and solutions
are created per run.

## Build the Windows application

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
.venv/Scripts/python.exe -m PyInstaller --noconfirm WindingFlux.spec
```

After building, open `dist/WindingFlux.exe`. This single-file, windowed build
includes Python, Qt6 and the numerical dependencies. FEMM remains a separate
optional installation.

## Developer checks

```powershell
.venv/Scripts/python.exe main.py --self-test build/source-check
dist/WindingFlux.exe --self-test build/exe-check
.venv/Scripts/python.exe tools/benchmark_solver.py build/solver-benchmark.json
```

The self-test exercises navigation, mesh generation, field solving, animation,
cache reuse and mesh invalidation. Its screenshots and results are written to
the specified output directory. The benchmark checks cold/repeated solves and
full-network residuals across the mesh presets.

## Source layout

```text
main.py                    Application entry point and stage navigation
core/                      Winding, MMF, mesh, field and FEMM calculation engines
ui/                        Qt pages, stator drawing and field visualisation
ui/assets/                 Required application icon and control graphics
utils/                     Defaults, phase conventions, paths and input parsing
tools/                     Application workers and developer utilities
femm_validation/
  run_validation.lua       Required FEMM model-building template
third_party/dolomites/     Pinned upstream generator, licence and attribution
requirements.txt           Application dependencies
requirements-build.txt     Windows packaging dependencies
WindingFlux.spec           PyInstaller build configuration
```

## Credits and upstream licence

The winding generator integrates Luigi Alberti and contributors' GPLv3
[Dolomites / Koil module](https://gitlab.com/LuigiAlberti/dolomites-python), pinned
to revision `21eceabcdf09ecd0873b693cfa123b3567d6f62b`. The application adapter
corrects periodic sector boundary/wrap handling and validates physical occupancy
and phase balance. The unmodified upstream module, complete
[licence](third_party/dolomites/LICENSE) and
[notice](third_party/dolomites/NOTICE.md) are retained in the source.

Method reference: L. Alberti, *Koil: A Tool to Design the Winding of Rotating
Electric Machinery*, ICEM 2018, pp. 805-811,
[DOI: 10.1109/ICELMACH.2018.8507004](https://doi.org/10.1109/ICELMACH.2018.8507004).
