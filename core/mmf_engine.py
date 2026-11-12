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

    def update_matrix_from_parameters(self, winding_pattern, is_double_layer,
                                      poles, coil_span=None):
        """Rebuild the connection matrix from winding parameters."""
        matrix = generate_connection_matrix(
            winding_pattern, list(PHASES), is_double_layer, poles,
            coil_span=coil_span)
        self.set_connection_matrix(matrix)
        return self.matrix

    def set_connection_matrix(self, matrix):
        """Set the connection matrix and recompute all MMF profiles."""
        matrix = np.asarray(matrix, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] == 0:
            raise ValueError('Connection matrix must contain phase rows and slots.')
        rows = matrix.shape[0]
        if rows not in (SINGLE_LAYER_ROWS, DOUBLE_LAYER_ROWS):
            raise ValueError(
                f"Connection matrix must have {SINGLE_LAYER_ROWS} or "
                f"{DOUBLE_LAYER_ROWS} rows, got {rows}")
        combined = matrix[:3] + matrix[3:] if rows == DOUBLE_LAYER_ROWS else matrix
        if not np.isfinite(matrix).all() or not np.allclose(combined.sum(axis=1), 0):
            raise ValueError('Each complete winding phase must have balanced slot ampere-turns.')

        pitch = 360 / matrix.shape[1]
        if not 0 < self.slot_arc_deg < pitch:
            self.slot_arc_deg = default_slot_arc_deg(matrix.shape[1])
        self.matrix = matrix.copy()
        self.n_slots = matrix.shape[1]
        self.slot_pitch_deg = 360 / self.n_slots
        self.tooth_arc_deg = self.slot_pitch_deg - self.slot_arc_deg

        # Amplitude/geometry changed: the cached base tooth MMF is now stale.
        self._tooth_mmf_base = None
        self.profiles = {}

        if rows == DOUBLE_LAYER_ROWS:
            self._calculate_double_layer_profiles(matrix)
        else:
            self._calculate_single_layer_profiles(matrix)

        self.profiles['resultant'] = self.compute_resultant_profile(self.wt_angle_deg)

    def get_profile_data(self, phase_name, layer=None, wt_deg=None):
        """Return (angles, values) for a phase ('A'/'B'/'C' or 'resultant').

        ``layer`` may be 'top', 'bot', or 'sum' for double layer windings.
        A supplied Wt returns the instantaneous contribution of that phase.
        Without Wt the phase profile is its peak-current reference.
        Returns (None, None) when the profile has not been computed.
        """
        if phase_name == 'resultant':
            if wt_deg is not None:
                result = self.compute_resultant_profile(wt_deg)
                return result if result is not None else (None, None)
            key = 'resultant'
        elif layer:
            key = f'{phase_name}_{layer}'
        else:
            key = phase_name

        profile = self.profiles.get(key)
        if profile is None:
            return None, None
        if wt_deg is not None and phase_name in PHASES:
            factor = _three_phase_sin_factors(wt_deg)[PHASES.index(phase_name)]
            return profile[0], profile[1] * factor
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
        slot_arc_deg = _finite_value(slot_arc_deg, 'Slot arc')
        pitch = self.slot_pitch_deg or 360.0
        if not 0 < slot_arc_deg < pitch:
            raise ValueError('Slot arc must be positive and smaller than the slot pitch.')
        self.slot_arc_deg = slot_arc_deg
        self._recalculate()

    def update_turns(self, turns):
        """Update the number of turns and recompute profiles."""
        self.turns = _finite_value(turns, 'Turns')
        self._recalculate()

    def update_current(self, current_a):
        """Update the phase current (same for all phases) and recompute."""
        self.phase_current_a = _finite_value(current_a, 'Current')
        self._recalculate()

    def update_wt_angle(self, wt_deg):
        """Update the electrical angle Wt and recompute only the resultant.

        Wt affects only the ``A·sin + B·sin + C·sin`` combination, not the
        per-phase profiles, so we skip the (much heavier) rebuild of the
        continuous A/B/C profiles here. This makes Wt-spin and animation
        sweeps ~30x cheaper while producing identical output.
        """
        wt_deg = _finite_value(wt_deg, 'Electrical angle')
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

        # A layer may carry net current whose return lies in the other layer.
        # Plot its periodic spatial component. The two removed means cancel
        # in the complete phase, preserving its exact winding function.
        top_tooth = [self._tooth_mmf_from_phase((row - row.mean()) * amp)
                     for row in top_rows]
        bottom_tooth = [self._tooth_mmf_from_phase((row - row.mean()) * amp)
                        for row in bottom_rows]

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
        """Winding function on the tooth immediately before each slot.

        ``phase_mmf`` stores half the slot ampere-turns. Tooth k precedes
        slot k in the machine geometry, so F[k+1] - F[k] = NI[k]. The
        arbitrary integration constant is chosen for zero mean tooth MMF.
        """
        slot_ni = 2 * np.asarray(phase_mmf, dtype=float)
        if slot_ni.ndim != 1 or len(slot_ni) != self.n_slots:
            raise ValueError('Slot excitation must match the winding slot count.')
        if not np.isfinite(slot_ni).all():
            raise ValueError('Slot excitation must be finite.')
        if abs(float(slot_ni.sum())) > max(1e-9, float(np.abs(slot_ni).sum()) * 1e-9):
            raise ValueError('Each winding phase must have balanced slot ampere-turns.')
        tooth_mmf = np.concatenate(([0.0], np.cumsum(slot_ni[:-1])))
        return tooth_mmf - tooth_mmf.mean()

    def _build_continuous_profiles(self, tooth_value_arrays):
        """Interpolate per-tooth values into continuous 0-360° profiles.

        Tooth regions are constant; slot regions interpolate linearly to the
        next tooth. Returns (angles, [values_per_input_array]).
        """
        slot_pitch = self.tooth_arc_deg + self.slot_arc_deg

        if not 0 < self.slot_arc_deg < slot_pitch:
            raise ValueError('Slot arc must be positive and smaller than the slot pitch.')
        # Exact breakpoints preserve flat teeth and linear slot transitions.
        # Include both ends of the period so exports and plots close at 360.
        starts = np.arange(self.n_slots) * slot_pitch
        angles = np.unique(np.concatenate((
            np.linspace(0, 360, MMF_PROFILE_RESOLUTION, endpoint=False),
            starts, starts + self.tooth_arc_deg,
            starts + self.tooth_arc_deg / 2, [360.0])))
        wrapped = np.mod(angles, 360.0)
        sector = np.floor(wrapped / slot_pitch).astype(int) % self.n_slots
        local_angle = wrapped - sector * slot_pitch
        fraction = np.clip((local_angle - self.tooth_arc_deg)
                           / self.slot_arc_deg, 0.0, 1.0)
        profiles = []
        for tooth_values in tooth_value_arrays:
            values = np.asarray(tooth_values, dtype=float)
            profiles.append((1 - fraction) * values[sector]
                            + fraction * values[(sector + 1) % self.n_slots])
        return angles, profiles


def _split_double_layer_rows(matrix):
    """Preserve the actual phase/sign of each physical winding layer."""
    return np.asarray(matrix[:3]), np.asarray(matrix[3:])


def _three_phase_sin_factors(wt_deg):
    """sin factors for phases A, B, C at electrical angle Wt."""
    wt_rad = np.radians(_finite_value(wt_deg, 'Electrical angle') % 360)
    return (np.sin(wt_rad),
            np.sin(wt_rad + np.radians(120)),
            np.sin(wt_rad - np.radians(120)))


def _finite_value(value, label):
    value = float(value)
    if not np.isfinite(value):
        raise ValueError(f'{label} must be finite.')
    return value


