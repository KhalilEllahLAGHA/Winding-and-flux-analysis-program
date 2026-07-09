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
tools/                      Standalone FEMM scripts (not used by the app)
  femm_drawing.py           Shared FEMM geometry helpers
  flux_run.py               Winding simulation driven by an Excel matrix
  validation_a_vide.py      No-load validation model
  femm_check.py             Smoke-test for the validation Lua script
femm_validation/            FEMM model + Lua validation script (data)
```
