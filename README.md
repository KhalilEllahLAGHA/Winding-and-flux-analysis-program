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

## Notable fixes versus the original

- The Flux Viewer Step 1 motor preview never updated when parameters
  changed: the `MotorDrawingPageUI` controller was created as a local
  variable and garbage collected, and PyQt5 only holds weak references
  to bound-method slots, so every `textChanged` connection silently
  died. The controller now registers itself on the main window
  (`motor_drawing_page_ui`), like the other flux pages already did.
- `Meshing_Page_UI.py` defined `update_mesh_visualization` twice; the
  duplicate silently disabled mesh invalidation on parameter changes.
  Changing machine parameters now correctly clears stale mesh data.
- The resultant-MMF animation permanently overwrote the configured Wt
  angle; it now computes frames without mutating engine state.
- `eval()` on user input fields replaced with a safe arithmetic parser.
- `_tmp_femm_check.py` pointed at a hard-coded path outside the project.
- Dead code removed (unused placeholder widgets, unreached methods,
  superseded resultant formula, vector-field plot with no UI entry).

## CPU / performance optimizations

Profiling showed the flux pipeline's cost was dominated by per-element
Python dict loops, not the numerical solve, and that the Wt-sweep animation
re-did large amounts of identical work every frame. All changes below were
verified to produce **bit-for-bit identical numerical output** and
**pixel-identical render output** against the pre-optimization reference.
Reference figures are for the default machine at the *Mid Precision* preset
(8,640 mesh elements).

- **Vectorised the flux solver** (`core/flux_solver.py`). Branch fluxes, the
  MMF RHS vector, flux densities, and the flux statistics were per-element
  Python loops doing ~2.8M `dict.get` calls per 12 frames. They are now NumPy
  gathers over per-direction neighbour-index / conductance arrays cached with
  the system matrix. The system matrix is also assembled in one COO build
  instead of ~43k `lil_matrix` insertions. *Branch-flux step ≈ 160 ms → ≈ 7 ms
  per frame; one full interactive calculate ≈ 713 ms → ≈ 500 ms.*
- **Wt updates recompute only the resultant** (`core/mmf_engine.py`). The
  electrical angle Wt only scales the `A·sin + B·sin + C·sin` combination, so
  `update_wt_angle` no longer rebuilds the per-phase continuous profiles.
  *≈ 250× faster Wt spin / animation stepping (6.3 ms → 0.025 ms per update).*
- **Cached the teeth/slot MMF layout** (`core/teeth_slot_mmf.py`). The
  element→tooth/slot classification and the Wt-independent per-phase tooth MMF
  are computed once per geometry and reused; each frame only does a vectorised
  gather. The animation also skips assembling the full per-element MMF dict
  list (`build_full=False`) and the unused per-frame statistics
  (`include_statistics=False`). *Animation compute ≈ 370 ms → ≈ 55 ms/frame.*
- **Persistent heatmap figure for animation** (`ui/flux_visualization.py`,
  `ui/flux_density_page.py`). Animation frames rebuilt ~8,640 wedge paths, the
  data limits, and the colorbar every frame. The heatmap mode now builds the
  patch collection and colorbar once and only swaps the colour array per
  frame; a B-magnitude-only extractor skips Bx/By trig the heatmap discards.
  *Heatmap frame render ≈ 524 ms → ≈ 350 ms; end-to-end frame ≈ 894 ms →
  ≈ 345 ms.*
- **Debounced high-frequency UI events** (`ui/mmf_tab.py`). MMF plot controls
  (turns, current, Wt, slot arc, line width, phase toggles) coalesce bursts of
  changes into a single matplotlib redraw, and the resultant-MMF animation
  updates the existing line's data each tick instead of clearing and rebuilding
  the whole axis at 20 fps.

Net effect: the Wt-sweep animation pre-render is ~2.6× faster end-to-end with
the compute portion ~6× faster, interactive Wt adjustment is effectively
instant, and a full flux calculation is ~1.4× faster — all with unchanged
results and visuals.
