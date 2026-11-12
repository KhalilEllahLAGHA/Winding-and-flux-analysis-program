"""Signed electrical belts, physical coil pairs and working-pole checks."""

import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt5.QtWidgets import QApplication

from core.connection_matrix import (build_winding_connection_matrix,
                                     generate_connection_matrix,
                                     phase_pattern_from_matrix)
from ui.stator_drawing import StatorDrawing


def phase_phasors(matrix, poles):
    complete = matrix[:3] + matrix[3:] if len(matrix) == 6 else matrix
    angles = np.arange(complete.shape[1]) * 2 * np.pi / complete.shape[1]
    return complete @ np.exp(-1j * (poles // 2) * angles)


class FractionalWindingTests(unittest.TestCase):
    def test_selected_fractional_cases_have_the_requested_balanced_working_harmonic(self):
        for slots, poles in ((6, 4), (12, 8), (24, 10), (12, 10), (30, 8)):
            for double in (False, True):
                with self.subTest(slots=slots, poles=poles, double=double):
                    matrix = build_winding_connection_matrix(
                        slots, poles, double, slots // poles)
                    phasors = phase_phasors(matrix, poles)
                    self.assertGreater(float(np.min(np.abs(phasors))), 1e-6)
                    np.testing.assert_allclose(
                        phasors / phasors[0],
                        np.exp(1j * np.radians([0, -120, 120])), atol=1e-12)

    def test_single_layer_uses_each_slot_once_in_opposite_current_coil_pairs(self):
        for slots, poles in ((6, 4), (12, 8), (24, 10), (36, 4)):
            span = slots // poles
            matrix = build_winding_connection_matrix(slots, poles, False, span)
            np.testing.assert_array_equal(np.abs(matrix).sum(axis=0), np.ones(slots))
            seen = set()
            cycles = math.gcd(slots, span)
            for start in range(cycles):
                cycle = [(start + k * span) % slots for k in range(slots // cycles)]
                for index in range(0, len(cycle), 2):
                    first, last = cycle[index:index + 2]
                    np.testing.assert_array_equal(matrix[:, first], -matrix[:, last])
                    self.assertNotIn(first, seen)
                    self.assertNotIn(last, seen)
                    seen.update((first, last))
            self.assertEqual(seen, set(range(slots)))

    def test_double_layer_return_sides_follow_the_selected_coil_span(self):
        for slots, poles, span in ((6, 4, 1), (12, 8, 1), (24, 10, 2),
                                   (36, 4, 6), (36, 4, 9), (36, 4, 18)):
            with self.subTest(slots=slots, poles=poles, span=span):
                matrix = build_winding_connection_matrix(slots, poles, True, span)
                np.testing.assert_array_equal(matrix[3:],
                                              -np.roll(matrix[:3], span, axis=1))

    def test_odd_uniform_span_cycles_have_a_genuine_topology_error(self):
        with self.assertRaisesRegex(ValueError, 'contain 9 slots, an odd number'):
            build_winding_connection_matrix(18, 4, False, 4)
        # The same machine does support a full double-layer return topology.
        matrix = build_winding_connection_matrix(18, 4, True, 4)
        self.assertGreater(float(np.min(np.abs(phase_phasors(matrix, 4)))), 0)

    def test_incompatible_three_phase_slot_axes_are_rejected(self):
        # 12 slots / 6 poles offer four distinct electrical slot directions,
        # which this equal-turn uniform-coil layout cannot make into balanced
        # nonzero phase axes separated by 120 degrees.
        with self.assertRaisesRegex(ValueError, 'balanced 6-pole three-phase'):
            build_winding_connection_matrix(12, 6, True, 2)

    def test_default_36_slot_4_pole_matrices_are_unchanged(self):
        # Two repetitions of the established six signed 3-slot phase belts.
        signed_belts = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0],
                                  [-1, 0, 0], [0, 0, 1], [0, -1, 0]]).T
        expected = np.tile(np.repeat(signed_belts, 3, axis=1), (1, 2))
        np.testing.assert_array_equal(
            build_winding_connection_matrix(36, 4, False, 9), expected)
        np.testing.assert_array_equal(
            build_winding_connection_matrix(36, 4, True, 9),
            np.vstack((expected, expected)))

    def test_full_electrical_period_pitch_remains_a_valid_zero_excitation_case(self):
        matrix = build_winding_connection_matrix(36, 4, True, 18)
        np.testing.assert_array_equal(matrix[:3] + matrix[3:], np.zeros((3, 36)))

    def test_supplied_phase_pattern_must_match_its_topology(self):
        matrix = build_winding_connection_matrix(12, 8, True, 1)
        pattern = phase_pattern_from_matrix(matrix)
        np.testing.assert_array_equal(
            generate_connection_matrix(pattern, list('ABC'), True, 8, 1), matrix)
        pattern[0] = ('C', pattern[0][1])
        with self.assertRaisesRegex(ValueError, 'phase pattern does not match'):
            generate_connection_matrix(pattern, list('ABC'), True, 8, 1)

    def test_top_only_legacy_pattern_derives_its_return_from_the_coil_span(self):
        matrix = build_winding_connection_matrix(12, 8, True, 1)
        pattern = [(top, None) for top, _ in phase_pattern_from_matrix(matrix)]
        np.testing.assert_array_equal(
            generate_connection_matrix(pattern, list('ABC'), True, 8, 1), matrix)


class DrawingLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_diagram_and_calculation_use_the_same_fractional_slot_phases(self):
        drawing = StatorDrawing()
        try:
            for slots, poles in ((6, 4), (12, 8), (24, 10)):
                for double in (False, True):
                    with self.subTest(slots=slots, poles=poles, double=double):
                        span = slots // poles
                        drawing.update_parameters(slots, poles, span, double)
                        self.assertIsNone(drawing.winding_error)
                        calculated = generate_connection_matrix(
                            drawing.winding_pattern, list('ABC'), double, poles, span)
                        np.testing.assert_array_equal(calculated, drawing.winding_matrix)
        finally:
            drawing.close()

    def test_unsupported_single_layer_is_neutral_and_explains_why(self):
        drawing = StatorDrawing()
        try:
            drawing.update_parameters(18, 4, 4, False)
            self.assertIn('odd number', drawing.winding_error)
            self.assertIsNone(drawing.winding_matrix)
            self.assertEqual(drawing.winding_pattern, [(None, None)] * 18)
            with self.assertRaisesRegex(ValueError, 'odd number'):
                generate_connection_matrix(drawing.winding_pattern,
                                           list('ABC'), False, 4, 4)
        finally:
            drawing.close()


if __name__ == '__main__':
    unittest.main()
