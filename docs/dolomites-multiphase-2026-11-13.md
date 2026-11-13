# Dolomites generator and multiphase controls — 13 November 2026

The winding generator now uses the actual Dolomites/Koil Python module, pinned to
`21eceabcdf09ecd0873b693cfa123b3567d6f62b` from
<https://gitlab.com/LuigiAlberti/dolomites-python>. The unmodified module and GPLv3
licence/attribution are retained in `third_party/dolomites/`.

The adapter uses Koil's star of slots, feasibility rules and coil population.
Periodic half-open sector membership fixes the upstream Python implementation's
omitted boundary spokes and wrapped sectors. The adapter rejects incomplete slot
occupancy, unequal phase conductor counts, net coil-return imbalance and
unbalanced working-harmonic phase axes. It does not independently normalise
physical coil-side signs or silently change the requested layer count.

The new Phases control supports 1–26 phases. Selected phase/layer metadata is
explicit throughout the connection matrix, MMF, drawing, field calculation,
animation and FEMM export. Odd phase counts use 360/m degree current spacing;
even counts use 180/m. The app retains its sine excitation convention (a common
time-origin shift from Koil's default cosine). Controls show total poles; only
the call into Koil uses pole pairs. Single-layer spans are odd, reducing even
entries by one as in upstream.

The detailed winding description panel has been removed. Dynamic phase legends
wrap, and MMF phase selectors scroll. Export filenames include the winding's
phase information and total pole count.

Fractional default slot half-pitches retain eight decimal places. The mesher
recognises equal slot/tooth arcs without fixed-point GCD rounding creating an
excessive mesh. Requests exceeding one million cells fail before allocation.
Two-slot single-phase machines are also supported consistently across stages.

## Verification

- All 131 unit/regression tests passed. Tests compare odd-phase coil matrices
  directly with the pinned, unmodified upstream generator, check even-phase
  boundary/wrap cases, and verify independent slot currents and tooth-MMF jumps.
- The explicit six-phase single-layer case remains six-phase when recalculated;
  it is not inferred to be three-phase double-layer from its six rows.
- A five-phase continuous-animation field agrees with an independent full solve
  at 113 electrical degrees within the stated test tolerances.
- `tools/check_multiphase.py` exercised the real Qt controls, winding/MMF views,
  coarse mesh, field solve and slot-current conservation for 1, 2, 3, 4, 5, 6,
  9, 13 and 26 phases. All ten configurations (including two single-phase slot
  counts) passed with relative algebraic residual below 1e-14.
- Source self-test passed with 8,640 cells, ten desktop/minimum-size screenshots,
  no clipped buttons, animation preparation in a responsive worker and cache
  reuse. On this run preparation took 0.437 s; 120 live combined frames averaged
  14.90 ms (p95 19.19 ms). These are local timings, not performance guarantees.

Evidence is under the workspace's `tmp/winding-dolomites/`. Changes are local;
no source repository or portfolio publication was performed.

## Executable

`dist/WindingFlux.exe` was rebuilt with PyInstaller and is 108,919,007 bytes.
SHA-256: `3f390d9349f6829db8d232c8928983eb9c355ccfb8932c21be810da126898fd2`.
Archive verification confirmed the new Dolomites, connection-matrix and phase
modules; bundled GPL licence/notice and FEMM template match source bytes. Qt6 is
present and Qt5 is absent.

The rebuilt executable launched successfully and its self-test exited 0 with
`frozen=true`: an 8,640-cell field solve, desktop/minimum-size renders without
clipped buttons, all animation display modes, background responsiveness and cache
reuse passed. Packaged animation preparation took 0.392 s; 120 combined frame
updates averaged 13.54 ms (p95 14.56 ms) on this run. The earlier build's Windows
Application Control launch block did not recur. No security/trust policy was
changed.
