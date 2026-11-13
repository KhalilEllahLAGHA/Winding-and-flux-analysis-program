"""Reluctance network calculation for mesh elements."""

import logging
import time
from collections import defaultdict

import numpy as np

from utils.constants import DEFAULT_AXIAL_LENGTH_MM, MU0

logger = logging.getLogger(__name__)

PROGRESS_REPORT_INTERVAL = 2000  # elements between progress callbacks

# Mesh material -> permeability key in the material properties dict.
MATERIAL_PERMEABILITY_KEYS = {
    'Stator Core': 'ur_stator',
    'Tooth': 'ur_stator',
    'Rotor Core': 'ur_rotor',
    'Slot': 'ur_air',
    'Air Gap': 'ur_air',
    'Rotor Air': 'ur_air',
}


class ReluctanceCalculator:
    """Computes radial and circumferential reluctances per mesh element."""

    def __init__(self):
        self.material_permeabilities = {}
        self.mesh_elements = []
        self.reluctance_results = {}

    def calculate_reluctances(self, mesh_data, material_properties,
                              machine_params, progress_callback=None):
        """Calculate reluctances for all mesh elements.

        Returns a results dictionary with per-element reluctance data plus
        statistics; raises on invalid input.
        """
        start_time = time.time()

        self.mesh_elements = mesh_data['mesh_elements']
        self.material_permeabilities = material_properties

        axial_length_m = float(
            machine_params.get('axial_length', DEFAULT_AXIAL_LENGTH_MM)) / 1000
        if not np.isfinite(axial_length_m) or axial_length_m <= 0:
            raise ValueError('Axial length must be finite and positive.')
        mesh_angle = mesh_data.get('mesh_stats', {}).get('mesh_angle', 10)
        total_elements = len(self.mesh_elements)

        if progress_callback:
            progress_callback(
                f"Starting reluctance calculation for {total_elements:,} elements...")

        reluctance_data = []
        region_stats = defaultdict(int)

        # Evaluate the same annular-sector formulas in one NumPy pass rather
        # than repeating scalar logarithms and validation for every cell.
        geometry = np.asarray([
            (e['rin'], e['rout'], e['theta_end']-e['theta_start'])
            for e in self.mesh_elements], dtype=float).reshape(-1, 3)
        rin, rout, span = geometry.T
        rin, rout, span = rin/1000, rout/1000, np.radians(span)
        if (not np.isfinite(geometry).all() or np.any(rin <= 0)
                or np.any(rout <= rin) or np.any(span <= 0)):
            raise ValueError('Mesh cells require positive finite radii, angular '
                             'width and axial length, with rout greater than rin.')
        permeabilities = {material: self.get_material_permeability(material)
                          for material in {e['material'] for e in self.mesh_elements}}
        ur = np.fromiter((permeabilities[e['material']] for e in self.mesh_elements),
                         dtype=float, count=total_elements)
        mu = ur * MU0
        center = (rin+rout)/2
        up = np.log(rout/center)/(span*mu*axial_length_m)
        down = np.log(center/rin)/(span*mu*axial_length_m)
        side = span/(2*mu*axial_length_m*np.log(rout/rin))
        # Python floats keep the export schema identical to the scalar API.
        rows = zip(up.tolist(), down.tolist(), side.tolist(), mu.tolist(), ur.tolist())

        for i, (element, values) in enumerate(zip(self.mesh_elements, rows)):
            if progress_callback and i % PROGRESS_REPORT_INTERVAL == 0 and i > 0:
                progress = int((i / total_elements) * 100)
                progress_callback(
                    f"Processing elements... {progress}% ({i:,}/{total_elements:,})")

            r_up, r_down, r_side, permeability, relative = values
            reluctance_data.append({
                'element_id': i + 1,
                'material': element['material'],
                'geometry': {
                    'rin': element['rin'],
                    'rout': element['rout'],
                    'theta_start': element['theta_start'],
                    'theta_end': element['theta_end'],
                },
                'reluctances': {
                    'R_up': r_up, 'R_down': r_down,
                    'R_left': r_side, 'R_right': r_side,
                    'R_avg': (r_up+r_down+2*r_side)/4,
                    'permeability': permeability, 'relative_permeability': relative,
                },
                'center': {
                    'r': (element['rin'] + element['rout']) / 2,
                    'theta': (element['theta_start'] + element['theta_end']) / 2,
                },
            })
            region_stats[element['material']] += 1

        total_time = time.time() - start_time

        self.reluctance_results = {
            'reluctance_data': reluctance_data,
            'statistics': {
                'total_elements': total_elements,
                'calculation_time': total_time,
                'elements_per_second': total_elements / total_time if total_time else 0.0,
                'region_distribution': dict(region_stats),
                'average_reluctances': self._statistics_by_region(reluctance_data),
            },
            'material_properties': material_properties,
            'machine_parameters': machine_params,
            'mesh_angle': mesh_angle,
            'physical_constants': {'mu0': MU0, 'axial_length': axial_length_m},
        }

        if progress_callback:
            progress_callback(
                f"Reluctance calculation completed in {total_time:.2f}s!")
        logger.info("Reluctances for %s elements in %.2fs",
                    total_elements, total_time)

        return self.reluctance_results

    def calculate_element_reluctance(self, element, axial_length_m):
        """Reluctances of one annular-sector element in all four directions."""
        rin_m = element['rin'] / 1000
        rout_m = element['rout'] / 1000
        theta_span = np.radians(element['theta_end'] - element['theta_start'])

        ur = self.get_material_permeability(element['material'])
        mu = ur * MU0
        if (not all(np.isfinite(v) for v in (
                rin_m, rout_m, theta_span, axial_length_m))
                or rin_m <= 0 or rout_m <= rin_m
                or theta_span <= 0 or axial_length_m <= 0):
            raise ValueError('Mesh cells require positive finite radii, angular '
                             'width and axial length, with rout greater than rin.')

        log_ratio = np.log(rout_m / rin_m)
        r_center = (rin_m + rout_m) / 2
        # The unknown is located at the arithmetic cell centre. Splitting
        # log(rout/rin) equally would instead locate it at sqrt(rin*rout).
        r_up = np.log(rout_m / r_center) / (theta_span * mu * axial_length_m)
        r_down = np.log(r_center / rin_m) / (theta_span * mu * axial_length_m)
        r_circumferential = theta_span / (2 * mu * axial_length_m * log_ratio)

        return {
            'R_up': r_up,
            'R_down': r_down,
            'R_left': r_circumferential,
            'R_right': r_circumferential,
            'R_avg': (r_up + r_down + 2 * r_circumferential) / 4,
            'permeability': mu,
            'relative_permeability': ur,
        }

    def get_material_permeability(self, material):
        """Relative permeability for a mesh material (air when unknown)."""
        ur_key = MATERIAL_PERMEABILITY_KEYS.get(material, 'ur_air')
        ur = float(self.material_permeabilities.get(ur_key, 1.0))
        if not np.isfinite(ur) or ur <= 0:
            raise ValueError('Material relative permeabilities must be finite '
                             'and positive.')
        return ur

    @staticmethod
    def _statistics_by_region(reluctance_data):
        """Average/min/max/std of finite element reluctances per material."""
        region_reluctances = defaultdict(list)
        for data in reluctance_data:
            avg_reluctance = data['reluctances']['R_avg']
            if not np.isinf(avg_reluctance):
                region_reluctances[data['material']].append(avg_reluctance)

        return {
            material: {
                'average': np.mean(values),
                'min': np.min(values),
                'max': np.max(values),
                'std': np.std(values),
                'count': len(values),
            }
            for material, values in region_reluctances.items()
        }
