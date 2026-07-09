"""Mapping of resultant tooth MMF values onto mesh elements
(formerly ``Meshing_mmf_teeth_slot.py``)."""

import logging
from collections import defaultdict

import numpy as np

logger = logging.getLogger(__name__)

PROGRESS_REPORT_INTERVAL = 1000  # elements between progress callbacks


class TeethSlotMMFCalculator:
    """Distributes the per-tooth resultant MMF over tooth and slot mesh
    elements (slots get the average of their two adjacent teeth)."""

    def __init__(self):
        self.mesh_elements = []
        self.mmf_results = {}
        self.tooth_layers = 1
        self.angle_divider = 1

        # Cached per-element layout (Wt-independent), keyed by mesh identity
        # and the angle divider. Lets each animation frame compute element
        # MMF as vectorised gathers instead of a per-element Python loop.
        self._layout_key = None
        self._sector = None        # int array: tooth/slot index per element
        self._is_tooth = None      # bool mask
        self._is_slot = None       # bool mask
        # Cached machine parameters recovered from the mesh.
        self._mp_key = None
        self._mp_cache = None

    def calculate_teeth_mmf(self, mesh_data, mesh_settings, mmf_calculator,
                            progress_callback=None, build_full=True):
        """Calculate per-element MMF sources from the MMF engine's tooth data.

        ``build_full`` controls whether the full ``mmf_data`` list of per-element
        dicts is assembled. The animation passes ``build_full=False``: it only
        needs the ``element_mmf_ud`` array the solver consumes, so it skips
        rebuilding ~thousands of dicts every frame.

        Raises when the MMF engine has no tooth data available.
        """
        if progress_callback:
            progress_callback("Starting teeth and slot MMF calculation...")

        self.mesh_elements = mesh_data['mesh_elements']
        # Slot/tooth radial layer count doubles as the per-layer MMF divisor.
        self.tooth_layers = mesh_settings.get('slot', 1)
        self.angle_divider = mesh_settings.get('angle_divider', 1)

        tooth_mmf_data = mmf_calculator.get_tooth_mmf_data()
        if not tooth_mmf_data or 'Resultant' not in tooth_mmf_data:
            raise RuntimeError(
                "No tooth MMF data available from MMF calculation engine")

        resultant_tooth_mmf = tooth_mmf_data['Resultant']['tooth_mmf']
        total_elements = len(self.mesh_elements)

        if progress_callback:
            progress_callback(f"Processing {total_elements:,} elements...")

        machine_params = self._machine_params_from_mesh(mesh_data)
        slot_mmf_values = self.calculate_slot_mmf_values(
            resultant_tooth_mmf, machine_params)

        self._ensure_layout(machine_params)
        element_mmf_ud, source_tooth, source_slot = self._element_mmf_array(
            resultant_tooth_mmf, slot_mmf_values)

        if build_full:
            mmf_data, region_stats = self._build_mmf_data(
                element_mmf_ud, source_tooth, source_slot, progress_callback)
        else:
            mmf_data, region_stats = [], {}

        self.mmf_results = {
            'mmf_data': mmf_data,
            'element_mmf_ud': element_mmf_ud,
            'statistics': {
                'total_elements': total_elements,
                'tooth_layers': self.tooth_layers,
                'region_distribution': dict(region_stats),
                'num_teeth': len(resultant_tooth_mmf),
                'num_slots': len(slot_mmf_values),
            },
            'tooth_mmf_values': resultant_tooth_mmf,
            'slot_mmf_values': slot_mmf_values,
            'machine_parameters': machine_params,
        }

        if progress_callback:
            progress_callback("Teeth and slot MMF calculation completed!")

        return self.mmf_results

    def _ensure_layout(self, machine_params):
        """Cache the per-element tooth/slot classification and sector index.

        Depends only on the mesh geometry and the angle divider, so it is
        computed once and reused across every Wt frame of an animation.
        """
        elements = self.mesh_elements
        key = (id(elements), len(elements), self.angle_divider,
               machine_params['num_slots'])
        if key == self._layout_key:
            return

        n = len(elements)
        sector = np.full(n, -1, dtype=np.int64)
        is_tooth = np.zeros(n, dtype=bool)
        is_slot = np.zeros(n, dtype=bool)

        num_slots = machine_params['num_slots']
        divider = self.angle_divider
        division_angle = 360.0 / (num_slots * divider) if num_slots > 0 else 360.0

        for i, element in enumerate(elements):
            material = element['material']
            if material == 'Tooth':
                is_tooth[i] = True
            elif material == 'Slot':
                is_slot[i] = True
            else:
                continue
            theta_center = ((element['theta_start']
                             + element['theta_end']) / 2) % 360
            fine_index = int(theta_center / division_angle)
            sector[i] = (fine_index // (divider * divider)) % num_slots

        self._sector = sector
        self._is_tooth = is_tooth
        self._is_slot = is_slot
        self._layout_key = key

    def _element_mmf_array(self, tooth_mmf_values, slot_mmf_values):
        """Vectorised per-element up/down MMF magnitude for the current frame.

        Returns (mmf_ud, source_tooth_mask, source_slot_mask). Elements whose
        sector falls outside the available values carry zero MMF, matching the
        original per-element guard exactly.
        """
        sector = self._sector
        divisor = 2.0 * self.tooth_layers
        tooth_arr = np.asarray(tooth_mmf_values, dtype=np.float64)
        slot_arr = np.asarray(slot_mmf_values, dtype=np.float64)

        in_tooth = self._is_tooth & (sector >= 0) & (sector < tooth_arr.size)
        in_slot = self._is_slot & (sector >= 0) & (sector < slot_arr.size)

        mmf_ud = np.zeros(sector.size, dtype=np.float64)
        if divisor > 0:
            mmf_ud[in_tooth] = tooth_arr[sector[in_tooth]] / divisor
            mmf_ud[in_slot] = slot_arr[sector[in_slot]] / divisor
        return mmf_ud, in_tooth, in_slot

    def _build_mmf_data(self, element_mmf_ud, source_tooth, source_slot,
                        progress_callback=None):
        """Assemble the full per-element MMF dict list (interactive path)."""
        sector = self._sector
        ud = element_mmf_ud.tolist()
        sec = sector.tolist()
        src_tooth = source_tooth.tolist()
        src_slot = source_slot.tolist()

        mmf_data = []
        region_stats = defaultdict(int)
        total_elements = len(self.mesh_elements)

        for i, element in enumerate(self.mesh_elements):
            if progress_callback and i % PROGRESS_REPORT_INTERVAL == 0 and i > 0:
                progress = int((i / total_elements) * 100)
                progress_callback(
                    f"Processing elements... {progress}% ({i:,}/{total_elements:,})")

            value = ud[i]
            if src_tooth[i]:
                tooth_number, slot_number = sec[i], -1
            elif src_slot[i]:
                tooth_number, slot_number = -1, sec[i]
            else:
                tooth_number, slot_number = -1, -1

            mmf_data.append({
                'element_id': i + 1,
                'material': element['material'],
                'geometry': {
                    'rin': element['rin'],
                    'rout': element['rout'],
                    'theta_start': element['theta_start'],
                    'theta_end': element['theta_end'],
                },
                'mmf_values': {
                    'MMF_up': value,
                    'MMF_down': value,
                    'MMF_left': 0.0,
                    'MMF_right': 0.0,
                    'tooth_number': tooth_number,
                    'slot_number': slot_number,
                },
                'tooth_number': tooth_number,
                'slot_number': slot_number,
            })
            region_stats[element['material']] += 1

        return mmf_data, region_stats

    @staticmethod
    def calculate_slot_mmf_values(tooth_mmf_values, machine_params):
        """Slot MMF = average of the two adjacent tooth MMF values.

        Slot N sits between tooth N and tooth N+1 (wrapping around).
        """
        num_slots = machine_params['num_slots']
        num_teeth = len(tooth_mmf_values)

        return [
            (tooth_mmf_values[slot % num_teeth]
             + tooth_mmf_values[(slot + 1) % num_teeth]) / 2
            for slot in range(num_slots)
        ]

    def _machine_params_from_mesh(self, mesh_data):
        """Recover slot count and pitch from the mesh itself (cached per mesh).

        Counting distinct slot angular positions scans every mesh element, so
        the result is cached keyed by mesh identity to keep animation frames
        from rescanning the whole mesh each time.
        """
        elements = self.mesh_elements
        key = (id(elements), len(elements))
        if key == self._mp_key and self._mp_cache is not None:
            return self._mp_cache

        params = self._compute_machine_params_from_mesh(mesh_data)
        self._mp_key = key
        self._mp_cache = params
        return params

    def _compute_machine_params_from_mesh(self, mesh_data):
        mesh_stats = mesh_data.get('mesh_stats', {})

        slot_elements = [element for element in self.mesh_elements
                         if element['material'] == 'Slot']
        if slot_elements:
            theta_positions = {
                round((element['theta_start'] + element['theta_end']) / 2, 1)
                for element in slot_elements
            }
            num_slots = len(theta_positions)
        else:
            mesh_angle = mesh_stats.get('mesh_angle', 10)
            num_slots = int(360 / mesh_angle) if mesh_angle > 0 else 36

        slot_pitch = 360 / num_slots if num_slots > 0 else 10

        return {
            'num_slots': num_slots,
            'slot_pitch': slot_pitch,
            'mesh_angle': mesh_stats.get('mesh_angle', slot_pitch),
        }
