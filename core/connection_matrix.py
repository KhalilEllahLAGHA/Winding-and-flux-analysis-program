"""Build signed coil connections from the electrical slot positions."""

from functools import lru_cache
import math

import numpy as np

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
    """Single-layer coil returns must connect odd and even slots."""
    _, _, span = _validated_dimensions(slots, poles, coil_span)
    return span - 1 if not is_double_layer and span % 2 == 0 else span


@lru_cache(maxsize=128)
def _winding_matrix(slots, poles, double, coil_span, count):
    pole_pairs = poles // 2
    repetitions = math.gcd(slots, pole_pairs)
    spokes_per_phase, remainder = divmod(slots, count * repetitions)
    if remainder or (count % 2 == 0 and spokes_per_phase % 2):
        raise ValueError(f'Cannot form a balanced {count}-phase winding '
                         f'with {slots} slots and {poles} poles.')
    if not double and slots % 2:
        raise ValueError('This combination requires a double-layer winding.')

    # One turn is 4*m*Q integer ticks, so phase-belt boundaries are exact.
    period = 4 * count * slots
    if count % 2 and spokes_per_phase <= 2:
        offset = slots
    elif count % 2:
        offset = count * repetitions * (2 if spokes_per_phase % 2 == 0 else 1)
    elif spokes_per_phase == 2:
        offset = 0
    else:
        offset = count * repetitions * (1 if spokes_per_phase % 4 == 0 else 2)

    start_slots = np.arange(0, slots, 1 if double else 2, dtype=np.int64)
    positions = (4 * count * ((start_slots * (pole_pairs % slots)) % slots)
                 + offset) % period
    starts = np.zeros((count, slots), dtype=int)
    phase_step = slots * (4 if count % 2 else 2)
    for phase in range(count):
        lower = slots * (count - 1) + phase * phase_step
        positive = (positions - lower) % period < 2 * slots
        negative = (positions - lower - period // 2) % period < 2 * slots
        starts[phase, start_slots[positive]] = 1
        starts[phase, start_slots[negative]] = -1

    # Every return keeps its phase and reverses the start's conductor direction.
    returns = -np.roll(starts, coil_span, axis=1)
    matrix = np.concatenate((starts, returns)) if double else starts + returns
    occupancy = np.abs(matrix).sum(axis=0)
    if not np.all(occupancy == (2 if double else 1)):
        raise ValueError('This layout does not fill each physical slot consistently.')
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
    """Generate a star-of-slots winding for odd or even phase counts."""
    slots, poles, span = _validated_dimensions(slots, poles, coil_span)
    phases = tuple(phases)
    phase_names(len(phases))
    if len(set(phases)) != len(phases):
        raise ValueError('Use distinct phase names.')
    span = effective_coil_span(slots, poles, is_double_layer, span)
    return _winding_matrix(slots, poles, bool(is_double_layer), span, len(phases)).copy()


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
            raise ValueError('The winding phase pattern does not match its physical '
                             'layout. Rebuild the winding layout.')
    return matrix
