"""Application-wide named constants.

Every default value that was previously hard-coded in several places
(machine geometry, winding defaults, mesh presets, ...) lives here so the
UI and the calculation engines stay in sync.
"""

import numpy as np

# --- Physics ---------------------------------------------------------------
MU0 = 4 * np.pi * 1e-7  # Permeability of free space [H/m]
GRID_FREQUENCY_HZ = 50  # Mains frequency used for synchronous-speed estimates

# --- Three-phase winding ---------------------------------------------------
PHASES = ('A', 'B', 'C')
PHASE_COUNT = len(PHASES)

DEFAULT_NUM_SLOTS = 36
SLOT_COUNT_RANGE = (6, 72)
DEFAULT_PAIR_POLES = 2

DEFAULT_TURNS = 204
TURNS_RANGE = (1, 1000)
DEFAULT_PHASE_CURRENT_A = 2.8
PHASE_CURRENT_RANGE_A = (0.1, 1000.0)
DEFAULT_WT_ANGLE_DEG = 90
WT_ANGLE_RANGE_DEG = (0, 360)

# Angular resolution (number of samples over 360°) of continuous MMF profiles.
MMF_PROFILE_RESOLUTION = 1000

# --- Machine geometry defaults (mm / degrees) -------------------------------
DEFAULT_MACHINE_PARAMS = {
    'stator_outer_radius': 69.15,
    'stator_inner_radius': 41.25,
    'air_gap': 1.0,
    'shaft_radius': 18.65,
    'num_slots': DEFAULT_NUM_SLOTS,
    'slot_angle': 5.0,
    'slot_height': 12.6,
}
DEFAULT_AXIAL_LENGTH_MM = 110.0

DEFAULT_RELATIVE_PERMEABILITIES = {
    'ur_stator': 4000.0,
    'ur_rotor': 4000.0,
    'ur_air': 1.0,
}

# --- Meshing ----------------------------------------------------------------
# Quality presets indexed by the "Quality Preset" combo box position.
MESH_PRESETS = {
    0: {'rotor': 3, 'slot': 3, 'airgap': 5, 'stator': 3,
        'quality': 'fast', 'angle_divider': 1},
    1: {'rotor': 10, 'slot': 10, 'airgap': 10, 'stator': 10,
        'quality': 'midspeed', 'angle_divider': 3},
    2: {'rotor': 20, 'slot': 20, 'airgap': 30, 'stator': 20,
        'quality': 'slow', 'angle_divider': 10},
}
DEFAULT_MESH_PRESET_INDEX = 1

# --- Animation --------------------------------------------------------------
# Wt increment per frame for the resultant-MMF animation, by speed label.
ANIMATION_SPEED_STEPS_DEG = {'Slow': 1.0, 'Mid': 2.5, 'Fast': 7.5}
DEFAULT_ANIMATION_SPEED = 'Mid'
ANIMATION_FRAME_INTERVAL_MS = 50


def default_slot_arc_deg(num_slots):
    """Default slot opening angle: half of the slot pitch."""
    return 360 / (2 * num_slots)


def max_slot_arc_deg(num_slots):
    """Upper bound for the slot opening so a tooth always remains."""
    return (360 / num_slots) - 0.5
