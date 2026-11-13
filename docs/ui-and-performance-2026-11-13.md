# Local Qt6 interface and performance update

The app uses PyQt6 6.12, installed in its virtual environment. Compact top
navigation and Hide/Show settings leave more room for the study/results view.
Inputs display total poles, including four poles in the default model. The theme
uses dark neutral surfaces, white plot canvases and coloured action/progress/step
accents.

## Animation

The fixed-permeability linear model uses two checked signed field solutions at
0 and 90 electrical degrees. Signed Br, Btheta and Az are combined before
calculating magnitude or contours. Preparation runs in a cancellable background
thread. Live PyQtGraph playback uses fixed cycle colour limits and elapsed time,
and stores no per-angle image or field dictionaries. Model edits invalidate the
cache. The electrical period is independent of pole count; |B| and undirected
contours repeat after 180 electrical degrees.

For 8,640 cells, the old combined generator took 6.278 s for twelve samples and
stored 22,394,880 image bytes plus field dictionaries. The final source check
prepared continuous playback in 0.390 s using 4,320,657 bytes of model arrays.
Across 120 combined updates, mean frame time was 12.87 ms and p95 was 13.87 ms.
These are local measurements, not a fixed performance guarantee.

## Solutions

The GUI selects cached sparse LU for up to 100,000 cells with the original PCG
fallback. Source-balance and full-network residual acceptance are unchanged.
Excitation edits reuse reluctances, sparse assembly and factorisation. Geometry,
material or axial-length edits rebuild them. Reluctance and conductance formulas
are vectorised. Static heatmaps use bulk polar polygons with at most one-degree
arc subdivisions instead of one Matplotlib Wedge per cell; this changes display
tessellation only.

The original cold 64,800-cell calculation took 3.648 s. The optimised calculation
took 1.748 s; thirteen subsequent angle solves averaged 0.430 s. These timings
exclude plot rendering. Reproduce with `tools/benchmark_solver.py OUTPUT.json`.

## Verification and executable

- All 121 tests passed.
- 39 angle checks passed across 1,008-, 8,640- and 64,800-cell meshes, including
  113 degrees. Full relative residuals remained below 1e-5.
- Source workflow/render checks passed at 1440×960 and 1200×760, including full
  width results, all animation modes, background preparation and cache reuse.
- The single-file windowed build is `dist/WindingFlux.exe`, 108,887,320 bytes.
  Python, Qt6 and numerical dependencies are included. Bundled icon/control
  assets and the FEMM template match source bytes. No Qt5 runtime is present.
- SHA-256: `108449b6e2a8d837e847eddc0c1994f4b90b3cba43e0a8e661f02c160d4bf333`.

Windows application control refused to start the unsigned executable with
WinError 4551. Consequently, its packaged self-test could not execute; successful
native executable launch is not claimed. Security policy and certificate trust
were not changed. Deployment must be approved by the applicable policy or use
an approved code-signing process.

Private evidence remains under the workspace's `tmp/winding-ui-redesign/`:
source screenshots, solver sweep, profiles and bundle-verification JSON. Source
and portfolio publication were not performed.
