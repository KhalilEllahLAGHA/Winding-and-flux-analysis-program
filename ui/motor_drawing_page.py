"""Step 1: machine parameters page
(formerly ``Meshing_motor_drawing_page_UI.py``)."""

import logging

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QVBoxLayout, QWidget)

from ui.machine_drawer import MachineDrawer
from ui.theme import (MOTOR_INPUT_PAGE_STYLE, PAGE_SUBTITLE_STYLE,
                      PAGE_TITLE_STYLE)
from utils.constants import (DEFAULT_MACHINE_PARAMS, DEFAULT_PAIR_POLES,
                             SLOT_COUNT_RANGE, default_slot_arc_deg)
from utils.safe_eval import parse_float_field, parse_int_field

logger = logging.getLogger(__name__)

REDRAW_DEBOUNCE_MS = 300
# Tolerance when echoing slot-arc values between tabs (avoids signal loops
# caused by float round-tripping through the text field).
SLOT_ARC_SYNC_EPSILON = 0.01


class MotorDrawingPageUI:
    """Machine dimension inputs plus a live cross-section preview."""

    def __init__(self, main_window):
        self.main_window = main_window

    def create_motor_input_widget(self):
        widget = QWidget()
        widget.setStyleSheet(MOTOR_INPUT_PAGE_STYLE)

        # Keep this controller alive on the main window. PyQt5 only holds
        # weak references to bound-method slots, so without this the page
        # object is garbage collected and every textChanged->redraw
        # connection silently dies (the preview then never updates).
        self.main_window.motor_drawing_page_ui = self

        main_layout = QHBoxLayout(widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)
        main_layout.addLayout(self._build_input_panel(), 3)
        main_layout.addWidget(self._build_drawing_canvas(), 5)

        self._connect_inputs_to_redraw()
        self._link_with_winding_tab()
        self._link_with_mmf_tab()
        self.update_slot_angle_from_slots()
        self.draw_flux_machine()

        return widget

    # ------------------------------------------------------------- UI setup

    def _build_input_panel(self):
        window = self.main_window
        defaults = DEFAULT_MACHINE_PARAMS

        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(4, 4, 8, 4)
        left_panel.setSpacing(12)

        title = QLabel("Step 1: Machine Parameters")
        title.setStyleSheet(PAGE_TITLE_STYLE)
        left_panel.addWidget(title)

        subtitle = QLabel("Define the machine geometry — the cross-section "
                          "preview updates live as you type.")
        subtitle.setStyleSheet(PAGE_SUBTITLE_STYLE)
        subtitle.setWordWrap(True)
        left_panel.addWidget(subtitle)

        dimensions_group = QGroupBox("Machine Dimensions")
        dimensions_layout = QFormLayout(dimensions_group)
        dimensions_layout.setSpacing(10)
        dimensions_layout.setContentsMargins(12, 16, 12, 12)

        window.flux_stator_rout = QLineEdit(str(defaults['stator_outer_radius']))
        window.flux_stator_rin = QLineEdit(str(defaults['stator_inner_radius']))
        window.flux_air_gap_thickness = QLineEdit(str(defaults['air_gap']))
        window.flux_shaft_radius = QLineEdit(str(defaults['shaft_radius']))
        window.flux_slot_angle = QLineEdit()  # derived from the slot count
        window.flux_slot_height = QLineEdit(str(defaults['slot_height']))

        window.flux_stator_rout.setToolTip(
            "Outer radius of the stator lamination stack (mm).")
        window.flux_stator_rin.setToolTip(
            "Inner (bore) radius of the stator — must be smaller than the "
            "outer radius (mm).")
        window.flux_air_gap_thickness.setToolTip(
            "Radial air gap between stator bore and rotor surface (mm).")
        window.flux_shaft_radius.setToolTip("Radius of the rotor shaft (mm).")
        window.flux_slot_angle.setToolTip(
            "Slot opening angle (deg). Auto-derived as half the slot pitch "
            "when the slot count changes; you can still edit it.")
        window.flux_slot_height.setToolTip(
            "Radial depth of the stator slots (mm).")

        dimensions_layout.addRow("Stator Outer Radius (mm):", window.flux_stator_rout)
        dimensions_layout.addRow("Stator Inner Radius (mm):", window.flux_stator_rin)
        dimensions_layout.addRow("Air Gap Thickness (mm):", window.flux_air_gap_thickness)
        dimensions_layout.addRow("Shaft Radius (mm):", window.flux_shaft_radius)
        dimensions_layout.addRow("Slot Angle (deg):", window.flux_slot_angle)
        dimensions_layout.addRow("Slot Height (mm):", window.flux_slot_height)

        winding_group = QGroupBox("Winding Parameters")
        winding_layout = QFormLayout(winding_group)
        winding_layout.setSpacing(10)
        winding_layout.setContentsMargins(12, 16, 12, 12)

        window.flux_num_slots = QLineEdit(str(defaults['num_slots']))
        window.flux_num_pair_poles = QLineEdit(str(DEFAULT_PAIR_POLES))

        window.flux_num_slots.setToolTip(
            "Number of stator slots. Kept in sync with the Winding Simulator "
            "tab; changing it also recomputes the default slot angle.")
        window.flux_num_pair_poles.setToolTip(
            "Number of pole pairs. Kept in sync with the Winding Simulator tab.")

        winding_layout.addRow("Number of Slots:", window.flux_num_slots)
        winding_layout.addRow("Number of Pair of Poles:", window.flux_num_pair_poles)

        sync_note = QLabel("Slots, poles, and slot angle stay in sync with "
                           "the other tabs.")
        sync_note.setStyleSheet(PAGE_SUBTITLE_STYLE)
        sync_note.setWordWrap(True)

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setToolTip("Restore every machine parameter to its default value.")
        reset_btn.clicked.connect(self.reset_to_default)
        reset_btn.setMinimumWidth(140)
        reset_btn.setMinimumHeight(36)

        left_panel.addWidget(dimensions_group)
        left_panel.addWidget(winding_group)
        left_panel.addWidget(sync_note)
        left_panel.addWidget(reset_btn)
        left_panel.addStretch()

        return left_panel

    def _build_drawing_canvas(self):
        window = self.main_window

        window.flux_figure, window.flux_ax = plt.subplots(figsize=(8, 8))
        window.flux_figure.patch.set_facecolor('white')
        window.flux_ax.set_facecolor('white')

        window.flux_canvas = FigureCanvas(window.flux_figure)
        window.flux_machine_drawer = MachineDrawer(window.flux_figure,
                                                   window.flux_ax)
        return window.flux_canvas

    # ------------------------------------------------------------ wiring

    def _input_fields(self):
        window = self.main_window
        return [
            window.flux_stator_rout, window.flux_stator_rin,
            window.flux_num_slots, window.flux_slot_angle,
            window.flux_slot_height, window.flux_air_gap_thickness,
            window.flux_shaft_radius, window.flux_num_pair_poles,
        ]

    def _connect_inputs_to_redraw(self):
        """Redraw the machine (debounced) whenever an input changes."""
        for field in self._input_fields():
            field.textChanged.connect(self._on_input_changed)

        self.main_window.flux_num_slots.textChanged.connect(
            self.update_slot_angle_from_slots)

    def _on_input_changed(self):
        window = self.main_window
        if not hasattr(window, 'flux_redraw_timer'):
            window.flux_redraw_timer = QTimer()
            window.flux_redraw_timer.setSingleShot(True)
            window.flux_redraw_timer.timeout.connect(self.draw_flux_machine)

        window.flux_redraw_timer.stop()
        window.flux_redraw_timer.start(REDRAW_DEBOUNCE_MS)

    def _link_with_winding_tab(self):
        """Two-way sync of slot/pole counts with the winding tab."""
        window = self.main_window
        if not (hasattr(window, 'slots_spin') and hasattr(window, 'poles_spin')):
            return

        window.slots_spin.valueChanged.connect(
            lambda value: window.flux_num_slots.setText(str(value)))
        window.poles_spin.valueChanged.connect(
            lambda value: window.flux_num_pair_poles.setText(str(value)))

        window.flux_num_slots.textChanged.connect(self._update_winding_tab_slots)
        window.flux_num_pair_poles.textChanged.connect(
            self._update_winding_tab_pair_poles)

        window.flux_num_slots.setText(str(window.slots_spin.value()))
        window.flux_num_pair_poles.setText(str(window.poles_spin.value()))

    def _update_winding_tab_pair_poles(self, text):
        window = self.main_window
        try:
            value = int(text)
        except ValueError:
            return
        if value != window.poles_spin.value():
            window.poles_spin.setValue(value)

    def _update_winding_tab_slots(self, text):
        window = self.main_window
        try:
            value = int(text)
        except ValueError:
            return
        min_slots, max_slots = SLOT_COUNT_RANGE
        if min_slots <= value <= max_slots and value != window.slots_spin.value():
            window.slots_spin.setValue(value)

    def _link_with_mmf_tab(self):
        """Two-way sync of the slot opening angle with the MMF tab."""
        window = self.main_window
        connection_tab = getattr(window, 'connection_tab', None)
        if connection_tab is None or not hasattr(connection_tab, 'slot_arc_spin'):
            return

        connection_tab.slot_arc_spin.valueChanged.connect(
            lambda value: window.flux_slot_angle.setText(str(value)))
        window.flux_slot_angle.textChanged.connect(self._update_mmf_tab_slot_arc)

        window.flux_slot_angle.setText(str(connection_tab.slot_arc_spin.value()))

    def _update_mmf_tab_slot_arc(self, text):
        window = self.main_window
        try:
            value = float(text)
        except ValueError:
            return

        connection_tab = getattr(window, 'connection_tab', None)
        if connection_tab is None or not hasattr(connection_tab, 'slot_arc_spin'):
            return

        if abs(value - connection_tab.slot_arc_spin.value()) > SLOT_ARC_SYNC_EPSILON:
            connection_tab.slot_arc_spin.setValue(value)

    # --------------------------------------------------------------- actions

    def update_slot_angle_from_slots(self):
        """Default slot angle from the slot count (half the slot pitch)."""
        window = self.main_window
        num_slots = parse_int_field(window.flux_num_slots.text(), fallback=0)
        if num_slots <= 0:
            num_slots = DEFAULT_MACHINE_PARAMS['num_slots']
        window.flux_slot_angle.setText(f"{default_slot_arc_deg(num_slots):.2f}")

    def reset_to_default(self):
        window = self.main_window
        defaults = DEFAULT_MACHINE_PARAMS

        window.flux_stator_rout.setText(str(defaults['stator_outer_radius']))
        window.flux_stator_rin.setText(str(defaults['stator_inner_radius']))
        window.flux_air_gap_thickness.setText(str(defaults['air_gap']))
        window.flux_shaft_radius.setText(str(defaults['shaft_radius']))
        window.flux_slot_height.setText(str(defaults['slot_height']))
        window.flux_num_slots.setText(str(defaults['num_slots']))
        window.flux_num_pair_poles.setText(str(DEFAULT_PAIR_POLES))
        window.flux_slot_angle.setText(
            f"{default_slot_arc_deg(defaults['num_slots']):.2f}")

        self.draw_flux_machine()

    def draw_flux_machine(self):
        """Draw the machine preview from the current input values."""
        window = self.main_window
        try:
            params = {
                'stator_outer_radius': parse_float_field(window.flux_stator_rout.text()),
                'stator_inner_radius': parse_float_field(window.flux_stator_rin.text()),
                'air_gap_thickness': parse_float_field(window.flux_air_gap_thickness.text()),
                'shaft_radius': parse_float_field(window.flux_shaft_radius.text()),
                'num_slots': parse_int_field(window.flux_num_slots.text(),
                                             fallback=DEFAULT_MACHINE_PARAMS['num_slots']),
                'slot_angle': parse_float_field(window.flux_slot_angle.text()),
                'slot_height': parse_float_field(window.flux_slot_height.text()),
            }
            window.flux_machine_drawer.draw_machine(params)

        except Exception as error:
            logger.error("Error drawing flux machine: %s", error)
            window.flux_ax.clear()
            window.flux_ax.text(
                0, 0,
                f"Error drawing machine\nCheck parameter values\n{str(error)[:50]}...",
                ha='center', va='center', fontsize=12, color='red',
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#ffcccc", alpha=0.8))
            window.flux_ax.set_xlim(-100, 100)
            window.flux_ax.set_ylim(-100, 100)
            window.flux_canvas.draw()
