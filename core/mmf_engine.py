"""MMF profile calculation engine (formerly ``mmf_calculation_engine.py``).

Computes tooth-based MMF profiles per phase from a connection matrix and
combines them into the rotating resultant
``A·sin(Wt) + B·sin(Wt+120°) + C·sin(Wt-120°)``.

Profiles are stored as ``(angles, values)`` NumPy array pairs instead of the
previous lists of (angle, value) tuples, which keeps the per-frame resultant
computation of the animation vectorised.
"""

import numpy as np

from core.connection_matrix import generate_connection_matrix
from utils.constants import (
    DEFAULT_PHASE_CURRENT_A,
    DEFAULT_TURNS,
    DEFAULT_WT_ANGLE_DEG,
    MMF_PROFILE_RESOLUTION,
    PHASES,
    default_slot_arc_deg,
)

SINGLE_LAYER_ROWS = 3
DOUBLE_LAYER_ROWS = 6


class MMFCalculationEngine:
    """Stateful MMF calculator shared by the MMF tab and the flux solver."""

    def __init__(self):
        self.matrix = None
        self.n_slots = 0
        self.slot_arc_deg = 5.0
        self.tooth_arc_deg = 0.0
        self.slot_pitch_deg = 0.0
        self.turns = DEFAULT_TURNS
        self.phase_current_a = DEFAULT_PHASE_CURRENT_A
        self.wt_angle_deg = DEFAULT_WT_ANGLE_DEG
        # Keys: 'A', 'B', 'C', '<phase>_top', '<phase>_bot', '<phase>_sum',
        # 'resultant'. Values: (angles, values) NumPy array pairs.
        self.profiles = {}
        # Cached Wt-independent per-phase tooth MMF ({'A','B','C': array}).
        # Invalidated whenever the matrix or amplitude parameters change.
        self._tooth_mmf_base = None

    # ------------------------------------------------------------------ API

    def update_matrix_from_parameters(self, winding_pattern, is_double_layer, poles):
        """Rebuild the connection matrix from winding parameters."""
        self.matrix = generate_connection_matrix(
            winding_pattern, list(PHASES), is_double_layer, poles)
        self.slot_arc_deg = default_slot_arc_deg(self.matrix.shape[1])
        self.set_connection_matrix(self.matrix)
        return self.matrix

    def set_connection_matrix(self, matrix):
        """Set the connection matrix and recompute all MMF profiles."""
        rows = matrix.shape[0]
        if rows not in (SINGLE_LAYER_ROWS, DOUBLE_LAYER_ROWS):
            raise ValueError(
                f"Connection matrix must have {SINGLE_LAYER_ROWS} or "
                f"{DOUBLE_LAYER_ROWS} rows, got {rows}")

        self.matrix = matrix
        self.n_slots = matrix.shape[1]
        self.slot_pitch_deg = 360 / self.n_slots
        self.tooth_arc_deg = self.slot_pitch_deg - self.slot_arc_deg

        # Amplitude/geometry changed: the cached base tooth MMF is now stale.
        self._tooth_mmf_base = None

        if rows == DOUBLE_LAYER_ROWS:
            self._calculate_double_layer_profiles(matrix)
        else:
            self._calculate_single_layer_profiles(matrix)

        self.profiles['resultant'] = self.compute_resultant_profile(self.wt_angle_deg)

    def get_profile_data(self, phase_name, layer=None):
        """Return (angles, values) for a phase ('A'/'B'/'C' or 'resultant').

        ``layer`` may be 'top', 'bot', or 'sum' for double layer windings.
        Returns (None, None) when the profile has not been computed.
        """
        if phase_name == 'resultant':
            key = 'resultant'
        elif layer:
            key = f'{phase_name}_{layer}'
        else:
            key = phase_name

        profile = self.profiles.get(key)
        if profile is None:
            return None, None
        return profile

    def compute_resultant_profile(self, wt_deg):
        """Resultant profile at an arbitrary Wt without mutating engine state.

        Used by the animation so sweeping Wt never corrupts the configured
        angle (the previous implementation overwrote it permanently).
        """
        try:
            angles, values_a = self.profiles['A']
            _, values_b = self.profiles['B']
            _, values_c = self.profiles['C']
        except KeyError:
            return None

        sin_a, sin_b, sin_c = _three_phase_sin_factors(wt_deg)
        return angles, values_a * sin_a + values_b * sin_b + values_c * sin_c

    def get_tooth_mmf_data(self, wt_deg=None):
        """Resultant MMF per tooth, used by the teeth/slot MMF calculator.

        Returns {'Resultant': {'tooth_mmf': [...]}} or None when no matrix
        is loaded.
        """
        if self.matrix is None:
            return None

        # The per-phase tooth MMF is Wt-independent (only the sin combination
        # below depends on Wt), so cache it. This turns each animation frame's
        # tooth-MMF step into a couple of vectorised multiply-adds instead of
        # re-running the O(n_slots²) group-finding for all three phases.
        tooth_mmf = self._tooth_mmf_base
        if tooth_mmf is None:
            phase_mmf = self._phase_mmf_per_slot(self.matrix)
            if phase_mmf is None:
                return None
            tooth_mmf = {phase: self._tooth_mmf_from_phase(values)
                         for phase, values in phase_mmf.items()}
            self._tooth_mmf_base = tooth_mmf

        if wt_deg is None:
            wt_deg = self.wt_angle_deg
        sin_a, sin_b, sin_c = _three_phase_sin_factors(wt_deg)
        resultant = (tooth_mmf['A'] * sin_a
                     + tooth_mmf['B'] * sin_b
                     + tooth_mmf['C'] * sin_c)

        return {'Resultant': {'tooth_mmf': resultant.tolist()}}

    # ------------------------------------------------------ parameter setters

    def update_slot_arc(self, slot_arc_deg):
        """Update the slot opening angle and recompute profiles."""
        self.slot_arc_deg = slot_arc_deg
        self._recalculate()

    def update_turns(self, turns):
        """Update the number of turns and recompute profiles."""
        self.turns = turns
        self._recalculate()

    def update_current(self, current_a):
        """Update the phase current (same for all phases) and recompute."""
        self.phase_current_a = current_a
        self._recalculate()

    def update_wt_angle(self, wt_deg):
        """Update the electrical angle Wt and recompute only the resultant.

        Wt affects only the ``A·sin + B·sin + C·sin`` combination, not the
        per-phase profiles, so we skip the (much heavier) rebuild of the
        continuous A/B/C profiles here. This makes Wt-spin and animation
        sweeps ~30x cheaper while producing identical output.
        """
        self.wt_angle_deg = wt_deg
        if self.matrix is not None and 'A' in self.profiles:
            self.profiles['resultant'] = self.compute_resultant_profile(wt_deg)
        else:
            self._recalculate()

    def _recalculate(self):
        if self.matrix is not None:
            self.set_connection_matrix(self.matrix)

    # ----------------------------------------------------- profile assembly

    def _calculate_single_layer_profiles(self, matrix):
        phase_a, phase_b, phase_c = matrix
        amp = self.phase_current_a * self.turns / 2

        tooth_values = [self._tooth_mmf_from_phase(row * amp)
                        for row in (phase_a, phase_b, phase_c)]
        angles, value_arrays = self._build_continuous_profiles(tooth_values)

        for phase, values in zip(PHASES, value_arrays):
            self.profiles[phase] = (angles, values)

    def _calculate_double_layer_profiles(self, matrix):
        top_rows, bottom_rows = _split_double_layer_rows(matrix)

        # Phase current is shared equally between the two layers.
        amp = (self.phase_current_a / 2) * self.turns / 2

        top_tooth = [self._tooth_mmf_from_phase(row * amp) for row in top_rows]
        bottom_tooth = [self._tooth_mmf_from_phase(row * amp) for row in bottom_rows]

        angles, top_values = self._build_continuous_profiles(top_tooth)
        _, bottom_values = self._build_continuous_profiles(bottom_tooth)

        for phase, top, bottom in zip(PHASES, top_values, bottom_values):
            self.profiles[f'{phase}_top'] = (angles, top)
            self.profiles[f'{phase}_bot'] = (angles, bottom)
            summed = top + bottom
            self.profiles[f'{phase}_sum'] = (angles, summed)
            # The per-phase view of a double layer winding is the layer sum.
            self.profiles[phase] = (angles, summed)

    def _phase_mmf_per_slot(self, matrix):
        """Raw per-slot MMF for each phase (before the tooth-based logic)."""
        rows = matrix.shape[0]
        amp = self.phase_current_a * self.turns / 2

        if rows == SINGLE_LAYER_ROWS:
            phase_a, phase_b, phase_c = matrix
            scale = amp
        elif rows == DOUBLE_LAYER_ROWS:
            top_a, top_b, top_c, bot_a, bot_b, bot_c = matrix
            phase_a, phase_b, phase_c = top_a + bot_a, top_b + bot_b, top_c + bot_c
            scale = amp / 2  # current split between layers
        else:
            return None

        return {'A': phase_a * scale, 'B': phase_b * scale, 'C': phase_c * scale}

    # ----------------------------------------------------- tooth-based logic

    def _tooth_mmf_from_phase(self, phase_mmf):
        """MMF at each tooth centre from per-slot phase MMF.

        Starts integrating at the slot of the widest constant-MMF group so
        the profile is symmetric, then accumulates 2x the slot MMF around
        the circular machine.
        """
        tooth_mmf = np.zeros_like(phase_mmf, dtype=float)

        anchor = _widest_group_anchor(phase_mmf)
        anchor_group_size = _count_equal_around(phase_mmf, anchor)

        for offset in range(self.n_slots):
            i = (anchor + offset) % self.n_slots
            if offset == 0:
                same_on_left = _count_equal_left(phase_mmf, i)
                tooth_mmf[i] = (-anchor_group_size * phase_mmf[anchor]
                                + 2 * phase_mmf[i] * (same_on_left + 1))
            else:
                previous = (anchor + offset - 1) % self.n_slots
                tooth_mmf[i] = tooth_mmf[previous] + 2 * phase_mmf[i]
        return tooth_mmf

    def _build_continuous_profiles(self, tooth_value_arrays):
        """Interpolate per-tooth values into continuous 0-360° profiles.

        Tooth regions are constant; slot regions interpolate linearly to the
        next tooth. Returns (angles, [values_per_input_array]).
        """
        angles = np.linspace(0, 360, MMF_PROFILE_RESOLUTION, endpoint=False)
        slot_pitch = self.tooth_arc_deg + self.slot_arc_deg

        tooth_centers = np.arange(0, self.n_slots * slot_pitch, slot_pitch) % 360
        tooth_starts = (tooth_centers - self.tooth_arc_deg / 2) % 360
        tooth_ends = (tooth_centers + self.tooth_arc_deg / 2) % 360

        profiles = [np.zeros_like(angles) for _ in tooth_value_arrays]

        for i in range(self.n_slots):
            next_i = (i + 1) % self.n_slots
            start, end, next_start = tooth_starts[i], tooth_ends[i], tooth_starts[next_i]

            # Tooth region: constant value (mask handles the 360° wrap).
            if start < end:
                tooth_mask = (angles >= start) & (angles < end)
            else:
                tooth_mask = (angles >= start) | (angles < end)

            # Slot region: linear interpolation toward the next tooth.
            if end < next_start:
                slot_mask = (angles >= end) & (angles < next_start)
                t = (angles[slot_mask] - end) / (next_start - end)
            else:
                slot_mask = (angles >= end) | (angles < next_start)
                t = (angles[slot_mask] - end) % 360 / ((next_start - end) % 360)

            for profile, tooth_values in zip(profiles, tooth_value_arrays):
                profile[tooth_mask] = tooth_values[i]
                profile[slot_mask] = ((1 - t) * tooth_values[i]
                                      + t * tooth_values[next_i])

        return angles, profiles


