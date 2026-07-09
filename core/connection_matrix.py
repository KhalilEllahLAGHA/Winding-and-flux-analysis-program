"""Connection-matrix construction for single and double layer windings
(formerly ``matrix.py``)."""

import numpy as np


def generate_connection_matrix(winding_pattern, phases, is_double_layer, poles):
    """Build the phase/slot connection matrix.

    Each entry is +1/-1 for a coil side of the row's phase in that slot
    (sign = current direction) or 0 when the phase is absent. Double layer
    windings get one row block for the top layer and one for the bottom.
    """
    rows = len(phases) * 2 if is_double_layer else len(phases)
    matrix = np.zeros((rows, len(winding_pattern)), dtype=int)
    phase_indices = {phase: idx for idx, phase in enumerate(phases)}

    if is_double_layer:
        top_phases = [top for top, _ in winding_pattern]
        bottom_phases = [bottom for _, bottom in winding_pattern]
        top_signs = _alternating_phase_signs(top_phases)
        bottom_signs = _alternating_phase_signs(bottom_phases)

        for slot, (top_phase, bottom_phase) in enumerate(winding_pattern):
            if top_phase in phase_indices:
                matrix[phase_indices[top_phase]][slot] = top_signs[slot]
            if bottom_phase in phase_indices:
                row = len(phases) + phase_indices[bottom_phase]
                matrix[row][slot] = bottom_signs[slot]
    else:
        layer_phases = [phase for phase, _ in winding_pattern]
        signs = _alternating_phase_signs(layer_phases)

        for slot, (phase, _) in enumerate(winding_pattern):
            if phase in phase_indices:
                matrix[phase_indices[phase]][slot] = signs[slot]

    return matrix


def _alternating_phase_signs(pattern):
    """Assign alternating current directions to consecutive phase groups.

    The sign flips every time the phase changes along the slot sequence,
    then the whole sequence is normalised so the first 'A' group is +1.
    """
    previous_phase = None
    current_sign = 1
    signs = []

    for phase in pattern:
        if phase != previous_phase:
            current_sign *= -1
            previous_phase = phase
        signs.append(current_sign)

    if 'A' in pattern:
        first_a_index = pattern.index('A')
        if signs[first_a_index] != 1:
            signs = [-sign for sign in signs]
    return signs
