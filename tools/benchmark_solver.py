"""Benchmark checked cold/repeated solves across the three standard meshes."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.connection_matrix import build_winding_connection_matrix
from core.flux_solver import FluxCalculator
from core.meshing_engine import MeshingEngine
from core.mmf_engine import MMFCalculationEngine
from core.reluctance_calculator import ReluctanceCalculator
from core.teeth_slot_mmf import TeethSlotMMFCalculator
from utils.constants import DEFAULT_MACHINE_PARAMS, DEFAULT_RELATIVE_PERMEABILITIES, MESH_PRESETS


def benchmark():
    report = []
    for preset in (0, 1, 2):
        mesh = MeshingEngine().generate_mesh(dict(DEFAULT_MACHINE_PARAMS), MESH_PRESETS[preset])
        engine = MMFCalculationEngine()
        engine.set_connection_matrix(build_winding_connection_matrix(36, 4, True, 9))
        engine.update_wt_angle(113)
        solver, mmf = FluxCalculator(), TeethSlotMMFCalculator()
        start = time.perf_counter()
        reluctance = ReluctanceCalculator().calculate_reluctances(
            mesh, DEFAULT_RELATIVE_PERMEABILITIES, {'axial_length': 110})
        source = mmf.calculate_teeth_mmf(mesh, MESH_PRESETS[preset], engine)
        result = solver.calculate_flux_distribution(reluctance, source,
                                                     {'method': 'auto', 'tolerance': 1e-6})
        cold = time.perf_counter()-start
        checks = []
        for angle in (*range(0, 360, 30), 113):
            start = time.perf_counter()
            engine.update_wt_angle(angle)
            source = mmf.calculate_teeth_mmf(mesh, MESH_PRESETS[preset], engine)
            result = solver.calculate_flux_distribution(reluctance, source,
                                                        {'method': 'auto', 'tolerance': 1e-6})
            residual = result['solver_info']['relative_residual']
            if residual > 1e-5:
                raise RuntimeError(f'Full-network residual failed: {residual}')
            checks.append({'angle': angle, 'seconds': time.perf_counter()-start,
                           'relative_residual': residual})
        report.append({'preset': preset, 'elements': len(mesh['mesh_elements']),
                       'cold_seconds': cold, 'repeated_checks': checks})
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = benchmark()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    for row in report:
        warm = sum(check['seconds'] for check in row['repeated_checks'])/len(row['repeated_checks'])
        print(f"{row['elements']:,} cells: cold {row['cold_seconds']:.3f}s, repeated mean {warm:.3f}s")