def _split_double_layer_rows(matrix):
    """Combine the 6-row matrix into per-phase top/bottom contributions.

    Slots where both layers carry the same phase (|sum| == 2) split equally;
    slots with a single coil side (|sum| == 1) are attributed to the top
    layer, matching the original implementation.
    """
    top_a, top_b, top_c, bot_a, bot_b, bot_c = matrix
    combined = [top_a + bot_a, top_b + bot_b, top_c + bot_c]

    top_rows, bottom_rows = [], []
    for row in combined:
        both_layers = np.abs(row) == 2
        top_rows.append(np.where(both_layers, row // 2, row))
        bottom_rows.append(np.where(both_layers, row // 2, 0))
    return top_rows, bottom_rows


def _three_phase_sin_factors(wt_deg):
    """sin factors for phases A, B, C at electrical angle Wt."""
    wt_rad = np.radians(wt_deg)
    return (np.sin(wt_rad),
            np.sin(wt_rad + np.radians(120)),
            np.sin(wt_rad - np.radians(120)))


def _count_equal_around(phase_mmf, index):
    """Size of the circular group of equal values containing ``index``."""
    if phase_mmf[index] == 0:
        return 1

    target = phase_mmf[index]
    count = 1
    n = len(phase_mmf)

    i = (index + 1) % n
    while i != index and phase_mmf[i] == target:
        count += 1
        i = (i + 1) % n

    i = (index - 1) % n
    while i != index and phase_mmf[i] == target:
        count += 1
        i = (i - 1) % n

    return count


def _count_equal_left(phase_mmf, index):
    """Number of consecutive equal values immediately left of ``index``
    (circular)."""
    target = phase_mmf[index]
    count = 0
    n = len(phase_mmf)

    for offset in range(1, n):
        if phase_mmf[(index - offset) % n] == target:
            count += 1
        else:
            break
    return count


def _widest_group_anchor(phase_mmf):
    """Index of the non-zero element with the widest equal-value group.

    Returns -1 when the array contains no non-zero element.
    """
    max_count = 0
    best_index = -1

    for i, value in enumerate(phase_mmf):
        if value != 0:
            count = _count_equal_around(phase_mmf, i)
            if count > max_count:
                max_count = count
                best_index = i

    return best_index
