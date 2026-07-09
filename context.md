# Project Context & Work Summary

**Application:** Three Phase Winding Simulator — a PyQt5 + matplotlib desktop
app for electric-machine winding design and magnetic flux analysis.

**Stack:** Python 3.13, PyQt5, matplotlib, NumPy, SciPy (sparse CG solver),
optional pyqtgraph (animation playback) and FEMM (validation).

**Entry point:** `python main.py`

---

## 1. Architecture at a glance

Three top-level tabs hosted by `MainWindow` ([main.py](main.py)):

| Tab | Module | Purpose |
|-----|--------|---------|
| Winding Simulator | [ui/winding_tab.py](ui/winding_tab.py) | Slot/pole/coil config, feasibility, stator drawing |
| MMF Curves | [ui/mmf_tab.py](ui/mmf_tab.py) | Per-phase + resultant MMF plots, connection matrix, Wt animation |
| Flux Viewer | [ui/flux_viewer_tab.py](ui/flux_viewer_tab.py) | 3-step wizard: Motor Drawing → Meshing → Flux Density |

The tabs share state through widgets attached to the main window so slot/pole
counts and slot-arc angle stay synchronized across tabs.

**Compute pipeline (Flux Viewer Step 3):**
mesh ([core/meshing_engine.py](core/meshing_engine.py)) → reluctance network
([core/reluctance_calculator.py](core/reluctance_calculator.py)) → teeth/slot
MMF mapping ([core/teeth_slot_mmf.py](core/teeth_slot_mmf.py)) → magnetic-circuit
solve ([core/flux_solver.py](core/flux_solver.py)) → visualization
([ui/flux_visualization.py](ui/flux_visualization.py)). MMF profiles come from
[core/mmf_engine.py](core/mmf_engine.py).

---

## 2. Bug fix — Flux Viewer motor preview never updated

**Symptom:** In the Flux Viewer's Step 1 (Machine Parameters), the motor
cross-section preview did not update when parameters changed.

**Root cause:** A PyQt5 lifetime trap. `MotorDrawingPageUI` was created as a
local variable in `setup_flux_viewer_tab` and never referenced afterward, so it
was garbage-collected. PyQt5 holds only **weak references to bound-method
slots**, so once the controller was collected, every `textChanged → redraw`
signal connection (plus slot-angle derivation and cross-tab sync) silently
died. The other two flux pages were unaffected because they already register
themselves on the main window.

**Fix:** The controller now registers itself as
`main_window.motor_drawing_page_ui` ([ui/motor_drawing_page.py](ui/motor_drawing_page.py)),
and the tab builder keeps all three page controllers in
`flux_page_controllers` ([ui/flux_viewer_tab.py](ui/flux_viewer_tab.py)) as a
safeguard. Verified: editing slot count now redraws live, re-derives the slot
angle, and syncs the winding tab.

---

## 3. UI/UX redesign

A consistent design system was introduced in [ui/theme.py](ui/theme.py)
(color tokens, typography scale, spacing, radii, and hover/focus/pressed/
disabled states for every widget), plus helpers: `set_status()` for
color-coded feedback, `badge_style()` for status chips, and step-indicator
styles.

