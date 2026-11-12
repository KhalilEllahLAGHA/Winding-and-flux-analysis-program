# Winding and flux analysis program

A Python (PyQt5) desktop tool for three-phase electrical-machine design: it builds
the stator winding, computes tooth-based MMF profiles, generates a polar mesh, and
solves the airgap/iron flux density through a reluctance network — with FEMM
finite-element validation of the results. Winding feasibility and factors, MMF
curves, and flux-density heatmaps / flux-line plots are all interactive.

## Run

```bash
python main.py
```

Dependencies: PyQt5, numpy, scipy, pandas, matplotlib, openpyxl,
pyqtgraph (optional, for animation playback), pyfemm + FEMM (optional,
for FEMM validation and the standalone tools).

## MMF curves

The default **Instantaneous phases** view applies the configured electrical angle
Wt to each phase. Enable **Resultant** to display their sum. **Peak phase
references** shows each phase at peak current for comparing winding shapes.
The current parameter I is a peak value. Double-layer windings use I/2 in each
layer, and N multiplies each occupied coil-side current.

The connection matrix uses signed electrical phase belts and opposite-current
coil returns at the selected span. Incompatible uniform-span windings display
an explanation. Slot transitions include their exact breakpoints and the curves
close at 360 degrees. Custom slot width is retained when switching tabs.

## Field display

**Solve field** opens the density map with magnetic flux contours. Select a
display mode above the plot and choose 4–100 contour levels. The view refreshes
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

Generate a mesh in **Flux Viewer → Step 2**, then click **Validation using FEMM**
in Step 3. The button recalculates the local model automatically, builds FEMM
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

Regression checks (no FEMM installation required):

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

The 12 November 2026 physics audit corrected field reconstruction, coil returns,
slot indexing and distributed winding sources. The default mid-mesh peak radial
B difference is now about 0.067%. Signed curve comparisons retain the remaining
local discretization errors. See [the audit](femm_validation/physics-audit.md)
for equations, mesh convergence, measured residuals and reproduction commands.

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
  flux_solver.py            Sparse PCG flux solver (cached system matrix)
  femm_validation.py        Active-model Lua generation and matched metrics
  femm_runner.py            Isolated FEMM execution, timeout and result parsing
  flux_contours.py          Conservative planar vector potential for flux lines
ui/                         Qt widgets and pages
  theme.py                  Shared dark-theme stylesheets (deduplicated)
  winding_tab.py            Tab 1: winding simulator
  stator_drawing.py         Stator winding drawing widget
  mmf_tab.py                Tab 2: MMF curves + matrix dialog + animation
  flux_viewer_tab.py        Tab 3 container: 3-step flow + navigation
  motor_drawing_page.py     Step 1: machine parameters
  meshing_page.py           Step 2: mesh settings/generation/export
  flux_density_page.py      Step 3: flux solve, visualisation, FEMM check
  machine_drawer.py         Matplotlib machine cross-section
  flux_visualization.py     Heatmap / flux-line / combined renderers
utils/
  constants.py              All shared defaults and presets
  paths.py                  Project paths (femm_validation locations)
  safe_eval.py              Safe arithmetic parsing of input fields
tools/                      FEMM tools and the app's validation worker
  femm_drawing.py           Shared FEMM geometry helpers
  flux_run.py               Winding simulation driven by an Excel matrix
  validation_a_vide.py      No-load validation model
  femm_check.py             Background validation worker (--script, --results)
femm_validation/            Shared Lua 4 template, old model and per-run artifacts
```
