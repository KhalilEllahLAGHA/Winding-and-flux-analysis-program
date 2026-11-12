"""Conservative planar flux contours and annular topology."""

import unittest
from unittest.mock import patch

import numpy as np

from core.flux_contours import reconstruct_flux_potential
from matplotlib.figure import Figure
from ui.flux_visualization import FluxDensityVisualizer


def field_from_potential(potential, radii, angles, length_m=0.11):
    """Integrate the exact curl of an analytic Az over each cell face."""
    elements, branches = [], {}
    for i in range(len(radii) - 1):
        for j in range(len(angles) - 1):
            eid = len(elements) + 1
            elements.append(dict(element_id=eid, rin=radii[i], rout=radii[i + 1],
                                 theta_start=angles[j], theta_end=angles[j + 1],
                                 material='Air Gap'))
            a00, a01 = potential[i, j:j + 2]
            a10, a11 = potential[i + 1, j:j + 2]
            branches[eid] = dict(up=(a11 - a10) * length_m,
                                 down=-(a01 - a00) * length_m,
                                 left=(a10 - a00) * length_m,
                                 right=-(a11 - a01) * length_m)
    return {'mesh_elements': elements}, branches


class FluxContourTests(unittest.TestCase):
    def setUp(self):
        self.radii = np.array([10., 13., 14., 20., 25.])
        self.angles = np.linspace(0, 360, 49)
        radius, angle = np.meshgrid(self.radii, np.radians(self.angles), indexing='ij')
        self.potential = ((radius - 10) * (25 - radius) * np.cos(2 * angle) * 1e-4
                          + 0.003 * np.log(radius / 10))

    def test_recovers_multipole_and_circulating_flux_with_correct_scale_and_sign(self):
        mesh, branches = field_from_potential(self.potential, self.radii, self.angles)
        result = reconstruct_flux_potential(mesh, branches, 110)
        np.testing.assert_allclose(result.potential, self.potential, atol=1e-15)
        self.assertLess(result.relative_residual, 1e-12)
        np.testing.assert_array_equal(result.potential[:, 0], result.potential[:, -1])
        self.assertAlmostEqual(np.ptp(result.potential[0]), 0)
        self.assertAlmostEqual(np.ptp(result.potential[-1]), 0)

    def test_shuffled_mesh_and_json_branch_keys_preserve_contours(self):
        mesh, branches = field_from_potential(self.potential, self.radii, self.angles)
        mesh['mesh_elements'].reverse()
        result = reconstruct_flux_potential(mesh, {str(k): v for k, v in branches.items()}, 110)
        np.testing.assert_allclose(result.potential, self.potential, atol=1e-15)

    def test_zero_field_is_finite_and_has_no_invented_potential(self):
        mesh, branches = field_from_potential(np.zeros_like(self.potential), self.radii, self.angles)
        result = reconstruct_flux_potential(mesh, branches, 110)
        np.testing.assert_array_equal(result.potential, np.zeros_like(self.potential))
        self.assertEqual(result.relative_residual, 0)

    def test_nonconservative_input_reports_reconstruction_residual(self):
        mesh, branches = field_from_potential(self.potential, self.radii, self.angles)
        branches[80]['up'] += 0.001
        result = reconstruct_flux_potential(mesh, branches, 110)
        self.assertGreater(result.relative_residual, 0.01)
        self.assertTrue(np.isfinite(result.potential).all())

    def test_incomplete_domain_and_missing_flux_raise_clear_errors(self):
        mesh, branches = field_from_potential(self.potential, self.radii, self.angles)
        with self.assertRaisesRegex(ValueError, 'missing'):
            reconstruct_flux_potential(mesh, {}, 110)
        mesh['mesh_elements'].pop()
        with self.assertRaisesRegex(ValueError, 'complete'):
            reconstruct_flux_potential(mesh, branches, 110)

    def test_one_radial_ring_retains_circulating_flux(self):
        radii = np.array([10., 25.])
        potential = np.broadcast_to(np.array([0., 0.004])[:, None], (2, len(self.angles)))
        mesh, branches = field_from_potential(potential, radii, self.angles)
        result = reconstruct_flux_potential(mesh, branches, 110)
        np.testing.assert_allclose(result.potential, potential, atol=1e-15)

    def test_complete_mesh_renderer_uses_equal_potential_levels_without_vector_interpolation(self):
        mesh, branches = field_from_potential(self.potential, self.radii, self.angles)
        figure = Figure()
        ax = figure.add_subplot(111)
        visualizer = FluxDensityVisualizer()
        with patch.object(ax, 'streamplot', side_effect=AssertionError('Expected Az contours')), \
                patch.object(visualizer, '_vectors_to_grid',
                             side_effect=AssertionError('Expected native mesh')):
            success = visualizer.generate_flux_lines_visualisation(
                ax, figure, mesh, branches,
                {'axial_length': 110, 'shaft_radius': 10, 'stator_outer_radius': 25},
                contour_count=24)
        self.assertTrue(success)
        self.assertEqual(figure._flux_contour_info['count'], 24)
        self.assertGreater(figure._flux_contour_info['flux_step_wb'], 0)
        contour = ax.collections[-1]
        np.testing.assert_allclose(np.diff(contour.levels), np.diff(contour.levels)[0])

    def test_zero_field_renderer_succeeds_without_drawing_flux_lines(self):
        mesh, branches = field_from_potential(np.zeros_like(self.potential), self.radii, self.angles)
        figure = Figure()
        ax = figure.add_subplot(111)
        success = FluxDensityVisualizer().generate_flux_lines_visualisation(
            ax, figure, mesh, branches, {'axial_length': 110})
        self.assertTrue(success)
        self.assertEqual(figure._flux_contour_info['count'], 0)
        self.assertFalse(ax.collections)


if __name__ == '__main__':
    unittest.main()
