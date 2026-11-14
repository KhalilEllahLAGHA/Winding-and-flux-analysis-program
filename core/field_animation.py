"""Compact, continuous animation of the prescribed-linear magnetic model.

With fixed geometry/permeability and sinusoidal excitation, each signed field
component is B(0)*cos(Wt) + B(90)*sin(Wt). Magnitudes are evaluated AFTER combining
the signed components. Az is linear too, so equal-Az contours retain the same
conservative reconstruction as the static view. Machine symmetry is checked
against the network before reusing its response for winding comparisons.
"""

from copy import deepcopy
from dataclasses import dataclass
import time

import contourpy
import numpy as np

from core.flux_contours import (arrowhead_paths, flux_direction_arrows,
                                reconstruct_flux_potential)
from core.flux_solver import FluxCalculator, NEGLIGIBLE_FLUX_WB
from core.reluctance_calculator import ReluctanceCalculator
from core.teeth_slot_mmf import TeethSlotMMFCalculator


def _joined_paths(paths):
    pieces = []
    for path in paths:
        if len(path):
            pieces.extend((path, np.full((1, 2), np.nan)))
    return np.concatenate(pieces) if pieces else np.empty((0, 2))


class FieldPreparationCache:
    """Reuse one network for serialized preparations with different windings."""

    def __init__(self, direct_winding_updates=False):
        self._key = None
        self._reluctance = None
        self._solver = None
        self.direct_winding_updates = direct_winding_updates
        self._response_count = None
        self._response = None

    def network(self, mesh, materials, axial_length_mm):
        cells = tuple((e.get('element_id', e.get('id')), e['rin'], e['rout'],
                       e['theta_start'], e['theta_end'], e['material'])
                      for e in mesh['mesh_elements'])
        key = (cells, tuple(sorted(materials.items())), float(axial_length_mm))
        reused = key == self._key
        if not reused:
            reluctance = ReluctanceCalculator().calculate_reluctances(
                mesh, dict(materials), {'axial_length': axial_length_mm})
            self._key, self._reluctance = key, reluctance
            self._solver = FluxCalculator()
            self._response_count = self._response = None
        return self._reluctance, self._solver, reused

    def prepare_response(self, mesh, settings, mmf):
        """Prepare one tooth response only when the network is slot-periodic."""
        count = mesh['params']['num_slots']
        if not self.direct_winding_updates or self._response_count == count:
            return
        self._response_count = count
        elements = mesh['mesh_elements']
        radii = np.unique([e['rin'] for e in elements])
        angles = np.unique([e['theta_start'] for e in elements])
        nr, nt = len(radii), len(angles)
        if nt % count or nr * nt != len(elements):
            return
        indices = np.empty((nr, nt), dtype=int)
        for index, element in enumerate(elements):
            indices[np.searchsorted(radii, element['rin']),
                    np.searchsorted(angles, element['theta_start'])] = index
        step = nt // count
        permutation = np.empty(len(elements), dtype=int)
        permutation[indices.ravel()] = np.roll(indices, step, axis=1).ravel()
        materials = np.asarray([element['material'] for element in elements])
        if np.any(materials != materials[permutation]):
            return

        class ToothSource:
            def __init__(self, tooth):
                self.values = np.zeros(count)
                self.values[tooth] = 1.0

            def get_tooth_mmf_data(self):
                return {'Resultant': {'tooth_mmf': self.values}}

        solver = self._solver
        rhs_vectors = []
        for tooth in (0, 1):
            source = mmf.calculate_teeth_mmf(mesh, settings, ToothSource(tooth), build_full=False)
            solver.reluctance_data = self._reluctance['reluctance_data']
            solver.mmf_data = []
            solver._element_mmf_ud = None
            solver._element_mmf_up = source['element_mmf_up']
            solver._element_mmf_down = source['element_mmf_down']
            matrix, rhs = solver._get_system()
            rhs_vectors.append(rhs)
        difference = matrix[permutation][:, permutation] - matrix
        scale = max(float(np.max(np.abs(matrix.data))), 1e-300)
        if difference.nnz and np.max(np.abs(difference.data)) > scale * 1e-10:
            return
        rhs0, rhs1 = rhs_vectors
        if not np.allclose(rhs1, rhs0[permutation], rtol=1e-10,
                           atol=max(float(np.max(np.abs(rhs0))), 1e-300) * 1e-12):
            return
        potential, _ = solver._solve_linear_system(matrix, rhs0, 1e-10, 'auto')
        self._response = (indices, step, np.fft.rfft(potential[indices], axis=1))

    def potentials_for(self, tooth_values):
        if self._response is None:
            return None
        indices, step, response = self._response
        nt = indices.shape[1]
        impulses = np.zeros(nt)
        impulses[::step] = tooth_values
        values = np.fft.irfft(response * np.fft.rfft(impulses)[None, :], n=nt, axis=1)
        potential = np.empty(indices.size)
        potential[indices.ravel()] = values.ravel()
        return potential - potential[0]


