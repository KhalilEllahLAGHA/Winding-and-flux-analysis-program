"""Physical coil pairing and field-line direction invariants."""

import math
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import matplotlib
matplotlib.use('Agg')
from matplotlib.figure import Figure
import numpy as np

from core.connection_matrix import generate_connection_matrix
from ui.flux_visualization import FluxDensityVisualizer


def winding_pattern(span, slots=36, poles=4):
    def phase(index):
        angle = ((index % slots) * 360 * poles / slots) % 360
        return 'A' if angle < 120 else 'C' if angle < 240 else 'B'
    return [(phase(i), phase(i - span)) for i in range(slots)]


class CoilPairingTests(unittest.TestCase):
    def test_every_coil_has_an_opposite_return_side_at_its_span(self):
        for span in (1, 3, 6, 8, 9, 10, 12, 18):
            with self.subTest(span=span):
                matrix = generate_connection_matrix(winding_pattern(span),
                                                     list('ABC'), True, 4,
                                                     coil_span=span)
                np.testing.assert_array_equal(matrix[3:],
                                              -np.roll(matrix[:3], span, axis=1))
                np.testing.assert_array_equal(matrix.sum(axis=1), np.zeros(6))

    def test_electrical_full_period_coil_span_cancels_its_excitation(self):
        matrix = generate_connection_matrix(winding_pattern(18), list('ABC'),
                                             True, 4, coil_span=18)
        np.testing.assert_array_equal(matrix[:3] + matrix[3:], np.zeros((3, 36)))

    def test_fundamental_tracks_the_analytic_pitch_factor(self):
        full_pitch = generate_connection_matrix(winding_pattern(9), list('ABC'),
                                                True, 4, coil_span=9)
        # Use one phase: the three-phase spatial winding sum is not its
        # excitation for a particular electrical current angle.
        full_amplitude = abs(np.fft.rfft(full_pitch[0] + full_pitch[3])[2])
        for span in (1, 3, 6, 8, 10, 12, 18):
            matrix = generate_connection_matrix(winding_pattern(span),
                                                 list('ABC'), True, 4,
                                                 coil_span=span)
            amplitude = abs(np.fft.rfft(matrix[0] + matrix[3])[2])
            expected = abs(math.sin(math.pi * span / 18))
            self.assertAlmostEqual(amplitude / full_amplitude, expected, places=12)

    def test_default_connection_matrix_uses_full_pitch(self):
        actual = generate_connection_matrix(winding_pattern(9), list('ABC'), True, 4)
        expected = generate_connection_matrix(winding_pattern(9), list('ABC'),
                                               True, 4, coil_span=9)
        np.testing.assert_array_equal(actual, expected)


class FieldLineDirectionTests(unittest.TestCase):
    def setUp(self):
        self.visualizer = FluxDensityVisualizer()
        self.element = {'element_id': 1, 'rin': 40.0, 'rout': 40.1,
                        'theta_start': -1.0, 'theta_end': 1.0,
                        'center_r': 40.05, 'center_theta': 0.0,
                        'material': 'Air Gap'}
        self.geometry = self.visualizer._get_mesh_geometry([self.element])

    def test_branch_flux_components_use_their_own_face_areas(self):
        length = 0.11
        radial_area = 0.04005 * math.radians(2) * length
        tangential_area = 0.04005 * math.log(40.1 / 40.0) * length
        # Br=2 T, Btheta=3 T on a thin polar cell. Raw face fluxes have
        # very different magnitudes even though the B components do not.
        branches = {1: {'up': 2 * radial_area, 'down': -2 * radial_area,
                        'right': 3 * tangential_area,
                        'left': -3 * tangential_area}}
        bx, by = self.visualizer._extract_branch_flux_vectors(
            branches, self.geometry, {'axial_length': 110})
        self.assertAlmostEqual(bx[0], 2.0, places=12)
        self.assertAlmostEqual(by[0], 3.0, places=12)

    def test_cartesian_rotation_preserves_signed_field_direction(self):
        element = dict(self.element, theta_start=89, theta_end=91,
                       center_theta=90)
        geometry = self.visualizer._get_mesh_geometry([element])
        _, bx, by = self.visualizer._extract_flux_arrays(
            {1: {'Br': 2, 'Btheta': 3, 'B_magnitude': math.sqrt(13)}}, geometry)
        self.assertAlmostEqual(bx[0], -3.0)
        self.assertAlmostEqual(by[0], 2.0)

    def test_field_line_renderer_prefers_density_vectors_and_tesla_scale(self):
        figure = Figure()
        ax = figure.add_subplot(111)
        density = {1: {'Br': 2, 'Btheta': 3, 'B_magnitude': math.sqrt(13)}}
        captured = {}

        def grid(_geometry, bx, by, _limit, _resolution):
            captured['bx'] = bx.copy()
            captured['by'] = by.copy()
            return (np.linspace(-50, 50, 10), np.linspace(-50, 50, 10),
                    np.full((10, 10), 2.0), np.full((10, 10), 3.0))

        with patch.object(self.visualizer, '_vectors_to_grid', side_effect=grid), \
                patch.object(self.visualizer, 'draw_machine_cross_section_background'), \
                patch.object(self.visualizer, '_extract_branch_flux_vectors',
                             side_effect=AssertionError('Must use physical density')):
            success = self.visualizer.generate_flux_lines_visualisation(
                ax, figure, {'mesh_elements': [self.element]},
                {1: {'up': 999}}, {'stator_outer_radius': 50, 'shaft_radius': 0},
                flux_densities=density)
        self.assertTrue(success)
        np.testing.assert_allclose(captured['bx'], [2.0])
        np.testing.assert_allclose(captured['by'], [3.0])
        self.assertEqual(figure.axes[-1].get_ylabel(), 'Flux Density |B| (T)')


if __name__ == '__main__':
    unittest.main()
