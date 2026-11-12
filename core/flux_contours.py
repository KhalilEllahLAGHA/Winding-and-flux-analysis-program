"""Planar vector potential reconstructed from conservative polar face fluxes.

For psi = axial_length * Az, outward radial flux is the angular difference
of psi, and positive-theta flux is its negative radial difference. A least
squares fit of these discrete differences uses every solved branch. Periodic
Fourier modes reduce the fit to independent radial tridiagonal systems.
The insulated inner and outer boundaries each have a constant potential.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class FluxContourData:
    radii_mm: np.ndarray
    angles_deg: np.ndarray
    potential: np.ndarray  # Az in Wb/m, with a repeated periodic endpoint.
    relative_residual: float


def reconstruct_flux_potential(mesh_data, branch_fluxes, axial_length_mm):
    """Recover Az on mesh corners, preserving the annular boundary conditions.

    Requires the complete polar mesh used by the reluctance solver. Missing
    branch values and incomplete meshes raise ValueError. Integer and JSON
    string element ids are both accepted.
    """
    length_m = float(axial_length_mm) * 1e-3
    if not np.isfinite(length_m) or length_m <= 0:
        raise ValueError('Axial length must be positive and finite.')
    elements = mesh_data.get('mesh_elements', [])
    if not elements:
        raise ValueError('A complete polar mesh is required for flux contours.')
    radii = np.unique([e[key] for e in elements for key in ('rin', 'rout')])
    angles = np.unique([e[key] for e in elements
                        for key in ('theta_start', 'theta_end')])
    nr, nt = len(radii) - 1, len(angles) - 1
    if (nr < 1 or nt < 3 or len(elements) != nr * nt
            or not np.isclose(angles[-1] - angles[0], 360.0)):
        raise ValueError('Flux contours require a complete 360-degree polar mesh.')

    faces = np.empty((nr, nt, 4), dtype=float)
    occupied = np.zeros((nr, nt), dtype=bool)
    for element in elements:
        i = int(np.searchsorted(radii, element['rin']))
        j = int(np.searchsorted(angles, element['theta_start']))
        if (i >= nr or j >= nt or occupied[i, j]
                or element['rout'] != radii[i + 1]
                or element['theta_end'] != angles[j + 1]):
            raise ValueError('Flux contours require matching polar cell faces.')
        eid = element.get('element_id', element.get('id'))
        branch = branch_fluxes.get(eid, branch_fluxes.get(str(eid)))
        if branch is None and isinstance(eid, str) and eid.isdigit():
            branch = branch_fluxes.get(int(eid))
        if branch is None or any(key not in branch for key in ('up', 'down', 'left', 'right')):
            raise ValueError('Solved face fluxes are missing for a mesh element.')
        faces[i, j] = [branch[key] for key in ('up', 'down', 'left', 'right')]
        occupied[i, j] = True
    if not occupied.all() or not np.isfinite(faces).all():
        raise ValueError('Solved face fluxes must be complete and finite.')
    boundary_tolerance = max(float(np.max(np.abs(faces))) * 1e-10, 1e-30)
    if (np.any(np.abs(faces[0, :, 1]) > boundary_tolerance)
            or np.any(np.abs(faces[-1, :, 0]) > boundary_tolerance)):
        raise ValueError('Flux contours require insulated inner and outer boundaries.')

    # Average the two signed observations of each shared physical face.
    radial = 0.5 * (faces[:-1, :, 0] - faces[1:, :, 1])
    radial_difference = 0.5 * (faces[:, :, 2]
                               - np.roll(faces[:, :, 3], 1, axis=1))
    psi = np.zeros((nr + 1, nt))
    mean_psi = np.concatenate(([0.0], np.cumsum(radial_difference.mean(axis=1))))
    psi[-1] = mean_psi[-1]

    if nr > 1:
        rhs = (radial_difference[:-1] - radial_difference[1:]
               + np.roll(radial, 1, axis=1) - radial)
        transformed = np.fft.rfft(rhs, axis=1)
        angular_eigenvalue = 2 - 2 * np.cos(2 * np.pi * np.fft.rfftfreq(nt))
        diagonal = np.broadcast_to(2 + angular_eigenvalue, transformed.shape).copy()
        # Thomas elimination acts on every angular mode together.
        for i in range(1, nr - 1):
            inverse_previous = 1 / diagonal[i - 1]
            diagonal[i] -= inverse_previous
            transformed[i] += transformed[i - 1] * inverse_previous
        transformed[-1] /= diagonal[-1]
        for i in range(nr - 3, -1, -1):
            transformed[i] = (transformed[i] + transformed[i + 1]) / diagonal[i]
        # The zero mode permits different constants on the two boundaries,
        # preserving genuine circumferential flux around the shaft.
        transformed[:, 0] = mean_psi[1:-1] * nt
        psi[1:-1] = np.fft.irfft(transformed, n=nt, axis=1)

    reconstructed_radial = np.roll(psi[1:-1], -1, axis=1) - psi[1:-1]
    reconstructed_difference = np.diff(psi, axis=0)
    error_squared = (np.sum((reconstructed_radial - radial) ** 2)
                     + np.sum((reconstructed_difference - radial_difference) ** 2))
    target_squared = np.sum(radial ** 2) + np.sum(radial_difference ** 2)
    residual = float(np.sqrt(error_squared / target_squared)) if target_squared else 0.0
    potential = np.column_stack((psi, psi[:, 0])) / length_m
    return FluxContourData(radii, angles, potential, residual)
