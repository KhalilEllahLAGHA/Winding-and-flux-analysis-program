"""Phase identities and the odd/even phase convention used by Dolomites."""

import colorsys
import string

import numpy as np

DEFAULT_PHASE_COUNT = 3
MAX_PHASE_COUNT = 26


def phase_names(count):
    if not isinstance(count, (int, np.integer)) or not 1 <= count <= MAX_PHASE_COUNT:
        raise ValueError(f'Use between 1 and {MAX_PHASE_COUNT} phases.')
    return tuple(string.ascii_uppercase[:int(count)])


def phase_offsets_deg(count):
    phase_names(count)
    return np.arange(count, dtype=float) * (360.0/count if count % 2 else 180.0/count)


def phase_sin_factors(angle_deg, count):
    if not np.isfinite(float(angle_deg)):
        raise ValueError('Electrical angle must be finite.')
    return np.sin(np.radians(float(angle_deg) % 360 + phase_offsets_deg(count)))


def phase_color(phase):
    fixed = {'A': '#df4856', 'B': '#3277cf', 'C': '#159b75'}
    if phase in fixed:
        return fixed[phase]
    index = string.ascii_uppercase.index(phase)
    rgb = colorsys.hsv_to_rgb((0.11 + (index-3)*0.61803398875) % 1, 0.68, 0.78)
    return '#' + ''.join(f'{round(channel*255):02x}' for channel in rgb)


def matrix_layout(matrix, phase_count=None, is_double_layer=None):
    """Require explicit metadata for non-legacy or ambiguous row counts."""
    rows = np.asarray(matrix).shape[0]
    if phase_count is None:
        if rows not in (3, 6):
            raise ValueError('Specify phase count and layer layout for this connection matrix.')
        phase_count, is_double_layer = 3, rows == 6
    phase_names(phase_count)
    if is_double_layer is None:
        if rows not in (phase_count, 2*phase_count):
            raise ValueError('Connection matrix rows do not match the phase count.')
        is_double_layer = rows == 2*phase_count
    if rows != phase_count * (2 if is_double_layer else 1):
        raise ValueError('Connection matrix rows do not match its phases and layers.')
    return int(phase_count), bool(is_double_layer)