@dataclass
class FieldAnimationModel:
    field_basis: np.ndarray  # (cos/sin, element, Br/Btheta)
    potential_basis: np.ndarray
    contour_x: np.ndarray
    contour_y: np.ndarray
    image_indices: np.ndarray
    image_mask: np.ndarray
    material_image: np.ndarray
    geometry_paths: np.ndarray
    outer_radius: float
    color_max: float
    generation_seconds: float = 0.0
    reluctance_results: dict | None = None
    mmf_results: dict | None = None
    initial_solution: dict | None = None

    @property
    def storage_bytes(self):
        return sum(value.nbytes for value in vars(self).values()
                   if isinstance(value, np.ndarray))

    def field_at(self, angle_deg):
        angle = np.radians(angle_deg)
        return self.field_basis[0] * np.cos(angle) + self.field_basis[1] * np.sin(angle)

    def image_at(self, angle_deg):
        field = self.field_at(angle_deg)
        magnitude = np.hypot(field[:, 0], field[:, 1])
        image = magnitude[self.image_indices].astype(np.float32)
        image[self.image_mask] = np.nan
        return image

    def contours_at(self, angle_deg, count=12):
        return self.contour_frame_at(angle_deg, count)[0]

    def contour_frame_at(self, angle_deg, count=12, show_arrows=True):
        angle = np.radians(angle_deg)
        values = (self.potential_basis[0] * np.cos(angle)
                  + self.potential_basis[1] * np.sin(angle))
        low, high = float(values.min()), float(values.max())
        if high - low <= max(abs(high), abs(low), 1e-30) * 1e-12:
            return np.empty((0, 2)), np.empty((0, 2))
        levels = np.linspace(low, high, int(np.clip(count, 4, 100)) + 2)[1:-1]
        generator = contourpy.contour_generator(
            x=self.contour_x, y=self.contour_y, z=values,
            name='serial', line_type='Separate')
        paths = [path for level in generator.multi_lines(levels) for path in level]
        if not show_arrows:
            return _joined_paths(paths), np.empty((0, 2))
        radii = np.hypot(self.contour_x[:, 0], self.contour_y[:, 0])
        angles = np.degrees(np.unwrap(np.arctan2(self.contour_y[0], self.contour_x[0])))
        centers, directions = flux_direction_arrows(paths, radii, angles, values)
        arrows = arrowhead_paths(centers, directions, self.outer_radius * 0.035)
        return _joined_paths(paths), arrows

    def solution_at(self, angle_deg):
        """Make an export/statistics snapshot without solving the network again."""
        if self.reluctance_results is None:
            raise ValueError('This animation model has no calculation records.')
        started = time.perf_counter()
        angle = np.radians(float(angle_deg))
        weights = np.array([np.cos(angle), np.sin(angle)])
        field = self.field_at(angle_deg)
        branches = np.einsum('b,bnd->nd', weights, self._branch_basis)
        potentials = weights @ self._nodal_basis
        rhs, residual = weights @ self._rhs_basis, weights @ self._residual_basis
        residual_norm, rhs_norm = float(np.linalg.norm(residual)), float(np.linalg.norm(rhs))
        relative_residual = residual_norm / rhs_norm if rhs_norm else residual_norm
        if not np.isfinite(relative_residual) or relative_residual > 1e-7:
            raise RuntimeError('The field snapshot failed the full-network residual check.')

        up, down = np.einsum('b,bdn->dn', weights, self._source_basis)
        self.mmf_results['element_mmf_up'] = up
        self.mmf_results['element_mmf_down'] = down
        self.mmf_results['tooth_mmf_values'] = weights @ self._tooth_basis
        self.mmf_results['slot_mmf_values'] = weights @ self._slot_basis
        data = self.reluctance_results['reluctance_data']
        for element, source, upper, lower in zip(data, self.mmf_results['mmf_data'], up, down):
            source['mmf_values']['MMF_up'] = float(upper)
            source['mmf_values']['MMF_down'] = float(lower)
            element['mmf_values'] = source['mmf_values']
        self.reluctance_results['statistics']['mmf_integration'] = {
            'elements_with_mmf': int(np.count_nonzero((up != 0) | (down != 0))),
            'tooth_layers': self.mmf_results['statistics']['tooth_layers'],
            'num_teeth': self.mmf_results['statistics']['num_teeth'],
        }
        magnitude = np.linalg.norm(field, axis=1)
        ids = [element['element_id'] for element in data]
        return {
            'potentials': potentials,
            'branch_fluxes': {eid: dict(zip(('up', 'down', 'left', 'right'), values.tolist()))
                              for eid, values in zip(ids, branches)},
            'flux_densities': {eid: {'Br': float(values[0]), 'Btheta': float(values[1]),
                                      'B_magnitude': float(size), 'element_data': element}
                               for eid, values, size, element in zip(ids, field, magnitude, data)},
            'solver_info': {
                'method': 'basis_superposition', 'tolerance': 1e-8, 'info': 0,
                'reference_element_id': self._basis_solver_info[0]['reference_element_id'],
                'residual_norm': residual_norm, 'relative_residual': relative_residual,
                'source_balance': float(rhs.sum()), 'refinement_steps': 0,
                'basis_solver_info': self._basis_solver_info,
            },
            'statistics': {
                'total_elements': len(data), 'calculation_time': time.perf_counter()-started,
                'non_zero_fluxes': int(np.count_nonzero(np.abs(branches) > NEGLIGIBLE_FLUX_WB)),
                'max_flux': float(np.max(np.abs(branches))),
                'max_flux_density': float(magnitude.max()),
            },
            'neighbor_connectivity': self._neighbors,
        }

    @classmethod
    def from_solutions(cls, mesh, solutions, axial_length_mm, resolution=640):
        elements = mesh['mesh_elements']
        radii = np.unique([e[k] for e in elements for k in ('rin', 'rout')])
        angles = np.unique([e[k] for e in elements for k in ('theta_start', 'theta_end')])
        nr, nt = len(radii) - 1, len(angles) - 1
        indices = np.empty((nr, nt), dtype=np.int32)
        materials = np.empty((nr, nt), dtype=np.uint8)
        material_codes = {'Slot': 0, 'Air Gap': 1, 'Rotor Core': 2,
                          'Stator Core': 3, 'Tooth': 3}
        for index, element in enumerate(elements):
            i, j = np.searchsorted(radii, element['rin']), np.searchsorted(angles, element['theta_start'])
            indices[i, j] = index
            materials[i, j] = material_codes[element['material']]
        field_basis = np.asarray([
            [[result['flux_densities'][e['element_id']][key] for key in ('Br', 'Btheta')]
             for e in elements] for result in solutions])

        # Exact maximum of |u*cos(t)+v*sin(t)| for every cell over a full cycle.
        u, v = field_basis
        a, c, b = (np.sum(u*u, axis=1), np.sum(v*v, axis=1), np.sum(u*v, axis=1))
        peak = np.sqrt(np.maximum(0, 0.5 * (a + c + np.hypot(a-c, 2*b))))

        potentials = [reconstruct_flux_potential(mesh, s['branch_fluxes'], axial_length_mm)
                      for s in solutions]
        fine_angles = np.unique(np.concatenate((angles, np.linspace(0, 360, 481))))
        fine_radii = np.unique(np.concatenate((radii, np.sqrt(radii[:-1]*radii[1:]))))
        refined = []
        for potential in potentials:
            angular = np.asarray([np.interp(fine_angles, angles, row) for row in potential.potential])
            refined.append(np.asarray([np.interp(np.log(fine_radii), np.log(radii), column)
                                       for column in angular.T]).T)
        theta = np.radians(fine_angles)
        x, y = fine_radii[:, None]*np.cos(theta), fine_radii[:, None]*np.sin(theta)
        x[:, -1], y[:, -1] = x[:, 0], y[:, 0]

        outer = float(radii[-1])
        # Use cell-centre samples, matching the static piecewise-cell heatmap.
        samples = (np.arange(resolution) + 0.5) * (2*outer/resolution) - outer
        px, py = np.meshgrid(samples, samples)
        radius = np.hypot(px, py)
        angle = np.degrees(np.arctan2(py, px)) % 360
        ri = np.clip(np.searchsorted(radii, radius, side='right')-1, 0, nr-1)
        ti = np.clip(np.searchsorted(angles, angle, side='right')-1, 0, nt-1)
        mask = (radius < radii[0]) | (radius > outer)
        image_indices = indices[ri, ti]
        palette = np.asarray([[255,255,255,255], [222,222,222,255],
                              [150,150,150,255], [215,215,215,255]], dtype=np.uint8)
        background = palette[materials[ri, ti]]
        background[mask] = [255,255,255,255]

        # Material interfaces and circular boundaries are fixed for all frames.
        paths = []
        for i in range(nr):
            for j in range(nt):
                if materials[i, j] != materials[i, (j-1) % nt]:
                    t = np.radians(angles[j])
                    paths.append(np.array([[radii[i]*np.cos(t), radii[i]*np.sin(t)],
                                           [radii[i+1]*np.cos(t), radii[i+1]*np.sin(t)]]))
        for i in range(nr+1):
            for j in range(nt):
                if i in (0, nr) or materials[i-1, j] != materials[i, j]:
                    t = np.radians(np.linspace(angles[j], angles[j+1], 4))
                    paths.append(np.column_stack((radii[i]*np.cos(t), radii[i]*np.sin(t))))
        return cls(field_basis, np.asarray(refined), x, y, image_indices, mask,
                   background, _joined_paths(paths), outer, max(float(peak.max()), 1e-12))