- **Flux Viewer wizard:** numbered step-indicator header (badges turn into
  green checkmarks; connector lines light up with progress), a contextual hint
  bar (e.g. amber "Generate a mesh to unlock the next step", green "Mesh
  ready"), and an accent primary "Next" button. Mesh-gating logic unchanged.
- **Step pages:** titles/subtitles, tooltips on every input, primary action
  buttons (Generate Mesh, Calculate), and color-coded statuses everywhere
  (green success / red error / amber warning). Read-only monospace generation
  log.
- **Winding tab:** controls grouped into "Winding Configuration" and "Computed
  Properties" cards; feasibility shown as a green/red badge; hard-coded pixel
  widths replaced with minimums + stretch so the stator drawing scales with the
  window.
- **MMF tab:** the overloaded single control row (clipped below ~1700px) split
  into two rows — parameter groups on top, right-aligned actions below.
- `main.py` now applies the Fusion base style for consistent cross-platform
  rendering.

All redesign work preserved existing functionality (verified by an offscreen
UI smoke test covering navigation, mesh gating, and feasibility states).

---

## 4. CPU / performance optimizations

Profiling showed the flux pipeline's cost was dominated by **per-element Python
`dict` loops, not the numerical solve** (CG was only ~33 ms/frame), and that the
Wt-sweep animation re-did identical work every frame.

| Change | File(s) | Effect |
|--------|---------|--------|
| Vectorized branch fluxes, RHS, flux densities, statistics; COO matrix assembly (was ~43k `lil_matrix` inserts) | [core/flux_solver.py](core/flux_solver.py) | branch-flux step ~160 ms → ~7 ms/frame |
| `update_wt_angle` recomputes only the resultant (Wt doesn't change per-phase profiles) | [core/mmf_engine.py](core/mmf_engine.py) | Wt update 6.3 ms → 0.025 ms (~250×) |
| Cache element→tooth/slot layout + Wt-independent base tooth MMF; animation uses `build_full=False` / `include_statistics=False` | [core/teeth_slot_mmf.py](core/teeth_slot_mmf.py), [core/mmf_engine.py](core/mmf_engine.py) | animation compute ~370 ms → ~55 ms/frame |
| Persistent heatmap figure for animation (build patches/colorbar once, swap colors per frame); B-magnitude-only extractor | [ui/flux_visualization.py](ui/flux_visualization.py), [ui/flux_density_page.py](ui/flux_density_page.py) | render ~524 ms → ~350 ms/frame |
| Debounced MMF plot controls; resultant-MMF animation updates line data instead of clearing/rebuilding axis | [ui/mmf_tab.py](ui/mmf_tab.py) | no redraw flooding on spin/drag |

**Net result (8,640-element mesh):**

| Operation | Before | After |
|-----------|--------|-------|
| Animation frame (compute) | ~370 ms | ~55 ms |
| Animation frame (end-to-end incl. render) | ~894 ms | ~345 ms |
| Wt adjustment | 6.3 ms | 0.025 ms (~250×) |
| Full flux calculation | ~713 ms | ~500 ms |

The remaining animation cost is matplotlib rasterization at 220 DPI — inherent
to the output quality, left unchanged rather than silently lowering resolution.

**Load-bearing invariant:** the solver's vectorized fast path assumes MMF is
radial-only and symmetric (`MMF_up == MMF_down`, `MMF_left == MMF_right == 0`).
If tangential/asymmetric MMF sources are ever added, guard or remove the
`element_mmf_ud` fast path in `flux_solver._mmf_arrays()`.

---

## 5. Verification approach

- **Bit-for-bit numerical equivalence:** reference outputs (potentials, branch
  fluxes, densities, tooth/slot MMF, statistics, MMF profiles) were captured
  from the original code, then `np.allclose`-compared after every optimization.
  All 44 checks pass.
- **Pixel-identical renders:** animation heatmap frames compared against the
  original per-frame builder (mean pixel diff 0.000).
- **UI smoke test:** offscreen run exercising the live preview fix, wizard
  navigation, mesh gating/invalidation, real mesh generation, and feasibility
  badges — all pass.
- **End-to-end timing:** drove the real UI through generate-mesh →
  flux-calculate → visualization → animation pre-render.

Temporary profiling/verification scripts were removed after use; the app
constructs and runs cleanly.

> Headless testing note: on this machine the Qt `offscreen` platform has **no
> fonts** (text invisible in `grab()`). For screenshots use the native platform
> with `window.setAttribute(Qt.WA_DontShowOnScreen, True)`; logic-only tests run
> fine under `offscreen`.

---

## 6. Files changed

**Core (compute):**
- `core/flux_solver.py` — vectorized result computation, cached index/geometry
  arrays, COO matrix build, `element_mmf_ud` fast path, `include_statistics`.
- `core/mmf_engine.py` — resultant-only Wt update, cached base tooth MMF.
- `core/teeth_slot_mmf.py` — cached layout + machine params, vectorized
  per-element MMF, `build_full` flag, removed dead per-element code.

**UI:**
- `ui/theme.py` — full design-system rewrite (tokens, states, helpers).
- `ui/flux_viewer_tab.py` — wizard step indicator, contextual hints, controller
  references (bug fix).
- `ui/motor_drawing_page.py` — self-registration (bug fix), layout polish,
  tooltips.
- `ui/meshing_page.py` — color-coded status, primary action button, polish.
- `ui/flux_density_page.py` — color-coded status, persistent heatmap animation
  renderer, animation fast-path wiring.
- `ui/flux_visualization.py` — `setup_heatmap_animation`, B-magnitude-only
  extractor.
- `ui/mmf_tab.py` — debounced replot, efficient resultant-animation redraw,
  two-row control layout.
- `ui/winding_tab.py` — grouped cards, feasibility badge, responsive layout.
- `main.py` — Fusion base style.

**Docs:** `README.md` — "Notable fixes" + "CPU / performance optimizations"
sections.
