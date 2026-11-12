"""Analytic circuit/field invariants independent of FEMM and its output."""

import math
from unittest import TestCase, main
from unittest.mock import patch

import numpy as np
from scipy.sparse import csr_matrix

from core.flux_solver import FluxCalculator, OPPOSITE_DIRECTION
from core.meshing_engine import MeshingEngine
from core.reluctance_calculator import ReluctanceCalculator
from utils.constants import DEFAULT_MACHINE_PARAMS, MU0


def cell(rin=10.0, rout=20.0, start=0.0, end=30.0, eid=1):
    return {'rin': rin, 'rout': rout, 'theta_start': start, 'theta_end': end,
            'material': 'Air Gap', 'element_id': eid,
            'center_r': (rin + rout) / 2, 'center_theta': (start + end) / 2}


def reluctances_for_cell(element, length=100.0):
    calculator = ReluctanceCalculator()
    calculator.material_permeabilities = {'ur_air': 1.0}
    return calculator.calculate_element_reluctance(element, length / 1000)


def make_network():
    mesh = MeshingEngine().generate_mesh(
        dict(DEFAULT_MACHINE_PARAMS, num_slots=6, slot_angle=30.0),
        {'rotor': 2, 'airgap': 3, 'slot': 2, 'stator': 2, 'angle_divider': 1})
    result = ReluctanceCalculator().calculate_reluctances(
        mesh, {'ur_air': 1.0, 'ur_stator': 1000.0, 'ur_rotor': 1000.0},
        {'axial_length': 100.0})
    return mesh, result


class FieldReconstructionTests(TestCase):
    def test_thin_radial_rings_keep_distinct_neighbors(self):
        solver = FluxCalculator()
        solver.reluctance_data = [
            {'element_id': 1 + ring * 2 + angle,
             'center': {'r': 10.0 + ring * 0.0002, 'theta': 90.0 + angle * 180}}
            for ring in range(3) for angle in range(2)]
        neighbors = solver.build_neighbor_connectivity()
        self.assertEqual(neighbors[1]['up'], 3)
        self.assertEqual(neighbors[3]['up'], 5)
        self.assertEqual(neighbors[1]['right'], 2)
        self.assertEqual(neighbors[3]['right'], 4)

    def reconstruct(self, element, branches, length=100.0):
        solver = FluxCalculator()
        solver.reluctance_data = [{
            'element_id': element['element_id'], 'geometry': element,
            'center': {'r': element['center_r'], 'theta': element['center_theta']},
        }]
        solver._cached_geometry = solver._build_geometry_arrays()
        solver._branch_flux_array = np.asarray([branches], dtype=float)
        # The per-cell angle must be used even if a global angle is absent.
        return solver.compute_flux_densities(
            {'machine_parameters': {'axial_length': length}})[element['element_id']]

    def test_constant_radial_field_is_averaged_without_factor_two(self):
        element = cell()
        br = 1.7
        angle = math.radians(30)
        length = 0.1
        result = self.reconstruct(element, [
            br * 0.020 * angle * length,
            -br * 0.010 * angle * length, 0.0, 0.0])
        self.assertAlmostEqual(result['Br'], br)
        self.assertAlmostEqual(result['Btheta'], 0.0)

    def test_conserved_radial_flux_recovers_inverse_radius_field(self):
        element = cell()
        c = 0.025  # Br(r) = c/r in metres, divergence-free in an annulus.
        flux = c * math.radians(30) * 0.1
        result = self.reconstruct(element, [flux, -flux, 0.0, 0.0])
        self.assertAlmostEqual(result['Br'], c / 0.015)

    def test_increasing_theta_flux_has_positive_center_btheta(self):
        element = cell()
        c = 0.030  # Btheta(r)=c/r for a potential linear in theta.
        flux = c * 0.1 * math.log(20 / 10)
        result = self.reconstruct(element, [0.0, 0.0, -flux, flux])
        self.assertAlmostEqual(result['Btheta'], c / 0.015)
        self.assertAlmostEqual(result['B_magnitude'], c / 0.015)

    def test_zero_flux_has_zero_field(self):
        result = self.reconstruct(cell(), [0.0] * 4)
        self.assertEqual(result['B_magnitude'], 0.0)


class ReluctancePhysicsTests(TestCase):
    def test_radial_halves_match_arithmetic_node_position(self):
        result = reluctances_for_cell(cell())
        scale = math.radians(30) * MU0 * 0.1
        self.assertAlmostEqual(result['R_down'] * scale, math.log(15 / 10))
        self.assertAlmostEqual(result['R_up'] * scale, math.log(20 / 15))
        self.assertAlmostEqual((result['R_up'] + result['R_down']) * scale,
                               math.log(20 / 10))

    def test_nonuniform_radial_link_matches_analytic_log_integral(self):
        inner = reluctances_for_cell(cell(10, 20))
        outer = reluctances_for_cell(cell(20, 23))
        actual = inner['R_up'] + outer['R_down']
        expected = math.log(21.5 / 15) / (math.radians(30) * MU0 * 0.1)
        self.assertAlmostEqual(actual / expected, 1.0)

    def test_angular_halves_match_integrated_inverse_radius_field(self):
        result = reluctances_for_cell(cell())
        expected = math.radians(30) / (MU0 * 0.1 * math.log(20 / 10))
        self.assertAlmostEqual((result['R_left'] + result['R_right']) / expected, 1.0)

    def test_invalid_dimensions_and_permeability_are_rejected(self):
        for element in (cell(0, 20), cell(20, 10), cell(end=0), cell(rout=math.nan)):
            with self.subTest(element=element), self.assertRaises(ValueError):
                reluctances_for_cell(element)
        calculator = ReluctanceCalculator()
        for value in (0, -1, math.inf, math.nan):
            calculator.material_permeabilities = {'ur_air': value}
            with self.subTest(mu=value), self.assertRaises(ValueError):
                calculator.calculate_element_reluctance(cell(), 0.1)


