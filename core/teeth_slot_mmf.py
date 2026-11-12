"""Impressed-field sources equivalent to uniform axial slot currents.

The winding function F rises by each slot's ampere-turns across that slot.
Inside the slot/tooth band H_imp,r = -2*r*F(theta)/(Rout²-Rin²), giving
curl(H_imp)_z = J_z in a slot and zero current in a tooth. Half-cell source
integrals are separate because their radial lengths differ.
"""

from collections import defaultdict

import numpy as np

PROGRESS_REPORT_INTERVAL = 1000


class TeethSlotMMFCalculator:
    """Map the physical winding function onto the reluctance network."""

    def __init__(self):
        self.mesh_elements = []
        self.mmf_results = {}
        self.tooth_layers = 1
        self.angle_divider = 1
        self._layout_key = None
        self._sector = None
        self._is_tooth = None
        self._is_slot = None
        self._slot_fraction = None
        self._up_weight = None
        self._down_weight = None
        self._mp_key = None
        self._mp_cache = None

    def calculate_teeth_mmf(self, mesh_data, mesh_settings, mmf_calculator,
                            progress_callback=None, build_full=True):
        """Calculate signed radial half-cell impressed-field integrals.

        ``build_full=False`` omits per-element dictionaries during animation;
        the aligned up/down arrays contain exactly the same sources.
        """
        if progress_callback:
            progress_callback('Starting teeth and slot MMF calculation...')
        self.mesh_elements = mesh_data['mesh_elements']
        # These counts remain useful metadata; neither divides excitation.
        self.tooth_layers = mesh_settings.get('slot', 1)
        self.angle_divider = mesh_settings.get('angle_divider', 1)
        tooth_data = mmf_calculator.get_tooth_mmf_data()
        if not tooth_data or 'Resultant' not in tooth_data:
            raise RuntimeError('No tooth MMF data available from MMF calculation engine')
        tooth_values = tooth_data['Resultant']['tooth_mmf']
        machine_params = self._machine_params_from_mesh(mesh_data)
        if len(tooth_values) != machine_params['num_slots']:
            raise ValueError('Winding and mesh slot counts differ. Regenerate the mesh.')
        slot_values = self.calculate_slot_mmf_values(tooth_values, machine_params)
        self._ensure_layout(machine_params)
        up, down, source_tooth, source_slot = self._element_mmf_arrays(tooth_values)
        if build_full:
            mmf_data, region_stats = self._build_mmf_data(
                up, down, source_tooth, source_slot, progress_callback)
        else:
            mmf_data, region_stats = [], {}
        self.mmf_results = {
            'mmf_data': mmf_data,
            'element_mmf_up': up,
            'element_mmf_down': down,
            'statistics': {
                'total_elements': len(self.mesh_elements),
                'tooth_layers': self.tooth_layers,
                'region_distribution': dict(region_stats),
                'num_teeth': len(tooth_values),
                'num_slots': len(slot_values),
            },
            'tooth_mmf_values': tooth_values,
            'slot_mmf_values': slot_values,
            'machine_parameters': machine_params,
        }
        if progress_callback:
            progress_callback('Teeth and slot MMF calculation completed!')
        return self.mmf_results

    def _ensure_layout(self, machine_params):
        """Cache physical sectors, slot interpolation and half-cell weights."""
        elements = self.mesh_elements
        key = (id(elements), len(elements), machine_params['num_slots'],
               machine_params['slot_angle'], machine_params['slot_inner'],
               machine_params['slot_outer'])
        if key == self._layout_key:
            return
        count = len(elements)
        sector = np.full(count, -1, dtype=np.int64)
        is_tooth = np.zeros(count, dtype=bool)
        is_slot = np.zeros(count, dtype=bool)
        slot_fraction = np.zeros(count, dtype=float)
        up_weight = np.zeros(count, dtype=float)
        down_weight = np.zeros(count, dtype=float)
        num_slots = machine_params['num_slots']
        pitch = 360.0 / num_slots
        slot_arc = machine_params['slot_angle']
        tooth_arc = pitch - slot_arc
        denominator = (machine_params['slot_outer'] ** 2
                       - machine_params['slot_inner'] ** 2)
        for index, element in enumerate(elements):
            if element['material'] == 'Tooth':
                is_tooth[index] = True
            elif element['material'] == 'Slot':
                is_slot[index] = True
            else:
                continue
            theta = (element['theta_start'] + element['theta_end']) / 2 % 360
            sector[index] = int(theta / pitch) % num_slots
            local_angle = theta - sector[index] * pitch
            slot_fraction[index] = np.clip((local_angle - tooth_arc) / slot_arc,
                                           0.0, 1.0)
            rin, rout = element['rin'], element['rout']
            center = (rin + rout) / 2
            up_weight[index] = (rout ** 2 - center ** 2) / denominator
            down_weight[index] = (center ** 2 - rin ** 2) / denominator
        self._sector = sector
        self._is_tooth = is_tooth
        self._is_slot = is_slot
        self._slot_fraction = slot_fraction
        self._up_weight = up_weight
        self._down_weight = down_weight
        self._layout_key = key

    def _element_mmf_arrays(self, tooth_values):
        """Signed positive-radial H_imp integrals for each half-cell."""
        sector = self._sector
        values = np.asarray(tooth_values, dtype=float)
        in_tooth = self._is_tooth & (sector >= 0) & (sector < len(values))
        in_slot = self._is_slot & (sector >= 0) & (sector < len(values))
        function = np.zeros(len(sector), dtype=float)
        active = in_tooth | in_slot
        physical_sector = sector[active]
        left = values[physical_sector]
        right = values[(physical_sector + 1) % len(values)]
        function[active] = left + self._slot_fraction[active] * (right - left)
        return (-function * self._up_weight, -function * self._down_weight,
                in_tooth, in_slot)

    def _build_mmf_data(self, up_array, down_array, source_tooth, source_slot,
                        progress_callback=None):
        """Build export/UI records without changing the aligned array values."""
        mmf_data = []
        region_stats = defaultdict(int)
        total = len(self.mesh_elements)
        for index, element in enumerate(self.mesh_elements):
            if progress_callback and index and index % PROGRESS_REPORT_INTERVAL == 0:
                progress_callback(f'Processing elements... {int(index / total * 100)}% '
                                  f'({index:,}/{total:,})')
            tooth = int(self._sector[index]) if source_tooth[index] else -1
            slot = int(self._sector[index]) if source_slot[index] else -1
            mmf_data.append({
                'element_id': element['element_id'],
                'material': element['material'],
                'geometry': {key: element[key] for key in
                             ('rin', 'rout', 'theta_start', 'theta_end')},
                'mmf_values': {
                    'MMF_up': float(up_array[index]),
                    'MMF_down': float(down_array[index]),
                    'MMF_left': 0.0, 'MMF_right': 0.0,
                    'tooth_number': tooth, 'slot_number': slot,
                },
                'tooth_number': tooth, 'slot_number': slot,
            })
            region_stats[element['material']] += 1
        return mmf_data, region_stats

    @staticmethod
    def calculate_slot_mmf_values(tooth_values, machine_params):
        """MMF at each slot centre, between its two neighboring teeth."""
        count = machine_params['num_slots']
        if len(tooth_values) != count:
            raise ValueError('Tooth MMF values must match the physical slot count.')
        return [(tooth_values[k] + tooth_values[(k + 1) % count]) / 2
                for k in range(count)]

    def _machine_params_from_mesh(self, mesh_data):
        """Read physical geometry from the generated mesh's parameter record."""
        elements = self.mesh_elements
        params = mesh_data['params']
        key = (id(elements), len(elements), tuple(sorted(params.items())))
        if key != self._mp_key or self._mp_cache is None:
            self._mp_cache = self._compute_machine_params_from_mesh(mesh_data)
            self._mp_key = key
        return self._mp_cache

    def _compute_machine_params_from_mesh(self, mesh_data):
        params = mesh_data['params']
        count = int(params['num_slots'])
        pitch = 360.0 / count
        arc = float(params['slot_angle'])
        inner = float(params['stator_inner_radius'])
        outer = inner + float(params['slot_height'])
        if not 0 < arc < pitch or not 0 < inner < outer:
            raise ValueError('Invalid slot geometry for winding excitation.')
        return {
            'num_slots': count,
            'slot_pitch': pitch,
            'mesh_angle': mesh_data.get('mesh_stats', {}).get('mesh_angle', pitch),
            'slot_angle': arc,
            'slot_inner': inner,
            'slot_outer': outer,
        }