def build_field_animation(mesh, engine, materials, axial_length_mm, mesh_settings,
                          resolution=640, progress=None, cancelled=None,
                          preparation_cache=None):
    """Prepare two residual-checked field bases, leaving the inputs intact."""
    start = time.perf_counter()
    engine = deepcopy(engine)
    initial_angle = engine.wt_angle_deg
    def report(percent, message):
        if cancelled and cancelled():
            raise InterruptedError('Animation preparation cancelled.')
        if progress:
            progress(percent, message)
    report(5, 'Preparing the magnetic model…')
    cache = preparation_cache if preparation_cache is not None else FieldPreparationCache()
    reluctance, solver, network_reused = cache.network(mesh, materials, axial_length_mm)
    mmf, solutions = TeethSlotMMFCalculator(), []
    if cache.direct_winding_updates:
        report(10, 'Preparing winding comparisons...')
        cache.prepare_response(mesh, mesh_settings, mmf)
    sources, right_hand_sides, residuals = [], [], []
    for index, angle in enumerate((0, 90)):
        report(20 + 25*index, f'Updating field basis {index+1}/2…')
        engine.update_wt_angle(angle)
        source = mmf.calculate_teeth_mmf(mesh, mesh_settings, engine, build_full=False)
        sources.append(source)
        solutions.append(solver.calculate_flux_distribution(
            reluctance, source, {'method': 'auto', 'tolerance': 1e-8}, include_statistics=False,
            prepared_potentials=cache.potentials_for(source['tooth_mmf_values'])))
        rhs = solver._build_rhs_vector()
        right_hand_sides.append(rhs)
        residuals.append(solver._cached_matrix @ solutions[-1]['potentials'] - rhs)
    report(75, 'Preparing the continuous field display…')
    model = FieldAnimationModel.from_solutions(mesh, solutions, axial_length_mm, resolution)
    model.network_reused = network_reused
    model.direct_winding_updates = all(
        result['solver_info']['method'] == 'prepared_response' for result in solutions)
    report(90, 'Preparing field values and statistics...')
    # The solver keeps stable network records so its factorization stays reusable.
    # Models own the mutable source attachments used by export/statistics snapshots.
    model.reluctance_results = dict(reluctance)
    model.reluctance_results['reluctance_data'] = [dict(row) for row in reluctance['reluctance_data']]
    model.reluctance_results['statistics'] = dict(reluctance['statistics'])
    engine.update_wt_angle(initial_angle)
    model.mmf_results = mmf.calculate_teeth_mmf(mesh, mesh_settings, engine)
    ids = [element['element_id'] for element in reluctance['reluctance_data']]
    model._branch_basis = np.asarray([[[result['branch_fluxes'][eid][direction]
                                       for direction in ('up', 'down', 'left', 'right')]
                                      for eid in ids] for result in solutions])
    model._nodal_basis = np.asarray([result['potentials'] for result in solutions])
    model._source_basis = np.asarray([[source['element_mmf_up'], source['element_mmf_down']]
                                      for source in sources])
    model._tooth_basis = np.asarray([source['tooth_mmf_values'] for source in sources])
    model._slot_basis = np.asarray([source['slot_mmf_values'] for source in sources])
    model._rhs_basis, model._residual_basis = np.asarray(right_hand_sides), np.asarray(residuals)
    model._basis_solver_info = tuple(result['solver_info'] for result in solutions)
    model._neighbors = solutions[0]['neighbor_connectivity']
    model.initial_solution = model.solution_at(initial_angle)
    model.generation_seconds = time.perf_counter() - start
    report(100, 'Animation ready.')
    return model