class NetworkConservationTests(TestCase):
    def assert_conservative(self, solver, result):
        scale = max(abs(v) for branch in result['branch_fluxes'].values()
                    for v in branch.values())
        for eid, branch in result['branch_fluxes'].items():
            self.assertLessEqual(abs(sum(branch.values())), max(scale * 1e-7, 1e-18))
            for direction, flux in branch.items():
                neighbor = solver.neighbors[eid][direction]
                if neighbor is None:
                    self.assertEqual(flux, 0.0)
                else:
                    opposite = result['branch_fluxes'][neighbor][OPPOSITE_DIRECTION[direction]]
                    self.assertAlmostEqual(flux + opposite, 0.0, delta=max(scale * 1e-12, 1e-18))

    def test_asymmetric_half_sources_preserve_kcl_and_shared_branch_flux(self):
        _, reluctances = make_network()
        n = len(reluctances['reluctance_data'])
        indices = np.arange(n, dtype=float)
        mmf = {'mmf_data': [], 'element_mmf_up': np.sin(indices) * 2,
               'element_mmf_down': np.cos(indices) * 3}
        solver = FluxCalculator()
        result = solver.calculate_flux_distribution(reluctances, mmf, {'tolerance': 1e-10})
        self.assertEqual(result['potentials'][0], 0.0)
        self.assertLess(result['solver_info']['relative_residual'], 1e-8)
        self.assert_conservative(solver, result)
        # A constant gauge shift cannot change a physical branch flux.
        expected = np.copy(solver._branch_flux_array)
        solver.potentials += 127.0
        solver.compute_branch_fluxes()
        np.testing.assert_allclose(solver._branch_flux_array, expected,
                                   atol=1e-16, rtol=1e-10)

    def test_tangential_dictionary_sources_are_included_in_rhs(self):
        _, reluctances = make_network()
        mmf = {'mmf_data': [
            {'element_id': data['element_id'],
             'mmf_values': {'MMF_left': math.sin(i), 'MMF_right': math.cos(i)}}
            for i, data in enumerate(reluctances['reluctance_data'])]}
        solver = FluxCalculator()
        result = solver.calculate_flux_distribution(reluctances, mmf, {'tolerance': 1e-10})
        self.assert_conservative(solver, result)

    def test_symmetric_fast_path_and_explicit_halves_agree(self):
        _, reluctances = make_network()
        ud = np.sin(np.arange(len(reluctances['reluctance_data'])))
        solver = FluxCalculator()
        fast = solver.calculate_flux_distribution(
            reluctances, {'mmf_data': [], 'element_mmf_ud': ud}, {'tolerance': 1e-10})
        explicit = solver.calculate_flux_distribution(
            reluctances, {'mmf_data': [], 'element_mmf_up': ud, 'element_mmf_down': ud},
            {'tolerance': 1e-10})
        np.testing.assert_allclose(fast['potentials'], explicit['potentials'], atol=1e-12)
        self.assertIsNotNone(solver._cached_reduced_matrix)

    def test_zero_source_has_zero_field_and_finite_residual(self):
        _, reluctances = make_network()
        result = FluxCalculator().calculate_flux_distribution(reluctances, {'mmf_data': []})
        np.testing.assert_array_equal(result['potentials'], 0.0)
        self.assertEqual(result['statistics']['max_flux_density'], 0.0)
        self.assertEqual(result['solver_info']['relative_residual'], 0.0)

    def test_nonconverged_solution_is_not_published(self):
        solver = FluxCalculator()
        matrix = csr_matrix([[1.0, -1.0], [-1.0, 1.0]])
        with patch('core.flux_solver.cg', return_value=(np.zeros(1), 5)):
            with self.assertRaisesRegex(RuntimeError, 'did not converge'):
                solver._solve_linear_system(matrix, np.array([1.0, -1.0]), 1e-6)

    def test_inaccurate_or_nonfinite_success_code_is_rejected(self):
        matrix = csr_matrix([[1.0, -1.0], [-1.0, 1.0]])
        for value in (0.0, math.nan, math.inf):
            with self.subTest(value=value), patch(
                    'core.flux_solver.cg', return_value=(np.array([value]), 0)):
                with self.assertRaisesRegex(RuntimeError, 'did not converge'):
                    FluxCalculator()._solve_linear_system(
                        matrix, np.array([1.0, -1.0]), 1e-6)

    def test_unbalanced_closed_network_sources_are_rejected(self):
        matrix = csr_matrix([[1.0, -1.0], [-1.0, 1.0]])
        with self.assertRaisesRegex(ValueError, 'unbalanced'):
            FluxCalculator()._solve_linear_system(matrix, np.array([1.0, 0.0]), 1e-6)


if __name__ == '__main__':
    main()
