# Project guide

The application is a PyQt5 desktop tool for three-phase winding design and
magnetic-field analysis. Start it with `python main.py`; see [README.md](README.md)
for dependencies, controls and acknowledgements.

## Structure

| Workspace | Entry module | Purpose |
|---|---|---|
| Winding Simulator | `ui/winding_tab.py` | Winding parameters, feasibility and stator drawing |
| MMF Curves | `ui/mmf_tab.py` | Phase and resultant MMF, connection matrix and angle animation |
| Flux Viewer | `ui/flux_viewer_tab.py` | Machine geometry, polar mesh, field solution and FEMM comparison |

Calculation engines live in `core/`, widgets in `ui/`, and shared defaults and
input helpers in `utils/`. The main window retains the three Flux Viewer page
controllers so their signal connections remain active.

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

Run the regression suite with:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

The [physics audit](femm_validation/physics-audit.md) documents the field
equations, winding-source conventions, FEMM comparisons and mesh-convergence
results. Validation runs retain their models, solutions and metrics under
`femm_validation/runs/`. The app leaves FEMM open for inspection after a
comparison.
