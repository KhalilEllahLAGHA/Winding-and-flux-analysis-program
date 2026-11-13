# Magnetic model audit, 12 November 2026

The original default comparison gave a network peak radial field of 4.237036 T
and a FEMM value of 2.119936 T on the middle air-gap sample ring. The numerical
implementation contained several errors. The corrections below have been made.

## Field reconstruction and circuit solution

Branch fluxes are signed outwards from each cell. Opposite faces measure the
same field and must be averaged. With axial length L and angular width dtheta,

    Br = (Phi_up - Phi_down) / (2 * r_center * dtheta * L)
    Btheta = (Phi_right - Phi_left) / (2 * r_center * log(rout/rin) * L)

The previous equations doubled both components and reversed Btheta. The angular
area expression evaluates the centre value of a field proportional to 1/r,
consistent with the polar reluctance integral. Radial half-reluctances now use
the actual arithmetic node radius. The sparse Laplacian has one potential
reference fixed, and each solve checks its full residual and source balance.

On 13 November 2026, a reduced-system stopping mismatch was corrected. For n
nodes and balanced sources, the omitted reference residual is the negative sum
of the reduced residuals, so the full residual norm can be sqrt(n) larger.
When CG reports success but the full check fails, the solver warm-restarts
from the current potentials with a tighter absolute target derived from this
bound, then checks the full residual again. Refinement is bounded to two retries.
The existing full-system acceptance limit remains in force. The medium mesh at
Wt = 113 degrees now completes after one retry, reducing the full relative
residual from 1.358e-5 to 5.301e-8.

## Winding and current-source placement

- The return side of each double-layer coil now has the opposite sign in the
  slot displaced by its coil span. Independent sign normalization of each
  layer produced incorrect excitation for several spans.
- The default span is 36/4 = 9 slots for four poles. The previous division by
  two pole pairs gave 18 slots. With correct return signs, the 18-slot case
  cancels its slot excitation, as confirmed by both solvers.
- Physical slot count comes from machine parameters. It is independent of the
  number of mesh cells. Each tooth precedes its corresponding slot, and the
  winding function rises by that slot's signed ampere-turns across the slot.
- The winding function F is constant in a tooth and linear through a slot.
  Inside the slot/tooth radial band the impressed field is
  H_imp,r = -2 r F(theta)/(Rslot_outer^2 - Rslot_inner^2).
  Its curl gives the same uniform axial slot current density used in FEMM.
  Separate inner and outer half-cell integrals use their squared-radius
  differences. Their sum is independent of radial layer count.
- Complete phases must close. Net current in one layer may return through the
  other layer. Layer plots show periodic spatial components whose sum preserves
  the complete winding function.

The field-line display reconstructs planar vector potential Az from the solved
face fluxes. With psi = L Az, outward radial flux is its angular difference,
and positive-theta flux is its negative radial difference. A least-squares fit
uses every shared face, closes the angular seam and preserves constant potential
on the insulated inner and outer boundaries. Equally spaced Az contours carry
equal flux, following FEMM's planar display principle. Piecewise interpolation
in theta and log(r) preserves the integrated face fluxes. The underlying field
resolution remains set by the reluctance-network mesh.

## Comparison checks

The checked default case uses 36 slots, four poles, a nine-slot span, 204 turns,
2.8 A peak phase-current setting, Wt = 90 degrees, a 1 mm air gap, 110 mm axial
length and prescribed relative iron permeability 4000. Both models are linear
and use zero normal flux at the shaft and outer-yoke boundaries. Both winding
layers use the application's equal-current split and homogenized slot current.

The comparison now exports signed Br and Btheta at identical radii and angles.
It reports normalized L2 curve errors in addition to peak errors. Mean absolute
values include every sampled point, avoiding different zero-exclusion masks.
Legacy excited-average fields remain readable in older result files.

| Network mesh | Cells | Peak Br difference | Signed Br curve error | Signed Btheta curve error |
|---|---:|---:|---:|---:|
| Low preset | 1,008 | 0.268% | 14.08% | 33.30% |
| Mid preset | 8,640 | 0.067% | 7.56% | 43.32% |
| High preset | 64,800 | 0.033% | 2.73% | 12.14% |
| High against refined FEMM | 64,800 | 0.008% | 2.69% | 12.01% |
| Additional refinement against refined FEMM | 259,200 | — | 0.90% | 5.32% |

The additional refinement uses 40 rotor, 40 slot, 60 gap and 40 yoke layers,
with angular divider 20. Its fields were interpolated to the refined FEMM
reference's fixed sample locations. The refined FEMM run uses 0.25-degree arc
segments and an air-gap mesh size of gap/12. Other comparison rows use the
shared template's one-degree segments and gap/4 mesh size.

The signed field curves show the remaining local discrepancy near slot edges,
particularly in Btheta. Refinement reduces it. Peak agreement alone would hide
this discrepancy. These checks evaluate the implemented linear magnetic model.
Prescribed permeability does not represent saturation.

An additional case with slot opening 4 degrees, span 6, Wt 28 degrees and 0.5 A
gave 0.0016% peak Br difference, 5.20% signed Br curve error and 19.53% Btheta
curve error on the mid preset. The span-18 cancellation case gives exactly zero
field in both models.

## Reproduction and evidence

Reproduce the FEMM comparisons from the project root.

```powershell
.venv/Scripts/python.exe tools/compare_femm_physics.py --preset high
.venv/Scripts/python.exe tools/compare_femm_physics.py --preset mid --slot-angle 4 --span 6 --wt 28 --current 0.5
```

The comparison tool saves its model, sample CSV, numeric summary and signed
field plot under femm_validation/runs/. Existing FEMM windows are independent
of these audit runs. Application validation retains its results popup and open
FEMM field view.

Retained audit evidence is in the following local run folders.

- physics-audit-corrected-low
- physics-audit-corrected-mid
- physics-audit-corrected-high
- physics-audit-reference-fine
- physics-audit-high-fine-reference
- physics-audit-extra-fine
- physics-audit-span6-slot4-wt28
- physics-audit-span18-zero
