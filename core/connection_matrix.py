"""Dolomites/Koil winding generation with physical layer/phase metadata.

The upstream generator is pinned under third_party/dolomites (GNU GPL v3).
Periodic half-open sector membership fixes wrap and boundary omissions in its
Python sector.angle_inside implementation. Coil population itself is upstream.
"""

from functools import lru_cache
import math

import numpy as np

from third_party.dolomites import koil
from utils.phases import phase_names, phase_offsets_deg


def _validated_dimensions(slots, poles, coil_span):
    if (not isinstance(slots, (int, np.integer)) or slots < 2
            or not isinstance(poles, (int, np.integer)) or poles < 2 or poles % 2):
        raise ValueError('Use an integer slot count and a positive even pole count.')
    if coil_span is None:
        coil_span = max(1, slots // poles)
    if not isinstance(coil_span, (int, np.integer)) or not 1 <= coil_span <= slots:
        raise ValueError('Coil span must be an integer between 1 and the slot count.')
    return int(slots), int(poles), int(coil_span)


def effective_coil_span(slots, poles, is_double_layer, coil_span=None):
    """Dolomites uses an odd coil throw for single-layer windings."""
    _, _, span = _validated_dimensions(slots, poles, coil_span)
    return span - 1 if not is_double_layer and span % 2 == 0 else span


def _inside_sector(angle, sector):
    period = 2 * math.pi
    width = (sector.end_angle - sector.start_angle) % period
    distance = (angle - sector.start_angle) % period
    epsilon = 1e-10
    if distance < epsilon or period - distance < epsilon:
        distance = 0.0
    return distance < width - epsilon


@lru_cache(maxsize=128)
def _dolomites_matrix(slots, poles, double, coil_span, count):
    star = koil.star_of_slot(count, slots, poles // 2)
    if star.t < 1:
        raise ValueError(f'Dolomites cannot form a balanced {count}-phase winding '
                         f'with {slots} slots and {poles} poles.')
    if not double and not star.single_layer_feasible:
        raise ValueError('Dolomites requires a double-layer winding for this combination.')
    star.create_sectors()
    # Wrap sectors at 2*pi and assign each boundary to exactly one sector.
    for sector in (*star.p_sec, *star.n_sec):
        sector.slots = [spoke.id for spoke in star.star if _inside_sector(spoke.angle, sector)]
    winding = koil.m_phase_winding()
    winding.star, winding.p = star, poles // 2
    star.populate_winding(winding, coil_span, single_layer=not double)
    matrix = np.zeros((count * (2 if double else 1), slots), dtype=int)
    for phase, phase_winding in enumerate(winding.windings):
        for coil in phase_winding.coils:
            matrix[phase, coil.begin - 1] += coil.nc
            matrix[phase + count if double else phase, coil.end - 1] -= coil.nc
    occupancy = np.abs(matrix).sum(axis=0)
    if not np.all(occupancy == (2 if double else 1)):
        raise ValueError('This Dolomites layout does not fill each physical slot consistently.')
    complete = matrix[:count] + matrix[count:] if double else matrix
    if not np.all(complete.sum(axis=1) == 0):
        raise ValueError('The generated winding has an unbalanced coil return path.')
    counts = np.abs(matrix[:count]).sum(axis=1)
    if double:
        counts += np.abs(matrix[count:]).sum(axis=1)
    if np.any(counts == 0) or not np.all(counts == counts[0]):
        raise ValueError('This coil throw does not give equal conductor counts in all phases.')
    if np.any(complete):
        phasors = complete @ np.exp(-1j * np.pi * poles * np.arange(slots) / slots)
        axes = np.exp(-1j * np.radians(phase_offsets_deg(count)))
        if (np.min(np.abs(phasors)) <= 1e-10 or
                not np.allclose(phasors / phasors[0], axes, atol=1e-8, rtol=1e-8)):
            raise ValueError('This coil throw does not produce balanced working-harmonic phase axes.')
    matrix.setflags(write=False)
    return matrix


def build_winding_connection_matrix(slots, poles, is_double_layer,
                                     coil_span=None, phases=('A', 'B', 'C')):
    """Generate a Dolomites star-of-slots winding for odd or even phase counts."""
    slots, poles, span = _validated_dimensions(slots, poles, coil_span)
    phases = tuple(phases)
    phase_names(len(phases))
    if len(set(phases)) != len(phases):
        raise ValueError('Use distinct phase names.')
    span = effective_coil_span(slots, poles, is_double_layer, span)
    return _dolomites_matrix(slots, poles, bool(is_double_layer), span, len(phases)).copy()


def phase_pattern_from_matrix(matrix, phases=('A', 'B', 'C')):
    """Diagram labels from the same physical coil matrix used for calculation."""
    count = len(phases)
    if matrix.shape[0] not in (count, 2*count):
        raise ValueError('Matrix rows must match the phase names and layer count.')
    double = matrix.shape[0] == 2*count
    pattern = []
    for slot in range(matrix.shape[1]):
        top = np.flatnonzero(matrix[:count, slot])
        bottom = np.flatnonzero(matrix[count:, slot]) if double else []
        pattern.append((phases[int(top[0])] if len(top) else None,
                        phases[int(bottom[0])] if len(bottom) else None))
    return pattern


def generate_connection_matrix(winding_pattern, phases, is_double_layer, poles,
                               coil_span=None):
    matrix = build_winding_connection_matrix(
        len(winding_pattern), poles, is_double_layer, coil_span, phases)
    expected = phase_pattern_from_matrix(matrix, phases)
    for supplied, physical in zip(winding_pattern, expected):
        if (len(supplied) != 2 or supplied[0] != physical[0]
                or (supplied[1] != physical[1]
                    and not (is_double_layer and supplied[1] is None))):
            raise ValueError('The winding phase pattern does not match its Dolomites '
                             'layout. Rebuild the winding layout.')
    return matrix
