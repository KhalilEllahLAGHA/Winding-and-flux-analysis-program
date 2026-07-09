"""Polar mesh generation for the 4-region machine model
(formerly ``Meshing_engine.py``).

Pure calculation module: errors are raised as ``ValueError`` and presented
by the UI layer (the engine no longer pops Qt message boxes itself).
"""

import logging
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)

# Radii comparisons tolerance when closing the outermost division.
OUTER_RADIUS_TOLERANCE_MM = 1e-6
# Fixed-point precision used when computing the GCD of fractional arcs.
GCD_PRECISION = 1000

MATERIAL_ROTOR_CORE = "Rotor Core"
MATERIAL_AIR_GAP = "Air Gap"
MATERIAL_TOOTH = "Tooth"
MATERIAL_SLOT = "Slot"
MATERIAL_STATOR_CORE = "Stator Core"
ALL_MATERIALS = (MATERIAL_ROTOR_CORE, MATERIAL_AIR_GAP, MATERIAL_TOOTH,
                 MATERIAL_STATOR_CORE, MATERIAL_SLOT)


class MeshingEngine:
    """Generates an annular-sector mesh over rotor, air gap, slot/tooth,
    and stator yoke regions."""

    def __init__(self):
        self.mesh_elements = []
        self.r_divisions = []
        self.theta_divisions = []
        self.machine_params = {}
        self.mesh_stats = {}
        self.base_mesh_angle = None

    def generate_mesh(self, machine_params, mesh_settings):
        """Generate the mesh; raises ValueError on inconsistent geometry."""
        self.machine_params = machine_params

        _validate_geometry(machine_params)

        stator_inner_radius = machine_params['stator_inner_radius']
        rotor_outer_radius = stator_inner_radius - machine_params['air_gap']
        tooth_tip_radius = stator_inner_radius + machine_params['slot_height']
        slot_pitch = 360 / machine_params['num_slots']
        tooth_angle = slot_pitch - machine_params['slot_angle']

        mesh_angle = self.calculate_mesh_angle(machine_params, mesh_settings)
        self.r_divisions = self.create_radial_divisions(machine_params, mesh_settings)
        self.theta_divisions = self.create_angular_divisions(mesh_angle)

        material_boundaries = {
            'rotor_outer': rotor_outer_radius,
            'stator_inner': stator_inner_radius,
            'tooth_tip': tooth_tip_radius,
            'slot_pitch': slot_pitch,
            'tooth_angle': tooth_angle,
        }

        self.mesh_elements, region_counts = self._create_mesh_elements(
            self.r_divisions, self.theta_divisions, material_boundaries)

        self.mesh_stats = {
            'total_elements': len(self.mesh_elements),
            'mesh_angle': mesh_angle,
            'base_mesh_angle': self.base_mesh_angle or mesh_angle,
            'radial_divisions': len(self.r_divisions) - 1,
            'angular_divisions': len(self.theta_divisions) - 1,
            'region_counts': region_counts,
            'angle_divider': mesh_settings.get('angle_divider', 1),
        }
        logger.info("Mesh generated: %s elements, mesh angle %.3f°",
                    self.mesh_stats['total_elements'], mesh_angle)

        return {
            'mesh_elements': self.mesh_elements,
            'r_divisions': self.r_divisions,
            'theta_divisions': self.theta_divisions,
            'total_angular': len(self.theta_divisions) - 1,
            'params': machine_params,
            'settings': mesh_settings,
            'mesh_stats': self.mesh_stats,
        }

    def calculate_mesh_angle(self, machine_params, mesh_settings):
        """Mesh angle = GCD(slot arc, tooth arc) / angle divider, snapped so
        it divides 360° exactly."""
        angle_divider = mesh_settings.get('angle_divider', 1)

        slot_pitch = 360 / machine_params['num_slots']
        slot_arc = machine_params['slot_angle']
        tooth_arc = slot_pitch - slot_arc

        if slot_arc <= 0:
            raise ValueError("Slot angle must be positive")
        if tooth_arc <= 0:
            raise ValueError("Slot angle too large - no space for teeth")

        self.base_mesh_angle = self.calculate_gcd_fractional(slot_arc, tooth_arc)

        final_mesh_angle = self.base_mesh_angle / angle_divider
        divisions = round(360 / final_mesh_angle)
        return 360 / divisions

    @staticmethod
    def calculate_gcd_fractional(a, b, precision=GCD_PRECISION):
        """GCD of two fractional angles via fixed-point integers."""
        a_int = int(round(a * precision))
        b_int = int(round(b * precision))
        return _binary_gcd(a_int, b_int) / precision

    def create_radial_divisions(self, machine_params, mesh_settings):
        """Radial division boundaries: equal-thickness layers per region."""
        shaft_radius = machine_params['shaft_radius']
        stator_inner_radius = machine_params['stator_inner_radius']
        stator_outer_radius = machine_params['stator_outer_radius']
        rotor_outer_radius = stator_inner_radius - machine_params['air_gap']
        tooth_tip_radius = stator_inner_radius + machine_params['slot_height']

        regions = [
            (shaft_radius, rotor_outer_radius, mesh_settings['rotor']),
            (rotor_outer_radius, stator_inner_radius, mesh_settings['airgap']),
            (stator_inner_radius, tooth_tip_radius, mesh_settings['slot']),
            (tooth_tip_radius, stator_outer_radius, mesh_settings['stator']),
        ]

        r_divisions = [shaft_radius]
        for inner, outer, layers in regions:
            if layers > 0:
                # Skip the first point: it matches the previous region's end.
                r_divisions.extend(np.linspace(inner, outer, layers + 1)[1:].tolist())

        if abs(r_divisions[-1] - stator_outer_radius) > OUTER_RADIUS_TOLERANCE_MM:
            r_divisions.append(stator_outer_radius)

        return r_divisions

    def create_angular_divisions(self, mesh_angle):
        """Angular division boundaries covering exactly 0-360°."""
        num_divisions = int(np.ceil(360 / mesh_angle))
        theta_divisions = np.linspace(0, 360, num_divisions + 1).tolist()
        theta_divisions[-1] = 360.0
        return theta_divisions

    def _create_mesh_elements(self, r_divisions, theta_divisions, boundaries):
        """Build mesh element dictionaries and per-material counts."""
        mesh_elements = []
        region_counts = {material: 0 for material in ALL_MATERIALS}

        r_centers = [(r_divisions[i] + r_divisions[i + 1]) / 2
                     for i in range(len(r_divisions) - 1)]
        theta_centers = [(theta_divisions[j] + theta_divisions[j + 1]) / 2
                         for j in range(len(theta_divisions) - 1)]

        sin_theta = np.sin(np.radians(np.array(theta_centers)))
        cos_theta = np.cos(np.radians(np.array(theta_centers)))

        element_id = 1
        for i in range(len(r_divisions) - 1):
            r_center = r_centers[i]
            radial_material = self._radial_region_material(r_center, boundaries)

            for j in range(len(theta_divisions) - 1):
                theta_center = theta_centers[j]
                # The slot/tooth band needs a per-angle material decision.
                material = radial_material or _slot_or_tooth(
                    theta_center, boundaries['slot_pitch'], boundaries['tooth_angle'])
                region_counts[material] += 1

                mesh_elements.append({
                    'rin': r_divisions[i],
                    'rout': r_divisions[i + 1],
                    'theta_start': theta_divisions[j],
                    'theta_end': theta_divisions[j + 1],
                    'material': material,
                    'center_r': r_center,
                    'center_theta': theta_center,
                    'center_x': r_center * cos_theta[j],
                    'center_y': r_center * sin_theta[j],
                    'element_id': element_id,
                })
                element_id += 1

        return mesh_elements, region_counts

    @staticmethod
    def _radial_region_material(r_center, boundaries):
        """Material for a radius, or None inside the slot/tooth band."""
        if r_center <= boundaries['rotor_outer']:
            return MATERIAL_ROTOR_CORE
        if r_center <= boundaries['stator_inner']:
            return MATERIAL_AIR_GAP
        if r_center <= boundaries['tooth_tip']:
            return None
        return MATERIAL_STATOR_CORE


