"""Physical winding/source invariants independent of a FEMM installation."""

import math
import unittest

import numpy as np

from core.femm_validation import slot_ampere_turns
from core.meshing_engine import MeshingEngine
from core.mmf_engine import MMFCalculationEngine, _split_double_layer_rows
from core.teeth_slot_mmf import TeethSlotMMFCalculator
from utils.constants import DEFAULT_MACHINE_PARAMS


def balanced_matrix(slots=36):
    """Known 4-pole 36-slot or 2-pole 6-slot three-phase winding."""
    group_size = 3 if slots == 36 else 1
    matrix = np.zeros((3, slots), dtype=int)
    for slot in range(slots):
        group = slot // group_size
        phase = (0, 2, 1)[group % 3]
        matrix[phase, slot] = 1 if group % 2 == 0 else -1
    return matrix


def engine_for(matrix=None):
    engine = MMFCalculationEngine()
    engine.turns = 20
    engine.phase_current_a = 2
    engine.wt_angle_deg = 28
    matrix = balanced_matrix() if matrix is None else matrix
    engine.slot_arc_deg = 180 / matrix.shape[1]
    engine.set_connection_matrix(matrix)
    return engine


def sources(*, arc=5.0, divider=3, layers=4, slots=36, build_full=True):
    params = dict(DEFAULT_MACHINE_PARAMS, slot_angle=arc, num_slots=slots)
    settings = dict(rotor=1, airgap=1, slot=layers, stator=1,
                    angle_divider=divider)
    mesh = MeshingEngine().generate_mesh(params, settings)
    calculator = TeethSlotMMFCalculator()
    engine = engine_for(balanced_matrix(slots))
    result = calculator.calculate_teeth_mmf(mesh, settings, engine,
                                           build_full=build_full)
    return mesh, settings, calculator, engine, result


class WindingFunctionTests(unittest.TestCase):
    def test_each_slot_ni_is_jump_between_its_two_adjacent_teeth(self):
        engine = engine_for()
        function = np.asarray(engine.get_tooth_mmf_data()['Resultant']['tooth_mmf'])
        np.testing.assert_allclose(np.roll(function, -1) - function,
                                   slot_ampere_turns(engine), atol=1e-12)
        self.assertAlmostEqual(float(function.mean()), 0.0)

    def test_true_double_layer_phase_and_sign_are_preserved(self):
        top = balanced_matrix(6)
        bottom = np.roll(top, 1, axis=1)
        matrix = np.vstack((top, bottom))
        actual_top, actual_bottom = _split_double_layer_rows(matrix)
        np.testing.assert_array_equal(actual_top, top)
        np.testing.assert_array_equal(actual_bottom, bottom)
        engine = engine_for(matrix)
        function = np.asarray(engine.get_tooth_mmf_data()['Resultant']['tooth_mmf'])
        np.testing.assert_allclose(np.roll(function, -1) - function,
                                   slot_ampere_turns(engine), atol=1e-12)

    def test_mmf_plot_uses_same_tooth_origin_as_machine_mesh(self):
        engine = engine_for(balanced_matrix(6))
        phase_function = engine._tooth_mmf_from_phase(
            engine.matrix[0] * engine.phase_current_a * engine.turns / 2)
        angles, values = engine.get_profile_data('A')
        self.assertEqual(angles[0], 0.0)
        self.assertAlmostEqual(values[0], phase_function[0])
        first_tooth = np.argmin(abs(angles - 15.0))
        self.assertAlmostEqual(values[first_tooth], phase_function[0])
        first_slot = np.argmin(abs(angles - 45.0))
        self.assertAlmostEqual(values[first_slot],
                               (phase_function[0] + phase_function[1]) / 2)

    def test_non_closing_phase_winding_is_rejected(self):
        matrix = balanced_matrix(6)
        matrix[0, 0] = 0
        with self.assertRaisesRegex(ValueError, 'balanced'):
            engine_for(matrix)

    def test_a_coil_return_in_the_other_layer_closes_the_complete_phase(self):
        top = balanced_matrix(6)
        top[0, 0] = 0
        matrix = np.vstack((top, -np.roll(top, 1, axis=1)))
        engine = engine_for(matrix)
        function = np.asarray(engine.get_tooth_mmf_data()['Resultant']['tooth_mmf'])
        np.testing.assert_allclose(np.roll(function, -1) - function,
                                   slot_ampere_turns(engine), atol=1e-12)
        for phase in ('A', 'B', 'C'):
            _, combined = engine.get_profile_data(phase)
            _, upper = engine.get_profile_data(phase, 'top')
            _, lower = engine.get_profile_data(phase, 'bot')
            np.testing.assert_allclose(combined, upper + lower, atol=1e-12)


