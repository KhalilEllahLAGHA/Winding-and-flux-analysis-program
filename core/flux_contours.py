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


def flux_direction_arrows(paths, radii_mm, angles_deg, potential,
                          spacing_mm=None, max_arrows=128):
    """Place arrows along contours, oriented by B = curl(Az ez)."""
    radii = np.asarray(radii_mm)
    angles = np.radians(angles_deg)
    potential = np.asarray(potential)
    outer = float(radii[-1])
    spacing = float(spacing_mm or outer * 0.65)
    centers, tangents = [], []
    for path in paths:
        path = np.asarray(path)
        if len(path) < 2 or not np.isfinite(path).all():
            continue
        distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
        keep = np.r_[True, np.diff(distance) > outer * 1e-12]
        distance, path = distance[keep], path[keep]
        if distance[-1] < outer * 0.1:
            continue
        count = max(1, int(distance[-1] / spacing))
        marks = (np.arange(count) + 0.5) * distance[-1] / count
        sample = lambda s: np.column_stack([np.interp(s, distance, path[:, k])
                                            for k in (0, 1)])
        centers.append(sample(marks))
        tangents.append(sample(marks + outer * 0.008) - sample(marks - outer * 0.008))
    if not centers or max_arrows < 1:
        return np.empty((0, 2)), np.empty((0, 2))
    centers, tangents = np.concatenate(centers), np.concatenate(tangents)
    if len(centers) > max_arrows:
        selected = np.linspace(0, len(centers)-1, max_arrows, dtype=int)
        centers, tangents = centers[selected], tangents[selected]

    radius = np.hypot(centers[:, 0], centers[:, 1])
    theta = (np.arctan2(centers[:, 1], centers[:, 0]) - angles[0]) % (2*np.pi) + angles[0]
    ri = np.clip(np.searchsorted(radii, radius, side='right')-1, 0, len(radii)-2)
    ti = np.clip(np.searchsorted(angles, theta, side='right')-1, 0, len(angles)-2)
    dr = np.log(radii[ri+1] / radii[ri])
    dt = angles[ti+1] - angles[ti]
    u = np.clip(np.log(radius / radii[ri]) / dr, 0, 1)
    v = np.clip((theta - angles[ti]) / dt, 0, 1)
    a00, a01 = potential[ri, ti], potential[ri, ti+1]
    a10, a11 = potential[ri+1, ti], potential[ri+1, ti+1]
    # Common 1/r and mm-to-m factors cancel when finding the direction.
    br = ((1-u)*(a01-a00) + u*(a11-a10)) / dt
    bt = -((1-v)*(a10-a00) + v*(a11-a01)) / dr
    field = np.column_stack((br*np.cos(theta) - bt*np.sin(theta),
                             br*np.sin(theta) + bt*np.cos(theta)))
    magnitude = np.linalg.norm(field, axis=1)
    tangent_length = np.linalg.norm(tangents, axis=1)
    alignment = np.einsum('ij,ij->i', field, tangents)
    valid = ((magnitude > max(float(magnitude.max()) * 1e-10, 1e-300))
             & (tangent_length > outer * 1e-12)
             & (np.abs(alignment) > magnitude * tangent_length * 1e-6))
    directions = tangents[valid] / tangent_length[valid, None]
    directions *= np.sign(alignment[valid, None])
    return centers[valid], directions


def arrowhead_paths(centers, directions, length_mm):
    """Joined chevrons for both static figures and the live Qt view."""
    if not len(centers):
        return np.empty((0, 2))
    normal = np.column_stack((-directions[:, 1], directions[:, 0]))
    tail = centers - directions * length_mm * 0.6
    paths = np.full((len(centers), 4, 2), np.nan)
    paths[:, 0] = tail + normal * length_mm * 0.38
    paths[:, 1] = centers + directions * length_mm * 0.4
    paths[:, 2] = tail - normal * length_mm * 0.38
    return paths.reshape(-1, 2)


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
