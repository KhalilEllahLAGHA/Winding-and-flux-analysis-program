# Winding and flux analysis program

A Python (PyQt6) desktop tool for multiphase electrical-machine design: it builds
the stator winding, computes tooth-based MMF profiles, generates a polar mesh, and
solves the airgap/iron flux density through a reluctance network — with FEMM
finite-element validation of the results. Winding feasibility and factors, MMF
curves, and flux-density heatmaps / flux-line plots are all interactive.

## Run

On Windows, open `dist/WindingFlux.exe`. This single-file build includes Python,
Qt6 and the numerical libraries; Python does not need to be installed separately.

To run from source:

```bash
python -m pip install -r requirements.txt
python main.py
```

Dependencies: PyQt6, numpy, scipy, pandas, matplotlib, openpyxl,
pyqtgraph (optional, for animation playback), pyfemm + FEMM (optional,
for FEMM validation and the standalone tools).

## Workspace navigation

The dark interface uses black, grey and white as its main colours, with coloured
actions, progress and active steps. Compact top navigation leaves more room for
results. **Hide settings** expands the study view; **Show settings** restores the
controls. Drawings and plot canvases retain white backgrounds.

| Stage | Purpose | Shortcut |
|---|---|---|
| 01 Winding layout | Configure phases, slots, total poles, coil span and layers | Ctrl+1 |
| 02 MMF curves | Inspect phase/resultant MMF, excitation and connection matrix | Ctrl+2 |
| 03 Machine geometry | Edit dimensions and preview the cross-section | Ctrl+3 |
| 04 Mesh | Set resolution, generate and export the polar mesh | Ctrl+4 |
| 05 Field analysis | Solve, inspect, export, animate and validate the field | Ctrl+5 |

Field analysis unlocks after mesh generation and locks again when geometry changes clear the
mesh. Shared winding and excitation settings persist when navigating.

## Dolomites winding generator

