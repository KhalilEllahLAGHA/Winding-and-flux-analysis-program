"""Magnetic-circuit flux solver (formerly ``Meshing_flux_calculation.py``).

Builds the reluctance-network system matrix, solves the nodal potentials
with a Jacobi-preconditioned conjugate gradient solver, and derives branch
fluxes and flux densities.

The sparse system matrix and connectivity are cached between solves so the
animation (many Wt angles, same geometry) only rebuilds the RHS vector.
"""

import logging
import time

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import LinearOperator, cg

from utils.constants import DEFAULT_AXIAL_LENGTH_MM

logger = logging.getLogger(__name__)

DEFAULT_SOLVER_TOLERANCE = 1e-6
SOLVER_METHOD_NAME = 'pcg_jacobi'
NEGLIGIBLE_FLUX_WB = 1e-12

DIRECTIONS = ('left', 'right', 'up', 'down')
OPPOSITE_DIRECTION = {'left': 'right', 'right': 'left', 'up': 'down', 'down': 'up'}


def _parse_tolerance(solver_options):
    """Extract a valid positive solver tolerance from the options dict."""
    if not solver_options:
        return DEFAULT_SOLVER_TOLERANCE
    try:
        tolerance = float(solver_options.get('tolerance', DEFAULT_SOLVER_TOLERANCE))
    except (TypeError, ValueError):
        return DEFAULT_SOLVER_TOLERANCE
    return (tolerance if np.isfinite(tolerance) and tolerance > 0
            else DEFAULT_SOLVER_TOLERANCE)


