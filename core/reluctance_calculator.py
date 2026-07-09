"""Reluctance network calculation for mesh elements
(formerly ``Meshing_reluctance_calculation.py``)."""

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
        mesh_angle = mesh_data.get('mesh_stats', {}).get('mesh_angle', 10)
        total_elements = len(self.mesh_elements)

        if progress_callback:
            progress_callback(
                f"Starting reluctance calculation for {total_elements:,} elements...")

        reluctance_data = []
        region_stats = defaultdict(int)

        for i, element in enumerate(self.mesh_elements):
            if progress_callback and i % PROGRESS_REPORT_INTERVAL == 0 and i > 0:
                progress = int((i / total_elements) * 100)
                progress_callback(
                    f"Processing elements... {progress}% ({i:,}/{total_elements:,})")

            reluctance_data.append({
                'element_id': i + 1,
                'material': element['material'],
                'geometry': {
                    'rin': element['rin'],
                    'rout': element['rout'],
                    'theta_start': element['theta_start'],
                    'theta_end': element['theta_end'],
                },
                'reluctances': self.calculate_element_reluctance(
                    element, axial_length_m),
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

        if rout_m > rin_m:
            log_ratio = np.log(rout_m / rin_m)
            r_radial = log_ratio / (2 * theta_span * mu * axial_length_m)
            r_circumferential = theta_span / (2 * mu * axial_length_m * log_ratio)
        else:
            # Zero-thickness element: infinite reluctance.
            r_radial = float('inf')
            r_circumferential = float('inf')

        return {
            'R_up': r_radial,
            'R_down': r_radial,
            'R_left': r_circumferential,
            'R_right': r_circumferential,
            'R_avg': (r_radial + r_circumferential) / 2,
            'permeability': mu,
            'relative_permeability': ur,
        }

    def get_material_permeability(self, material):
        """Relative permeability for a mesh material (air when unknown)."""
        ur_key = MATERIAL_PERMEABILITY_KEYS.get(material, 'ur_air')
        return self.material_permeabilities.get(ur_key, 1.0)

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