**Winding layout → Phases** selects 1–26 phases (A–Z). The generator uses the
vendored [Dolomites / Koil source](https://gitlab.com/LuigiAlberti/dolomites-python),
pinned to revision `21eceabcdf09ecd0873b693cfa123b3567d6f62b`. It uses the
star-of-slots feasibility rules, phase sectors, coil throw and coil population.
Single-layer coils require an odd span; an even entry is reduced by one, as in
Dolomites. The application keeps total poles in its controls and converts them
to pole pairs only when calling Koil.

Odd phase counts use 360°/m phase-current spacing; even counts use 180°/m,
following Dolomites. An adapter fixes periodic sector wrap and boundary omissions
in the upstream Python membership check and rejects incomplete or unbalanced
layouts. The drawing, connection matrix, MMF, field solve, animation and FEMM
export share the same generated coils and explicit phase/layer metadata.

The winding sidebar contains controls and a compact feasibility check; the
detailed description panel has been removed. See
[third-party notices](third_party/dolomites/NOTICE.md) and the bundled GPLv3
[licence](third_party/dolomites/LICENSE).

## Fast solutions and animation

The interface automatically uses a cached sparse LU factorisation for networks
up to 100,000 cells, with checked PCG fallback for larger systems or factorisation
failure. Geometry/material changes rebuild the network. Excitation changes reuse
it. Both solvers must pass the full-network residual check before reporting a
solution. Reluctance evaluation, sparse assembly and plot geometry are batched.

In **Field analysis → Animation**, select a mode and click **Prepare animation**.
Preparation runs in the background and can be cancelled. Two checked field solves
provide signed cosine/sine basis fields for this fixed-permeability linear model.
Playback combines their signed components, then calculates |B| and conservative
Az contours live, without storing hundreds of full images or field dictionaries.
The colour scale stays fixed over the cycle. Unchanged inputs reuse the prepared
model; mesh, material or winding edits invalidate it.

The default playback interval is 16 ms. Playback follows elapsed time to avoid
accumulating timing drift. **Loop over 180° electrical** uses the true half-cycle
symmetry of |B| and undirected contours. A full electrical sweep is 360° regardless
of the number of poles; pole count controls the spatial winding, not that period.

## Detailed algorithm report and numerical studies

The [18-page report](docs/multiphase-report/winding-dolomites-multiphase-report.pdf)
by **LAGHA Khalil Ellah** explains the algorithm symbolically before three worked
double-layer studies. It includes phase/resultant MMF, flux contours and density
figures for each case, with Dolomites/Koil attribution and equations through the
field solver. The editable source is [report.md](docs/multiphase-report/report.md).

| Case | Phases | Slots | Total poles | Coil span | Working winding factor |
|---|---:|---:|---:|---:|---:|
| Default | 3 | 36 | 4 | 9 | 0.959795 |
| Two-phase | 2 | 24 | 4 | 6 | 0.910684 |
| Requested long throw | 5 | 45 | 8 | 11 | 0.068629 |

The exact five-phase case is balanced, but its 352-degree electrical coil span
nearly cancels the intended eight-pole MMF. A strong counter-rotating two-pole
subharmonic deforms the composite field. The report discusses possible torque
and loss consequences; this fixed-permeability model does not compute efficiency.
Different phase/slot counts at the same current setting are not an equal-power
or equal-copper comparison.

Two 12-second, 30-fps flux videos show the default and requested five-phase cases
on the [portfolio](https://khalilellahlagha.github.io/projects/winding-flux-analysis.html#flux-videos).
They combine signed solved field bases and keep a fixed density scale within each
video. Matrices, MMF/air-gap CSVs, harmonic metrics and verification data are in
[the numerical evidence folder](docs/multiphase-report/data/).

Reproduce the assets and report from the repository root:

```powershell
python -m pip install -r requirements.txt -r requirements-report.txt
python tools/generate_report_assets.py
python tools/build_algorithm_report.py
```

## Build the Windows executable

Run these commands from the project directory on Windows:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
.venv/Scripts/python.exe -m PyInstaller --noconfirm WindingFlux.spec
```

The output is `dist/WindingFlux.exe`, with a bundled icon and no console window.
FEMM itself remains an optional separate installation. In the standalone build,
validation runs are retained under `%LOCALAPPDATA%/WindingFlux/femm_validation/runs/`.
Source execution retains the repository-local validation path.

Verify source and packaged workflows with:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/python.exe main.py --self-test build/source-check
dist/WindingFlux.exe --self-test build/exe-check
```

The self-test generates and solves an 8,640-cell model, checks navigation and mesh
invalidation, and saves screenshots at 1440×960 and 1200×760 plus a JSON result.

## MMF curves

The default **Instantaneous phases** view applies the configured electrical angle
Wt to each phase. Enable **Resultant** to display their sum. **Peak phase
references** shows each phase at peak current for comparing winding shapes.
The current parameter I is a peak value. Double-layer windings use I/2 in each
layer, and N multiplies each occupied coil-side current.

The connection matrix uses Dolomites phase sectors and opposite-current
coil returns at the selected span. Incompatible uniform-span windings display
an explanation. Slot transitions include their exact breakpoints and the curves
close at 360 degrees. Custom slot width is retained when switching tabs.
Fractional default half-pitches retain eight decimal places internally so larger
phase/slot counts do not produce excessive meshes through angle rounding.

## Field display

**Solve field** opens the density map with magnetic flux contours. Select a
display mode above the plot and choose 4–100 contour levels (12 by default). The view refreshes
automatically. Click inside the machine to inspect the solved cell's Br,
Btheta and |B| in tesla. Pan and zoom use the plot toolbar.

Flux lines follow equally spaced contours of reconstructed planar vector
potential Az, the method described in the [FEMM manual, section 2.3.6](https://www.femm.info/doku/lib/exe/fetch.php?media=upload:documentation:manual.pdf).
The reconstruction fits the solved polar face fluxes with periodic angular
continuity and constant potential on the insulated shaft and outer boundary.
Each contour interval carries the same flux, shown below the solve controls.
Interpolation within polar cells preserves their integrated face fluxes.
Curve detail depends on mesh resolution, including near slot corners.

## FEMM comparison

Generate a mesh in **04 Mesh**, then click **Validate in FEMM**
in **05 Field analysis**. The button recalculates the local model automatically, builds FEMM
from the active winding connection matrix, current, electrical angle, turns,
geometry, permeabilities and axial length, and reports the differences in
air-gap radial B and radial sector flux. It uses one common sample ring and
sector area for both sets of aggregate metrics. This is a comparison without
an automatic acceptance tolerance; large differences require investigation.

On Windows the validator finds `C:\femm42\bin\femm.exe`, common install locations,
or `femm.exe` on PATH. Set `FEMM_EXE` for another installation. Native execution
does not require pyfemm; an isolated pyfemm/COM bridge is the fallback. The solve
runs in the background with a five-minute timeout and reports Lua errors.
Each run saves its generated Lua, model, solution, metrics and `comparison.txt`
under `femm_validation/runs/<run-id>/`, without overwriting older models.
If inputs change during a run, repeat the comparison for the new settings.

After an app validation, FEMM stays open on the solved field map with a colour
`|B|` legend and magnetic-flux contours. Its Lua console contains the four validation
metrics and the position, `Br`, `Btheta`, `Bx`, `By`, `|B|` and `Az` of the peak
air-gap `|Br|` sample. Click points in the map to inspect their field values
in the point-properties window. Close that FEMM window
when finished. Other FEMM windows remain independent. Command-line checks keep
their usual automatic-close behavior unless `--keep-open` is requested.
The console stays hidden initially so the field map and point readout remain
visible; open **View → Lua Console** to see the saved metrics.

The 12 November 2026 physics audit corrected field reconstruction, coil returns,
slot indexing and distributed winding sources. The default mid-mesh peak radial
B difference is now about 0.067%. Signed curve comparisons retain the remaining
local discretization errors. See [the audit](femm_validation/physics-audit.md)
for equations, mesh convergence, measured residuals and reproduction commands.

## Acknowledgements

The winding generator includes Luigi Alberti and contributors' GPLv3 Dolomites
Koil module; the pinned source and licence are retained under
`third_party/dolomites/`. Luigi Alberti’s article, [*Koil: A Tool to Design the Winding of Rotating
Electric Machinery*](https://doi.org/10.1109/ICELMACH.2018.8507004), ICEM 2018,
pp. 805–811, helped me understand the winding algorithm, particularly the
star-of-slots method and the assignment of coil sides to phases.

AI agents helped me refine the application and identify and fix bugs.

## Layout

```
main.py                     Entry point (MainWindow + logging setup)
core/                       Calculation engines (no Qt imports)
  winding_analysis.py       Feasibility, winding factors, report text
  connection_matrix.py      Phase/slot connection matrix builder
  mmf_engine.py             Tooth-based MMF profiles + resultant (NumPy)
  meshing_engine.py         4-region polar mesh generator
  reluctance_calculator.py  Per-element reluctance network values
  teeth_slot_mmf.py         Maps tooth MMF onto mesh elements
  flux_solver.py            Cached sparse LU / PCG with full residual checks
  field_animation.py        Two-solution continuous field/contour model
  femm_validation.py        Active-model Lua generation and matched metrics
  femm_runner.py            Isolated FEMM execution, timeout and result parsing
  flux_contours.py          Conservative planar vector potential for flux lines
ui/                         Qt widgets and pages
  theme.py                  Shared neutral dark theme and native Qt palette
  assets/                   Vector app mark and Windows icon
  winding_tab.py            Winding configuration and live preview
  stator_drawing.py         Stator winding drawing widget
  mmf_tab.py                MMF curves + matrix dialog + animation
  flux_viewer_tab.py        Linked geometry, mesh and field pages
  motor_drawing_page.py     Machine parameters
  meshing_page.py           Mesh settings/generation/export
  flux_density_page.py      Flux solve, visualisation, FEMM check
  machine_drawer.py         Matplotlib machine cross-section
  flux_visualization.py     Heatmap / flux-line / combined renderers
  field_animation.py        Background preparation and native live plot playback
utils/
  constants.py              All shared defaults and presets
  paths.py                  Project paths (femm_validation locations)
  safe_eval.py              Safe arithmetic parsing of input fields
tools/                      FEMM tools and the app's validation worker
  femm_drawing.py           Shared FEMM geometry helpers
  flux_run.py               Winding simulation driven by an Excel matrix
  validation_a_vide.py      No-load validation model
  femm_check.py             Background validation worker (--script, --results)
  ui_smoke_test.py          Source and standalone workflow/render checks
  benchmark_solver.py       Checked cold/repeated solve timing across mesh presets
  check_multiphase.py       Render and solve odd/even phase layouts through Qt controls
third_party/dolomites/       Pinned upstream Koil source, licence and attribution
WindingFlux.spec             Reproducible single-file Windows build
femm_validation/            Shared Lua 4 template, old model and per-run artifacts
```