class FluxCalculator:
    """Solves the magnetic circuit defined by reluctance and MMF data."""

    def __init__(self):
        self.reluctance_data = []
        self.mmf_data = []
        self.neighbors = {}
        self.flux_results = {}
        self.potentials = None
        self.branch_fluxes = {}
        self.flux_densities = {}

        # Cached system topology/matrix, reused while geometry is unchanged.
        # The per-direction neighbour-index and branch-conductance arrays let
        # the RHS, branch-flux, and flux-density computations run as
        # vectorised NumPy gathers instead of per-element Python dict loops.
        self._cached_structure_key = None
        self._cached_matrix = None
        self._cached_reduced_matrix = None
        self._cached_preconditioner = None
        self._cached_id_to_idx = None
        self._cached_neighbors = None
        self._cached_eids = None
        self._cached_nbr_idx = None       # {direction: int array, -1 if none}
        self._cached_inv_R = None         # {direction: 1/total_reluctance, 0 if none}
        self._cached_safe_j = None        # {direction: nbr index clamped to >=0}
        self._cached_geometry = None      # rin/rout/r_center in metres

        # Per-solve working arrays (reset each solve).
        self._mmf_arr = None
        self._element_mmf_ud = None
        self._element_mmf_up = None
        self._element_mmf_down = None
        self._branch_flux_array = None
        self._bmag_array = None
        self._solver_residual_norm = 0.0
        self._solver_relative_residual = 0.0
        self._solver_source_balance = 0.0
        self._solver_refinement_steps = 0

    def calculate_flux_distribution(self, reluctance_results, mmf_results,
                                    solver_options=None, progress_callback=None,
                                    include_flux_densities=True,
                                    include_statistics=True):
        """Run the full solve and return potentials, fluxes, and densities."""
        start_time = time.time()

        if progress_callback:
            progress_callback("Starting flux calculation...")

        self.reluctance_data = reluctance_results['reluctance_data']
        self.mmf_data = mmf_results['mmf_data']
        # Optional pre-aligned per-element up/down MMF array (the teeth/slot
        # calculator provides this so the solver can skip rebuilding MMF
        # arrays from per-element dicts — the dominant per-frame cost).
        self._element_mmf_ud = mmf_results.get('element_mmf_ud')
        self._element_mmf_up = mmf_results.get('element_mmf_up')
        self._element_mmf_down = mmf_results.get('element_mmf_down')
        total_elements = len(self.reluctance_data)

        if progress_callback:
            progress_callback(f"Processing {total_elements:,} elements...")

        matrix, rhs = self._get_system(progress_callback)

        tolerance = _parse_tolerance(solver_options)

        if progress_callback:
            progress_callback("Solving with Preconditioned CG (Jacobi)...")

        self.potentials, info = self._solve_linear_system(matrix, rhs, tolerance)

        if progress_callback:
            progress_callback("Computing branch fluxes...")
        self.branch_fluxes = self.compute_branch_fluxes()

        if include_flux_densities:
            if progress_callback:
                progress_callback("Computing flux densities...")
            self.flux_densities = self.compute_flux_densities(reluctance_results)
        else:
            self.flux_densities = {}
            self._bmag_array = None

        calculation_time = time.time() - start_time

        if include_statistics:
            statistics = {
                'total_elements': total_elements,
                'calculation_time': calculation_time,
                'non_zero_fluxes': self._count_non_zero_fluxes(),
                'max_flux': self._max_flux_magnitude(),
                'max_flux_density': (self._max_flux_density()
                                     if include_flux_densities else 0.0),
            }
        else:
            statistics = {
                'total_elements': total_elements,
                'calculation_time': calculation_time,
                'non_zero_fluxes': 0,
                'max_flux': 0.0,
                'max_flux_density': 0.0,
            }

        self.flux_results = {
            'potentials': self.potentials,
            'branch_fluxes': self.branch_fluxes,
            'flux_densities': self.flux_densities,
            'solver_info': {
                'method': SOLVER_METHOD_NAME,
                'tolerance': tolerance,
                'info': int(info),
                'reference_element_id': self.reluctance_data[0]['element_id'],
                'residual_norm': self._solver_residual_norm,
                'relative_residual': self._solver_relative_residual,
                'source_balance': self._solver_source_balance,
                'refinement_steps': self._solver_refinement_steps,
            },
            'statistics': statistics,
            'neighbor_connectivity': self.neighbors,
        }

        if progress_callback:
            progress_callback(
                f"Flux calculation completed in {calculation_time:.2f}s!")

        return self.flux_results

    # --------------------------------------------------------- connectivity

    def build_neighbor_connectivity(self):
        """Find up/down/left/right neighbours from element centre positions."""
        elements = [{
            'element_id': data['element_id'],
            'r': float(data['center']['r']),
            'theta': float(data['center']['theta']),
        } for data in self.reluctance_data]

        neighbors = {element['element_id']:
                     {'left': None, 'right': None, 'up': None, 'down': None}
                     for element in elements}

        # Radial neighbours: group by theta, connect along increasing radius.
        theta_groups = {}
        for element in elements:
            theta_groups.setdefault(element['theta'], []).append(
                (element['r'], element['element_id']))

        for radial_line in theta_groups.values():
            radial_line.sort()
            for (_, inner_id), (_, outer_id) in zip(radial_line, radial_line[1:]):
                neighbors[inner_id]['up'] = outer_id
                neighbors[outer_id]['down'] = inner_id

        # Angular neighbours: group by radius, connect circularly by theta.
        radius_groups = {}
        for element in elements:
            radius_groups.setdefault(element['r'], []).append(
                (element['theta'], element['element_id']))

        for ring in radius_groups.values():
            ring.sort()
            n = len(ring)
            for i in range(n):
                _, current_id = ring[i]
                _, next_id = ring[(i + 1) % n]
                neighbors[current_id]['right'] = next_id
                neighbors[next_id]['left'] = current_id

        self.neighbors = neighbors
        return neighbors

    # ------------------------------------------------------- system building

    def _get_structure_key(self):
        """Cheap fingerprint of the reluctance data used to detect changes."""
        if not self.reluctance_data:
            return None

        first = self.reluctance_data[0]
        last = self.reluctance_data[-1]
        return (
            id(self.reluctance_data),
            len(self.reluctance_data),
            first['element_id'],
            last['element_id'],
            round(first['reluctances']['R_up'], 12),
            round(last['reluctances']['R_up'], 12),
        )

    def _get_system(self, progress_callback=None):
        """Return (matrix, rhs); rebuild the cached matrix only when the
        reluctance structure changed."""
        structure_key = self._get_structure_key()
        if self._cached_matrix is None or structure_key != self._cached_structure_key:
            if progress_callback:
                progress_callback("Building neighbor connectivity...")
            self.build_neighbor_connectivity()
            if progress_callback:
                progress_callback("Building system matrix...")
            self._prepare_cached_system()
        else:
            self.neighbors = self._cached_neighbors

        if progress_callback:
            progress_callback("Building RHS vector...")
        return self._cached_matrix, self._build_rhs_vector()

    def _prepare_cached_system(self):
        """Build and cache the sparse system matrix plus the per-direction
        neighbour-index and branch-conductance arrays used by the vectorised
        RHS / branch-flux / flux-density computations."""
        n = len(self.reluctance_data)
        id_to_idx = {data['element_id']: idx
                     for idx, data in enumerate(self.reluctance_data)}
        reluctance_lookup = {data['element_id']: data['reluctances']
                             for data in self.reluctance_data}

        nbr_idx = {d: np.full(n, -1, dtype=np.int64) for d in DIRECTIONS}
        inv_R = {d: np.zeros(n, dtype=np.float64) for d in DIRECTIONS}

        for elem_data in self.reluctance_data:
            eid = elem_data['element_id']
            i = id_to_idx[eid]
            rel_i = reluctance_lookup[eid]
            neigh_i = self.neighbors.get(eid, {})

            for direction in DIRECTIONS:
                neighbor_id = neigh_i.get(direction)
                if neighbor_id is None or neighbor_id not in id_to_idx:
                    continue

                opposite = OPPOSITE_DIRECTION[direction]
                total_reluctance = (rel_i['R_' + direction]
                                    + reluctance_lookup[neighbor_id]['R_' + opposite])
                if not np.isfinite(total_reluctance) or total_reluctance <= 0:
                    raise ValueError('Branch reluctances must be finite and positive.')

                nbr_idx[direction][i] = id_to_idx[neighbor_id]
                inv_R[direction][i] = 1.0 / total_reluctance

        # Assemble the sparse system in one COO build from the per-direction
        # arrays, instead of tens of thousands of slow lil_matrix insertions.
        rows = [np.arange(n, dtype=np.int64)]
        cols = [np.arange(n, dtype=np.int64)]
        diagonal = np.zeros(n, dtype=np.float64)
        data = [diagonal]
        for direction in DIRECTIONS:
            mask = nbr_idx[direction] >= 0
            i_idx = np.nonzero(mask)[0]
            rows.append(i_idx)
            cols.append(nbr_idx[direction][i_idx])
            data.append(-inv_R[direction][i_idx])
            diagonal += inv_R[direction]  # 0 where no neighbour, so safe

        self._cached_matrix = coo_matrix(
            (np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))),
            shape=(n, n), dtype=np.float64).tocsr()
        self._cached_reduced_matrix = None
        self._cached_preconditioner = None
        self._cached_id_to_idx = id_to_idx
        self._cached_eids = [data['element_id'] for data in self.reluctance_data]
        self._cached_nbr_idx = nbr_idx
        self._cached_inv_R = inv_R
        # Clamp -1 (no neighbour) to 0 so gathers stay in-bounds; the matching
        # inv_R entry is 0 there, so the gathered value never contributes.
        self._cached_safe_j = {d: np.where(nbr_idx[d] >= 0, nbr_idx[d], 0)
                               for d in DIRECTIONS}
        self._cached_geometry = self._build_geometry_arrays()
        self._cached_neighbors = self.neighbors
        self._cached_structure_key = self._get_structure_key()

    def _build_geometry_arrays(self):
        """Cache element rin/rout/r_center (in metres) for flux densities."""
        n = len(self.reluctance_data)
        rin = np.empty(n, dtype=np.float64)
        rout = np.empty(n, dtype=np.float64)
        r_center = np.empty(n, dtype=np.float64)
        theta_span = np.empty(n, dtype=np.float64)
        for idx, data in enumerate(self.reluctance_data):
            geometry = data['geometry']
            rin[idx] = geometry['rin']
            rout[idx] = geometry['rout']
            r_center[idx] = data['center']['r']
            theta_span[idx] = np.radians(
                geometry['theta_end'] - geometry['theta_start'])
        return {'rin_m': rin / 1000.0,
                'rout_m': rout / 1000.0,
                'r_center_m': r_center / 1000.0,
                'theta_span_rad': theta_span,
                'log_ratio': np.log(rout / rin)}

    def _mmf_arrays(self):
        """Per-element MMF source arrays (up/down/left/right), aligned to the
        cached element index order. Built once per solve and reused by both
        the RHS and the branch-flux computation."""
        n = len(self.reluctance_data)

        # Signed positive-radial MMF integrals from centre to each radial
        # face. Unequal halves are needed for distributed winding sources.
        up, down = self._element_mmf_up, self._element_mmf_down
        if up is not None or down is not None:
            if up is None or down is None or len(up) != n or len(down) != n:
                raise ValueError('Both radial MMF arrays must align with the mesh.')
            up = np.asarray(up, dtype=np.float64)
            down = np.asarray(down, dtype=np.float64)
            if (up.shape != (n,) or down.shape != (n,)
                    or not np.isfinite(up).all() or not np.isfinite(down).all()):
                raise ValueError('Radial MMF arrays must contain finite scalars.')
            zeros = np.zeros(n, dtype=np.float64)
            return {'up': up, 'down': down, 'left': zeros, 'right': zeros}

        # Fast path: the teeth/slot calculator already produced an aligned
        # up/down MMF array (MMF_up == MMF_down; left/right are always 0).
        element_mmf_ud = self._element_mmf_ud
        if element_mmf_ud is not None and len(element_mmf_ud) == n:
            ud = np.asarray(element_mmf_ud, dtype=np.float64)
            if ud.shape != (n,) or not np.isfinite(ud).all():
                raise ValueError('Radial MMF arrays must contain finite scalars.')
            zeros = np.zeros(n, dtype=np.float64)
            return {'up': ud, 'down': ud, 'left': zeros, 'right': zeros}

        id_to_idx = self._cached_id_to_idx
        arrays = {d: np.zeros(n, dtype=np.float64) for d in DIRECTIONS}

        for data in self.mmf_data:
            idx = id_to_idx.get(data['element_id'])
            if idx is None:
                continue
            mmf_values = data.get('mmf_values')
            if not mmf_values:
                continue
            for direction in DIRECTIONS:
                arrays[direction][idx] = mmf_values.get('MMF_' + direction, 0.0)
        if not all(np.isfinite(values).all() for values in arrays.values()):
            raise ValueError('MMF sources must be finite.')
        return arrays

    def _build_rhs_vector(self):
        """Negative divergence of the exact sources used by every branch."""
        self._mmf_arr = self._mmf_arrays()
        mmf = self._mmf_arr
        inv_R = self._cached_inv_R
        safe_j = self._cached_safe_j

        # up branch: sign -1, neighbour contributes its 'down' MMF.
        up_term = (mmf['up'] + mmf['down'][safe_j['up']]) * inv_R['up']
        # down branch: sign +1, neighbour contributes its 'up' MMF.
        down_term = (mmf['down'] + mmf['up'][safe_j['down']]) * inv_R['down']
        left_term = (mmf['left'] + mmf['right'][safe_j['left']]) * inv_R['left']
        right_term = (mmf['right'] + mmf['left'][safe_j['right']]) * inv_R['right']
        return down_term - up_term + right_term - left_term

    # ---------------------------------------------------------------- solve

    @staticmethod
    def _build_jacobi_preconditioner(matrix):
        diag = matrix.diagonal().astype(np.float64)
        if not np.isfinite(diag).all() or np.any(diag <= 0):
            raise ValueError('The magnetic network has an invalid or isolated node.')
        inv_diag = 1.0 / diag
        return LinearOperator(shape=matrix.shape,
                              matvec=lambda x: inv_diag * x,
                              dtype=np.float64)

    def _solve_linear_system(self, matrix, rhs, tolerance):
        """Fix one potential reference without adding an artificial flux path.

        Missing boundary branches impose zero normal flux. The remaining
        graph Laplacian has one arbitrary constant potential; deleting the
        reference row and column makes the connected system positive definite.
        """
        rhs = np.asarray(rhs, dtype=np.float64)
        n = matrix.shape[0]
        if n == 0 or rhs.shape != (n,):
            raise ValueError('The magnetic network must contain aligned nodes and sources.')
        if not np.isfinite(matrix.data).all() or not np.isfinite(rhs).all():
            raise ValueError('The magnetic system contains non-finite values.')
        self._solver_source_balance = float(rhs.sum())
        source_scale = float(np.abs(rhs).sum())
        if abs(self._solver_source_balance) > max(source_scale, 1e-300) * 1e-10:
            raise ValueError('The closed magnetic network has unbalanced sources.')
        potentials = np.zeros(n, dtype=np.float64)
        info = 0
        self._solver_refinement_steps = 0
        if n > 1 and np.any(rhs):
            if matrix is self._cached_matrix:
                if self._cached_reduced_matrix is None:
                    self._cached_reduced_matrix = matrix[1:, 1:].tocsr()
                    self._cached_preconditioner = self._build_jacobi_preconditioner(
                        self._cached_reduced_matrix)
                reduced = self._cached_reduced_matrix
                preconditioner = self._cached_preconditioner
            else:
                reduced = matrix[1:, 1:].tocsr()
                preconditioner = self._build_jacobi_preconditioner(reduced)
            potentials[1:], info = cg(reduced, rhs[1:], M=preconditioner,
                                      rtol=tolerance)
        rhs_norm = float(np.linalg.norm(rhs))
        allowed_relative_residual = max(10 * tolerance, 1e-12)
        for attempt in range(3):
            residual = matrix @ potentials - rhs
            self._solver_residual_norm = float(np.linalg.norm(residual))
            self._solver_relative_residual = (
                self._solver_residual_norm / rhs_norm if rhs_norm else
                self._solver_residual_norm)
            finite = np.isfinite(potentials).all() and np.isfinite(self._solver_relative_residual)
            if info == 0 and finite and self._solver_relative_residual <= allowed_relative_residual:
                if self._solver_refinement_steps:
                    logger.info(
                        'Magnetic solver refined successfully after %d warm restart(s); '
                        'full relative residual %.3e.',
                        self._solver_refinement_steps, self._solver_relative_residual)
                return potentials, info
            if attempt == 2 or info != 0 or not finite:
                break

            # The omitted reference residual is -sum(reduced residuals)
            # for balanced sources. Its full norm can be sqrt(n) larger.
            # Tighten the reduced absolute target and recompute CG's true
            # starting residual while retaining the current potentials.
            residual_budget = (allowed_relative_residual * rhs_norm
                               - abs(self._solver_source_balance))
            if residual_budget <= 0:
                break
            reduced_atol = 0.5 * residual_budget / np.sqrt(n) * 0.1 ** attempt
            potentials[1:], info = cg(
                reduced, rhs[1:], x0=potentials[1:].copy(), M=preconditioner,
                rtol=0.0, atol=reduced_atol)
            self._solver_refinement_steps += 1

        raise RuntimeError(f'Magnetic solver did not converge (info={info}, '
                           f'relative residual={self._solver_relative_residual:.3e}).')

    # ------------------------------------------------------------- results

    def compute_branch_fluxes(self):
        """Flux through each element branch from solved potentials.

        Fully vectorised: for each direction the branch flux is
        ``(Δpotential ± ΣMMF) · conductance`` computed as a NumPy gather,
        then assembled into the per-element dict the consumers expect.
        Missing branches have conductance 0, so they stay exactly 0.0.
        """
        pot = np.asarray(self.potentials, dtype=np.float64)
        mmf = self._mmf_arr if self._mmf_arr is not None else self._mmf_arrays()
        inv_R = self._cached_inv_R
        safe_j = self._cached_safe_j

        flux = {}
        for direction in DIRECTIONS:
            opposite = OPPOSITE_DIRECTION[direction]
            sj = safe_j[direction]
            potential_diff = pot - pot[sj]
            total_mmf = mmf[direction] + mmf[opposite][sj]
            sign = 1.0 if direction in ('left', 'up') else -1.0
            flux[direction] = (potential_diff + sign * total_mmf) * inv_R[direction]

        # Flat array kept for O(n) statistics without re-walking the dicts.
        self._branch_flux_array = np.column_stack(
            (flux['up'], flux['down'], flux['left'], flux['right']))

        up_l = flux['up'].tolist()
        down_l = flux['down'].tolist()
        left_l = flux['left'].tolist()
        right_l = flux['right'].tolist()
        return {eid: {'up': u, 'down': d, 'left': l, 'right': r}
                for eid, u, d, l, r in zip(self._cached_eids,
                                           up_l, down_l, left_l, right_l)}

    def compute_flux_densities(self, reluctance_results):
        """Radial/circumferential flux densities per element [T], vectorised."""
        machine_params = reluctance_results.get('machine_parameters', {})
        axial_length_m = machine_params.get(
            'axial_length', DEFAULT_AXIAL_LENGTH_MM) / 1000

        geometry = self._cached_geometry
        branch = self._branch_flux_array
        flux_up, flux_down = branch[:, 0], branch[:, 1]
        flux_left, flux_right = branch[:, 2], branch[:, 3]

        # Opposite outward face fluxes describe the same field twice: average
        # them, rather than taking their unscaled difference.
        area_radial = (geometry['r_center_m'] * geometry['theta_span_rad']
                       * axial_length_m)
        br = np.divide(0.5 * (flux_up - flux_down), area_radial,
                       out=np.zeros_like(area_radial), where=area_radial > 0)

        # Right is increasing theta. The centre field for Btheta=C/r uses
        # Phi_theta = C L log(rout/rin), consistent with angular reluctance.
        area_circumferential = (geometry['r_center_m'] * geometry['log_ratio']
                               * axial_length_m)
        btheta = np.divide(0.5 * (flux_right - flux_left), area_circumferential,
                           out=np.zeros_like(area_circumferential),
                           where=area_circumferential > 0)

        b_magnitude = np.sqrt(br ** 2 + btheta ** 2)
        self._bmag_array = b_magnitude

        br_l = br.tolist()
        btheta_l = btheta.tolist()
        bmag_l = b_magnitude.tolist()
        return {
            elem_data['element_id']: {
                'Br': br_l[idx],
                'Btheta': btheta_l[idx],
                'B_magnitude': bmag_l[idx],
                'element_data': elem_data,
            }
            for idx, elem_data in enumerate(self.reluctance_data)
        }

    # ------------------------------------------------------------ statistics

    def _count_non_zero_fluxes(self):
        if self._branch_flux_array is None:
            return 0
        return int(np.count_nonzero(
            np.abs(self._branch_flux_array) > NEGLIGIBLE_FLUX_WB))

    def _max_flux_magnitude(self):
        if self._branch_flux_array is None or self._branch_flux_array.size == 0:
            return 0.0
        return float(np.abs(self._branch_flux_array).max())

    def _max_flux_density(self):
        if self._bmag_array is None or self._bmag_array.size == 0:
            return 0.0
        return float(self._bmag_array.max())