class ImpressedFieldTests(unittest.TestCase):
    def test_slot_count_and_source_poles_do_not_depend_on_angular_refinement(self):
        # Non-half-pitch widths exposed the original mesh-cell-as-slot bug;
        # 3° / divider 10 also exposed the rounded-angle collision bug.
        for arc, divider in ((5, 1), (5, 3), (4, 3), (3, 10), (7, 3)):
            with self.subTest(arc=arc, divider=divider):
                mesh, _, calculator, engine, result = sources(
                    arc=arc, divider=divider, layers=1, build_full=False)
                self.assertEqual(result['machine_parameters']['num_slots'], 36)
                self.assertEqual(len(result['slot_mmf_values']), 36)
                active = calculator._is_tooth | calculator._is_slot
                theta = np.array([e['center_theta'] for e in mesh['mesh_elements']])
                np.testing.assert_array_equal(calculator._sector[active],
                                              (theta[active] // 10).astype(int))
                # Integrate Himp over the full radial band to recover -F.
                winding = -(result['element_mmf_up'][active]
                            + result['element_mmf_down'][active])
                dominant = np.argmax(abs(np.fft.rfft(winding))[1:]) + 1
                self.assertEqual(dominant, 2)

    def test_each_tooth_and_slot_have_the_expected_integrated_source(self):
        for layers in (1, 2, 7):
            mesh, _, calculator, engine, result = sources(layers=layers)
            function = np.asarray(result['tooth_mmf_values'])
            ni = slot_ampere_turns(engine)
            lines = {}
            for index, element in enumerate(mesh['mesh_elements']):
                if element['material'] not in ('Tooth', 'Slot'):
                    continue
                angle = element['center_theta']
                lines[angle] = lines.get(angle, 0.0) + (
                    result['element_mmf_up'][index]
                    + result['element_mmf_down'][index])
            for angle, source_integral in lines.items():
                sector = int(angle // 10)
                fraction = np.clip((angle % 10 - 5) / 5, 0, 1)
                expected = function[sector] + fraction * ni[sector]
                self.assertAlmostEqual(source_integral, -expected, places=10)

    def test_ampere_loop_matches_uniform_slot_current_for_partial_radial_area(self):
        mesh, _, _, engine, result = sources(layers=5)
        inner = mesh['params']['stator_inner_radius']
        outer = inner + mesh['params']['slot_height']
        denominator = outer ** 2 - inner ** 2
        slot_zero = [(i, e) for i, e in enumerate(mesh['mesh_elements'])
                     if e['material'] == 'Slot' and e['center_theta'] < 10]
        angles = sorted({e['center_theta'] for _, e in slot_zero})
        radial_bounds = sorted({e['rin'] for _, e in slot_zero})
        r1, r2 = radial_bounds[1], radial_bounds[4]
        left_angle, right_angle = angles[0], angles[-1]
        integrals = {}
        for angle in (left_angle, right_angle):
            integrals[angle] = sum(
                result['element_mmf_up'][i] + result['element_mmf_down'][i]
                for i, e in slot_zero if e['center_theta'] == angle
                and e['rin'] >= r1 - 1e-9 and e['rout'] <= r2 + 1e-9)
        # Positive-z contour: outwards on the smaller angle, back inwards
        # on the larger angle. Angular legs have zero impressed Htheta.
        circulation = integrals[left_angle] - integrals[right_angle]
        expected = (slot_ampere_turns(engine)[0]
                    * (right_angle - left_angle) / 5
                    * (r2 ** 2 - r1 ** 2) / denominator)
        self.assertAlmostEqual(circulation, expected, places=10)

    def test_half_cell_integrals_use_radial_geometry_and_full_fast_paths_agree(self):
        mesh, settings, calculator, engine, full = sources(layers=3)
        self.assertNotIn('element_mmf_ud', full)
        active = calculator._is_tooth | calculator._is_slot
        self.assertGreater(float(np.max(abs(full['element_mmf_up'][active]
                                            - full['element_mmf_down'][active]))),
                           1e-6)
        for index, record in enumerate(full['mmf_data']):
            self.assertEqual(record['mmf_values']['MMF_up'],
                             full['element_mmf_up'][index])
            self.assertEqual(record['mmf_values']['MMF_down'],
                             full['element_mmf_down'][index])
        fast = calculator.calculate_teeth_mmf(mesh, settings, engine, build_full=False)
        np.testing.assert_array_equal(full['element_mmf_up'], fast['element_mmf_up'])
        np.testing.assert_array_equal(full['element_mmf_down'], fast['element_mmf_down'])
        self.assertEqual(fast['mmf_data'], [])


if __name__ == '__main__':
    unittest.main()
