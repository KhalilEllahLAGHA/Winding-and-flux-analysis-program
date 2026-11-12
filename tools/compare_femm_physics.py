"""Reproduce a signed, point-by-point network/FEMM air-gap comparison.

Run from the project root, for example:
    .venv/Scripts/python.exe tools/compare_femm_physics.py --preset mid
The independent FEMM run is hidden and does not touch existing FEMM windows.
"""

import argparse
import csv
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.connection_matrix import generate_connection_matrix
from core.femm_runner import parse_validation_results, run_femm_script
from core.femm_validation import (airgap_samples, build_validation_script,
                                  compute_reference_metrics, airgap_profile,
                                  compare_airgap_profiles)
from core.flux_solver import FluxCalculator
from core.meshing_engine import MeshingEngine
from core.mmf_engine import MMFCalculationEngine
from core.reluctance_calculator import ReluctanceCalculator
from core.teeth_slot_mmf import TeethSlotMMFCalculator
from utils.constants import (DEFAULT_MACHINE_PARAMS, DEFAULT_RELATIVE_PERMEABILITIES,
                             MESH_PRESETS, PHASES)


def run_comparison(output_dir, *, preset='mid', slot_angle=5.0, span=9,
                   current=2.8, wt=90.0, reuse_femm=None):
    output_dir = Path(output_dir).resolve()
    settings = dict(MESH_PRESETS[{'low': 0, 'mid': 1, 'high': 2}[preset]])
    params = dict(DEFAULT_MACHINE_PARAMS, slot_angle=slot_angle)
    slots, poles, axial_length = params['num_slots'], 4, 110.0

    # The same phase belts as the stator drawing; return directions are
    # independently enforced by the connection matrix's coil-span pairing.
    def phase(slot):
        angle = (slot % slots) * poles * 360 / slots % 360
        return 'A' if angle < 120 else 'C' if angle < 240 else 'B'

    pattern = [(phase(k), phase(k - span)) for k in range(slots)]
    engine = MMFCalculationEngine()
    engine.set_connection_matrix(generate_connection_matrix(
        pattern, PHASES, True, poles, coil_span=span))
    engine.update_slot_arc(slot_angle)
    engine.update_current(current)
    engine.update_wt_angle(wt)
    mesh = MeshingEngine().generate_mesh(params, settings)
    reluctances = ReluctanceCalculator().calculate_reluctances(
        mesh, DEFAULT_RELATIVE_PERMEABILITIES, {'axial_length': axial_length})
    mmf = TeethSlotMMFCalculator().calculate_teeth_mmf(mesh, settings, engine)
    result = FluxCalculator().calculate_flux_distribution(
        reluctances, mmf, {'tolerance': 1e-9})
    samples = airgap_samples(mesh)
    local = compute_reference_metrics(result, samples, axial_length)
    script = build_validation_script(mesh, engine, DEFAULT_RELATIVE_PERMEABILITIES,
                                     axial_length, output_dir)
    if reuse_femm is None:
        run_femm_script(script, output_dir / 'validation_results.txt', timeout=120)
        reference_dir = output_dir
    else:
        reference_dir = Path(reuse_femm).resolve()
    reference = parse_validation_results(reference_dir / 'validation_results.txt')
    with (reference_dir / 'airgap_samples.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    reference.setdefault('airgap_br_mean_abs_t',
                         float(np.mean([abs(float(r['br_t'])) for r in rows])))
    reference.setdefault('airgap_flux_mean_abs_wb',
                         float(np.mean([abs(float(r['radial_flux_wb'])) for r in rows])))
    if len(rows) != len(samples):
        raise ValueError('Reference and local sample counts differ.')
    theta = np.array([e['center_theta'] for e in samples])
    if not np.allclose(theta, [float(r['theta_deg']) for r in rows]):
        raise ValueError('Reference and local sample angles differ.')
    curves = {}
    summary = {
        'configuration': {'preset': preset, 'slot_angle_deg': slot_angle,
                          'coil_span_slots': span, 'phase_current_a': current,
                          'wt_deg': wt, 'mesh_cells': len(mesh['mesh_elements'])},
        'local': local, 'femm': reference, 'solver': result['solver_info'],
        'relative_metric_errors_percent': {
            k: abs(local[k] - reference[k]) / reference[k] * 100
            if reference[k] > 1e-12 else None for k in local},
        'signed_profile_errors': compare_airgap_profiles(
            airgap_profile(result, samples), reference_dir / 'airgap_samples.csv'),
    }
    for component, column in (('Br', 'br_t'), ('Btheta', 'btheta_t')):
        actual = np.array([result['flux_densities'][e['element_id']][component]
                           for e in samples])
        expected = np.array([float(row[column]) for row in rows])
        error = actual - expected
        curves[component] = actual, expected, error
    with (output_dir / 'comparison_samples.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['theta_deg', 'local_br_t', 'femm_br_t',
                         'local_btheta_t', 'femm_btheta_t'])
        writer.writerows(zip(theta, curves['Br'][0], curves['Br'][1],
                             curves['Btheta'][0], curves['Btheta'][1]))
    (output_dir / 'physics_comparison.json').write_text(
        json.dumps(summary, indent=2), encoding='utf-8')
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, layout='constrained')
    for ax, component in zip(axes[:2], ('Br', 'Btheta')):
        actual, expected, _ = curves[component]
        ax.plot(theta, expected, label='FEMM', color='#1d4ed8', linewidth=2)
        ax.plot(theta, actual, label='Reluctance network', color='#dc2626',
                linestyle='--', linewidth=1.5)
        ax.set_ylabel(f'{component} [T]')
        ax.grid(alpha=.25)
        ax.legend(loc='upper right')
    axes[2].plot(theta, curves['Br'][2], color='#7c3aed')
    axes[2].set_ylabel('Br difference [T]')
    axes[2].set_xlabel('Mechanical angle [degrees]')
    axes[2].grid(alpha=.25)
    fig.suptitle(f'Independent air-gap comparison: {preset} mesh, '
                 f'span {span}, slot {slot_angle:g} deg, Wt {wt:g} deg')
    fig.savefig(output_dir / 'field_comparison.png', dpi=160)
    plt.close(fig)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset', choices=('low', 'mid', 'high'), default='mid')
    parser.add_argument('--slot-angle', type=float, default=5.0)
    parser.add_argument('--span', type=int, default=9)
    parser.add_argument('--current', type=float, default=2.8)
    parser.add_argument('--wt', type=float, default=90.0)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reuse-femm', type=Path)
    args = parser.parse_args()
    output = args.output or (PROJECT_ROOT / 'femm_validation' / 'runs'
                             / f'physics-audit-{args.preset}-slot{args.slot_angle:g}'
                               f'-span{args.span}-wt{args.wt:g}')
    print(json.dumps(run_comparison(
        output, preset=args.preset, slot_angle=args.slot_angle, span=args.span,
        current=args.current, wt=args.wt, reuse_femm=args.reuse_femm), indent=2))


if __name__ == '__main__':
    main()
