# Project guide

The application is a PyQt6 desktop tool for multiphase winding design and
magnetic-field analysis. Start it with `python main.py`; see [README.md](README.md)
for dependencies, controls and acknowledgements.

## Structure

| Workspace | Entry module | Purpose |
|---|---|---|
| Winding layout | `ui/winding_tab.py` | Winding parameters, feasibility and stator drawing |
| MMF Curves | `ui/mmf_tab.py` | Phase and resultant MMF, connection matrix and angle animation |
| Machine geometry | `ui/motor_drawing_page.py` | Dimensions and cross-section preview |
| Mesh | `ui/meshing_page.py` | Polar mesh generation and export |
| Field analysis | `ui/flux_density_page.py` | Field solution and FEMM comparison |

Calculation engines live in `core/`, widgets in `ui/`, and shared defaults and
input helpers in `utils/`. The main window retains the three Flux Viewer page
controllers so their signal connections remain active.

The five stages share compact top navigation in `main.py`. Ctrl+1–5 opens stages
directly. A Hide/Show settings action expands the results. Inputs use total
poles (4 by default), not pole pairs. Field analysis requires a generated
mesh, and geometry invalidation relocks it. The palette uses dark neutral
greys/black, light text, coloured action/step/progress accents and white plot/image
canvases. Data colours remain in phase curves and flux-density maps. All Qt imports and Matplotlib Qt backends
use Qt6, including the standalone auxiliary tools.

Winding generation uses the vendored Dolomites/Koil Python module at revision
`21eceabcdf09ecd0873b693cfa123b3567d6f62b` with GPLv3 attribution/licence. The
adapter fixes periodic sector boundary/wrap omissions and rejects incomplete or
unbalanced layouts. The Phases control supports 1–26 phases. Explicit phase and
layer metadata follows the matrix into MMF, field calculations, animation and
FEMM; do not infer a six-row winding is three-phase double-layer when metadata
says six-phase single-layer. Current offsets are 360/m for odd m, 180/m for even m.
Single-layer throw is odd, with even values reduced by one. The detailed winding
description panel is removed. Fractional half-slot-pitch defaults keep eight
decimal places and use a stable two-sectors-per-pitch mesh base; excessive meshes
are rejected before allocation. `tools/check_multiphase.py` renders and solves
representative odd/even phase configurations through the real Qt controls.

Build the standalone Windows app with `WindingFlux.spec`; see README.md.
`dist/WindingFlux.exe` includes its Python/Qt runtime. Its FEMM worker launches
the same executable in worker mode and returns a JSON file because windowed
executables have no Python standard output. Validation templates stay bundled;
run evidence persists in `%LOCALAPPDATA%/WindingFlux/femm_validation/runs/`.
These changes are local until separately published.

The current Dolomites build (108,919,007 bytes) launched and passed its packaged
self-test with an 8,640-cell solve, live animation and desktop/minimum-size
renders. All 131 tests and ten multiphase GUI/field configurations passed. See
`docs/dolomites-multiphase-2026-11-13.md` for source revision, build hash and
verification details. The earlier executable's Windows launch block did not
recur; security/trust policy was not changed.

The GUI uses cached sparse LU for up to 100,000 cells, with the original checked
PCG fallback. Full-network residual acceptance is unchanged. Reluctances and
network assembly are vectorised; repeated excitation solves reuse the same
network, while geometry/material/length edits invalidate it. Static heatmaps use
bulk polar polygons with arcs subdivided to at most one degree, rather than one
Matplotlib Wedge object per cell. This changes display tessellation only.

Animation preparation runs in a cancellable Qt thread using snapshots of inputs.
Two checked solves yield the sine/cosine signed field and Az basis. Magnitude and
equal-Az contours are computed live in PyQtGraph, with fixed cycle colour limits
and elapsed-time playback. The electrical period is 360 degrees independently of
pole count; |B| and undirected contours have a 180-degree repeat. Cached animation
data is invalidated by model edits. `tools/benchmark_solver.py` and
`tools/ui_smoke_test.py` reproduce solver and interactive rendering checks.

## Calculation path

1. Build the signed coil-side connection matrix in `core/connection_matrix.py`.
2. Compute the phase and resultant MMF in `core/mmf_engine.py`. The current
   input is a peak value; double-layer windings assign I/2 to each layer.
3. Generate the polar mesh and reluctances, then map the distributed winding
   sources to cells with `core/teeth_slot_mmf.py`.
4. Solve the magnetic network in `core/flux_solver.py`, checking the full-system
   residual before accepting the result.
5. Reconstruct flux density and vector potential; `ui/flux_visualization.py`
   displays density maps and equally spaced flux contours.

The model is a 2D cross-section with prescribed permeabilities. It does not
calculate saturation. Flux-density accuracy depends on the mesh and must be
assessed separately from the algebraic solver residual.

## Verification

The [physics audit](femm_validation/physics-audit.md) documents the field
equations, winding-source conventions, FEMM comparisons and mesh-convergence
results. Validation runs retain their models, solutions and metrics under
`femm_validation/runs/`. The app leaves FEMM open for inspection after a
comparison.
