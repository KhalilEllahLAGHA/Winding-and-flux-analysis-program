"""Connection-matrix construction for single and double layer windings."""

import math

import numpy as np


def _validated_dimensions(slots, poles, coil_span):
    if (not isinstance(slots, (int, np.integer)) or slots < 3
            or not isinstance(poles, (int, np.integer)) or poles < 2 or poles % 2):
        raise ValueError('Use an integer slot count and a positive even pole count.')
    if coil_span is None:
        coil_span = slots // poles
    if (not isinstance(coil_span, (int, np.integer))
            or not 1 <= coil_span <= slots):
        raise ValueError('Coil span must be an integer between 1 and the slot count.')
    return int(slots), int(poles), int(coil_span)


def _signed_phase_belt(slot, slots, poles):
    """Six signed 60-degree belts of the actual electrical slot angle.

    Electrical angle is 180*poles*slot/slots degrees. Integer arithmetic
    avoids drifting to the neighboring belt at exact 60-degree boundaries.
    Belt order preserves the established A+, C-, B+, A-, C+, B- convention.
    """
    belts = ((0, 1), (2, -1), (1, 1), (0, -1), (2, 1), (1, -1))
    return belts[(3 * poles * slot // slots) % 6]


def _validate_three_phase_layout(matrix, slots, poles, coil_span):
    """Require equal phase conductors and balanced working-harmonic axes."""
    double = matrix.shape[0] == 6
    complete = matrix[:3] + matrix[3:] if double else matrix
    counts = np.abs(matrix[:3]).sum(axis=1)
    if double:
        counts += np.abs(matrix[3:]).sum(axis=1)
    reason = None
    if not np.all(counts == counts[0]) or counts[0] == 0:
        reason = 'the phase conductor counts are unequal'
    elif not np.all(complete.sum(axis=1) == 0):
        reason = 'a phase has no balanced coil return path'
    elif np.any(complete):
        angles = 2 * np.pi * np.arange(slots) / slots
        phasors = complete @ np.exp(-1j * (poles // 2) * angles)
        amplitudes = np.abs(phasors)
        axes = np.exp(1j * np.radians([0, -120, 120]))
        if np.min(amplitudes) <= 1e-10:
            reason = 'the requested working harmonic is absent'
        elif (not np.allclose(amplitudes, amplitudes[0], rtol=1e-8, atol=1e-10)
              or not np.allclose(phasors / phasors[0], axes, atol=1e-8, rtol=1e-8)):
            reason = 'the working-harmonic phase axes are not balanced at 120 degrees'
    # An intentional full-electrical-period coil pitch can cancel all slot
    # excitation. Keep that genuine zero case rather than fabricate a field.
    if reason:
        raise ValueError(
            f'Cannot construct a balanced {poles}-pole three-phase winding '
            f'with {slots} slots and uniform coil span {coil_span}: {reason}.')


def build_winding_connection_matrix(slots, poles, is_double_layer,
                                     coil_span=None, phases=('A', 'B', 'C')):
    """Construct signed coil sides from electrical angle and coil topology.

    A double layer has a signed coil start in every top slot and its exact
    opposite return in the bottom slot displaced by coil_span. A single
    layer pairs the slot cycles j -> j+coil_span, using each slot once.
    Odd cycles cannot be covered by those uniform-span coil pairs.
    """
    slots, poles, coil_span = _validated_dimensions(slots, poles, coil_span)
    if len(phases) != 3 or len(set(phases)) != 3:
        raise ValueError('Exactly three distinct phase names are required.')
    matrix = np.zeros((6 if is_double_layer else 3, slots), dtype=int)
    if is_double_layer:
        for slot in range(slots):
            phase, sign = _signed_phase_belt(slot, slots, poles)
            matrix[phase, slot] = sign
        matrix[3:] = -np.roll(matrix[:3], coil_span, axis=1)
    else:
        cycles = math.gcd(slots, coil_span)
        cycle_length = slots // cycles
        if cycle_length % 2:
            raise ValueError(
                f'A single-layer winding with {slots} slots and uniform coil '
                f'span {coil_span} cannot pair every slot: its slot cycles '
                f'contain {cycle_length} slots, an odd number. Choose another '
                'coil span or use a double-layer winding.')
        for root in range(cycles):
            cycle = [(root + step * coil_span) % slots
                     for step in range(cycle_length)]
            for index in range(0, cycle_length, 2):
                start, end = cycle[index:index + 2]
                phase, sign = _signed_phase_belt(start, slots, poles)
                matrix[phase, start] = sign
                matrix[phase, end] = -sign
    _validate_three_phase_layout(matrix, slots, poles, coil_span)
    return matrix


def phase_pattern_from_matrix(matrix, phases=('A', 'B', 'C')):
    """Phase-only diagram labels from the very same physical coil matrix."""
    double = matrix.shape[0] == 6
    pattern = []
    for slot in range(matrix.shape[1]):
        top = np.flatnonzero(matrix[:3, slot])
        bottom = np.flatnonzero(matrix[3:, slot]) if double else []
        pattern.append((phases[int(top[0])] if len(top) else None,
                        phases[int(bottom[0])] if len(bottom) else None))
    return pattern


def generate_connection_matrix(winding_pattern, phases, is_double_layer, poles,
                               coil_span=None):
    """Build the phase/slot connection matrix.

    Each entry is +1/-1 for a coil side of the row's phase in that slot
    (sign = current direction) or 0 when the phase is absent. Double layer
    windings get one row block for the top layer and one for the bottom.
    A coil's return side has the opposite sign in the slot displaced by its
    coil span. Phase names alone cannot determine that return-side polarity.
    """
    matrix = build_winding_connection_matrix(
        len(winding_pattern), poles, is_double_layer, coil_span, phases)
    expected = phase_pattern_from_matrix(matrix, phases)
    for supplied, physical in zip(winding_pattern, expected):
        # Earlier callers supplied only the top phase labels. An omitted
        # double-layer return is fully defined by the explicit coil span.
        if (len(supplied) != 2 or supplied[0] != physical[0]
                or (supplied[1] != physical[1]
                    and not (is_double_layer and supplied[1] is None))):
            raise ValueError('The winding phase pattern does not match its slot '
                             'count, pole count and coil span. Rebuild the winding layout.')
    return matrix