def _validate_geometry(machine_params):
    if machine_params['stator_inner_radius'] >= machine_params['stator_outer_radius']:
        raise ValueError("Stator inner radius must be less than outer radius")

    rotor_outer = machine_params['stator_inner_radius'] - machine_params['air_gap']
    if machine_params['shaft_radius'] >= rotor_outer:
        raise ValueError("Shaft radius too large for given air gap")

    if machine_params['num_slots'] < 3:
        raise ValueError("Number of slots must be at least 3")

    slot_pitch = 360 / machine_params['num_slots']
    if slot_pitch - machine_params['slot_angle'] <= 0:
        raise ValueError("Slot angle too large - no space for teeth")


@lru_cache(maxsize=1024)
def _slot_or_tooth(theta, slot_pitch, tooth_angle):
    """Classify an angle within the slot/tooth band (tooth first, then slot)."""
    theta_norm = theta % 360
    slot_index = int(theta_norm / slot_pitch)
    local_angle = theta_norm - slot_index * slot_pitch
    return MATERIAL_TOOTH if local_angle <= tooth_angle else MATERIAL_SLOT


def _binary_gcd(x, y):
    """Binary (Stein) GCD for non-negative integers."""
    if x == 0:
        return y
    if y == 0:
        return x

    shift = 0
    while ((x | y) & 1) == 0:
        x >>= 1
        y >>= 1
        shift += 1

    while (x & 1) == 0:
        x >>= 1

    while y != 0:
        while (y & 1) == 0:
            y >>= 1
        if x > y:
            x, y = y, x
        y -= x

    return x << shift
