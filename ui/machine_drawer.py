"""Matplotlib machine cross-section drawing
(formerly ``Meshing_machine_drawer.py``)."""

import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Wedge

from utils.constants import DEFAULT_MACHINE_PARAMS

STATOR_COLOR = "#4a90e2"
ROTOR_COLOR = "#666666"
AIR_GAP_COLOR = "#CCCCCC"


class MachineDrawer:
    """Draws stator yoke, teeth/slots, air gap, rotor core, and shaft."""

    def __init__(self, figure, ax):
        self.figure = figure
        self.ax = ax

    def draw_machine(self, params):
        """Draw the machine cross-section, or an error notice when the
        parameters are inconsistent."""
        self.ax.clear()
        self._apply_white_theme()

        try:
            geometry = _resolve_geometry(params)
            self._draw_geometry(geometry)
        except Exception as error:
            self._draw_error(str(error))

        self.figure.canvas.draw()

    def _apply_white_theme(self):
        self.ax.set_facecolor('white')
        self.figure.patch.set_facecolor('white')
        self.ax.tick_params(colors='black', which='both')
        for spine in self.ax.spines.values():
            spine.set_color('black')
        self.ax.xaxis.label.set_color('black')
        self.ax.yaxis.label.set_color('black')

    def _draw_geometry(self, geometry):
        ax = self.ax

        stator_yoke = Wedge(
            (0, 0), geometry['stator_outer_radius'], 0, 360,
            width=geometry['stator_outer_radius'] - geometry['tooth_tip_radius'],
            facecolor=STATOR_COLOR, edgecolor='black', alpha=0.8, linewidth=1.0)
        ax.add_patch(stator_yoke)

        for i in range(geometry['num_slots']):
            tooth_start = i * geometry['slot_pitch']
            if geometry['tooth_angle'] > 0:
                ax.add_patch(Wedge(
                    (0, 0), geometry['tooth_tip_radius'],
                    tooth_start, tooth_start + geometry['tooth_angle'],
                    width=geometry['slot_height'], facecolor=STATOR_COLOR,
                    edgecolor='black', alpha=0.8, linewidth=1.0))

            if geometry['slot_angle'] > 0:
                slot_start = tooth_start + geometry['tooth_angle']
                ax.add_patch(Wedge(
                    (0, 0), geometry['tooth_tip_radius'],
                    slot_start, slot_start + geometry['slot_angle'],
                    width=geometry['slot_height'], facecolor="white",
                    edgecolor='black', alpha=0.8, linewidth=1.0))

        ax.add_patch(Wedge(
            (0, 0), geometry['stator_inner_radius'], 0, 360,
            width=geometry['air_gap'], facecolor=AIR_GAP_COLOR,
            edgecolor='black', alpha=0.6, linewidth=1.0))

        ax.add_patch(Wedge(
            (0, 0), geometry['rotor_outer_radius'], 0, 360,
            width=geometry['rotor_outer_radius'] - geometry['shaft_radius'],
            facecolor=ROTOR_COLOR, edgecolor='black', alpha=0.7, linewidth=1.0))

        ax.add_patch(Circle(
            (0, 0), geometry['shaft_radius'], facecolor="white",
            edgecolor='black', alpha=1.0, linewidth=1.0))

        ax.set_aspect('equal')
        limit = geometry['stator_outer_radius'] * 1.2
        ax.set_xlim(-limit, limit)
        ax.set_ylim(-limit, limit)
        ax.set_title(f"Machine Cross-Section - {geometry['num_slots']} Slots",
                     color='black', fontsize=14, pad=20)
        self._draw_legend()

    def _draw_legend(self):
        legend_elements = [
            plt.Line2D([0], [0], marker='s', color='black',
                       markerfacecolor=STATOR_COLOR, markersize=10, label='Stator'),
            plt.Line2D([0], [0], marker='s', color='black',
                       markerfacecolor=ROTOR_COLOR, markersize=10, label='Rotor Core'),
            plt.Line2D([0], [0], marker='s', color='black',
                       markerfacecolor=AIR_GAP_COLOR, markersize=10, label='Air Gap'),
            plt.Line2D([0], [0], marker='s', color='black',
                       markerfacecolor='white', markersize=10, label='Shaft',
                       markeredgecolor='black'),
        ]
        legend = self.ax.legend(handles=legend_elements, loc='upper right',
                                bbox_to_anchor=(1.15, 1))
        legend.get_frame().set_facecolor('white')
        legend.get_frame().set_edgecolor('black')
        legend.get_frame().set_alpha(0.9)
        for text in legend.get_texts():
            text.set_color('black')

    def _draw_error(self, message):
        self.ax.text(0, 0,
                     f"Invalid input parameters\nPlease check values\n{message[:100]}...",
                     ha='center', va='center', fontsize=12, color='red',
                     bbox=dict(boxstyle="round,pad=0.5", facecolor="#ffcccc",
                               alpha=0.8, edgecolor='red'))
        self.ax.set_aspect('equal')
        self.ax.set_xlim(-100, 100)
        self.ax.set_ylim(-100, 100)
        self.ax.set_title("Machine Cross-Section - Invalid Parameters",
                          color='black', fontsize=14, pad=20)


def _resolve_geometry(params):
    """Validate input parameters and derive the radii needed for drawing.

    Accepts both naming conventions used by callers
    (``stator_outer_radius``/``stator_rout``, ``air_gap``/``air_gap_thickness``).
    """
    defaults = DEFAULT_MACHINE_PARAMS
    stator_outer_radius = params.get(
        'stator_outer_radius', params.get('stator_rout', defaults['stator_outer_radius']))
    stator_inner_radius = params.get(
        'stator_inner_radius', params.get('stator_rin', defaults['stator_inner_radius']))
    num_slots = params.get('num_slots', defaults['num_slots'])
    slot_angle = params.get('slot_angle', defaults['slot_angle'])
    slot_height = params.get('slot_height', defaults['slot_height'])
    air_gap = params.get('air_gap', params.get('air_gap_thickness', defaults['air_gap']))
    shaft_radius = params.get('shaft_radius', defaults['shaft_radius'])

    positive_required = [stator_outer_radius, stator_inner_radius,
                         num_slots, air_gap, shaft_radius]
    if any(value <= 0 for value in positive_required):
        raise ValueError("Invalid parameter values: all dimensions must be positive")

    if stator_inner_radius >= stator_outer_radius:
        raise ValueError("Stator inner radius must be less than outer radius")

    if num_slots < 3:
        raise ValueError("Number of slots must be at least 3")

    slot_pitch = 360 / num_slots
    tooth_tip_radius = stator_inner_radius + slot_height
    rotor_outer_radius = stator_inner_radius - air_gap

    # Cap the tooth height so teeth never poke through the stator yoke.
    if tooth_tip_radius >= stator_outer_radius:
        tooth_tip_radius = stator_outer_radius * 0.95
        slot_height = tooth_tip_radius - stator_inner_radius

    if rotor_outer_radius <= shaft_radius:
        raise ValueError(
            "Air gap too large: rotor outer radius must be greater than shaft radius")

    return {
        'stator_outer_radius': stator_outer_radius,
        'stator_inner_radius': stator_inner_radius,
        'num_slots': int(num_slots),
        'slot_angle': slot_angle,
        'slot_height': slot_height,
        'air_gap': air_gap,
        'shaft_radius': shaft_radius,
        'slot_pitch': slot_pitch,
        'tooth_angle': slot_pitch - slot_angle,
        'tooth_tip_radius': tooth_tip_radius,
        'rotor_outer_radius': rotor_outer_radius,
    }
