"""Winding Simulator tab (formerly ``Winding_tab.py``).

The controller builds the tab inside ``main_window.tab_main`` and keeps the
interactive widgets as attributes of the main window because the other tabs
(MMF curves, flux viewer) read them for cross-tab synchronisation.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QFileDialog, QFormLayout, QFrame, QGroupBox,
                             QHBoxLayout, QLabel, QPushButton, QRadioButton,
                             QButtonGroup, QScrollArea, QSizePolicy, QSpinBox,
                             QSplitter, QVBoxLayout, QWidget)

from core.winding_analysis import (check_winding_feasibility,
                                   generate_winding_explanation)
from ui.stator_drawing import StatorDrawing
from ui.theme import (PAGE_SUBTITLE_STYLE, PAGE_TITLE_STYLE, SPIN_BOX_STYLE,
                      badge_style)
from utils.constants import DEFAULT_NUM_SLOTS, DEFAULT_PAIR_POLES, SLOT_COUNT_RANGE

CONTROL_PANEL_MIN_WIDTH_PX = 285
EXPLANATION_PANEL_MIN_WIDTH_PX = 360
LEFT_PANEL_MIN_WIDTH_PX = 660
DRAWING_MIN_SIZE_PX = (520, 520)


class WindingTabController:
    """Builds and drives the winding simulator tab."""

    def __init__(self, main_window):
        self.window = main_window
        self._build_ui()
        self.update_winding()

    # ------------------------------------------------------------- UI setup

    def _build_ui(self):
        window = self.window

        main_splitter = QSplitter(Qt.Horizontal)
        main_layout = QHBoxLayout(window.tab_main)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.addWidget(main_splitter)

        left_widget = QWidget()
        left_layout = QHBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)
        left_layout.addWidget(self._build_control_panel())
        left_layout.addWidget(self._build_explanation_panel())

        right_widget = self._build_drawing_panel()

        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setCollapsible(0, False)
        main_splitter.setCollapsible(1, False)
        left_widget.setMinimumWidth(LEFT_PANEL_MIN_WIDTH_PX)
        # Let the drawing take the remaining space on any screen size.
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setHandleWidth(2)

    def _build_control_panel(self):
        window = self.window

        control_widget = QWidget()
        control_widget.setMinimumWidth(CONTROL_PANEL_MIN_WIDTH_PX)
        control_layout = QVBoxLayout(control_widget)
        control_layout.setSpacing(12)

        title = QLabel("Winding Simulator")
        title.setStyleSheet(PAGE_TITLE_STYLE)
        control_layout.addWidget(title)

        subtitle = QLabel("Results and the drawing update instantly.")
        subtitle.setStyleSheet(PAGE_SUBTITLE_STYLE)
        subtitle.setWordWrap(True)
        control_layout.addWidget(subtitle)

        min_slots, max_slots = SLOT_COUNT_RANGE

        window.slots_spin = QSpinBox()
        window.slots_spin.setRange(min_slots, max_slots)
        window.slots_spin.setValue(DEFAULT_NUM_SLOTS)
        window.slots_spin.setStyleSheet(SPIN_BOX_STYLE)
        window.slots_spin.valueChanged.connect(self.update_winding)
        window.slots_spin.valueChanged.connect(
            lambda: window.span_spin.setMaximum(window.slots_spin.value()))
        window.slots_spin.valueChanged.connect(
            lambda: window.poles_spin.setMaximum(window.slots_spin.value() // 3))
        window.slots_spin.valueChanged.connect(self.update_span_for_double_layer)

        window.poles_spin = QSpinBox()
        window.poles_spin.setRange(1, window.slots_spin.value() // 6)
        window.poles_spin.setSingleStep(1)
        window.poles_spin.setValue(DEFAULT_PAIR_POLES)
        window.poles_spin.setStyleSheet(SPIN_BOX_STYLE)
        window.poles_spin.valueChanged.connect(self.update_winding)
        window.poles_spin.valueChanged.connect(self.update_span_for_double_layer)

        window.span_spin = QSpinBox()
        window.span_spin.setRange(1, window.slots_spin.value())
        window.span_spin.setValue(
            window.slots_spin.value() // window.poles_spin.value())
        window.span_spin.setStyleSheet(SPIN_BOX_STYLE)
        window.span_spin.valueChanged.connect(self.update_winding)

        window.single_layer = QRadioButton("Single Layer")
        window.double_layer = QRadioButton("Double Layer")
        window.double_layer.setChecked(True)
        window.single_layer.toggled.connect(self.update_winding)
        window.single_layer.toggled.connect(self.handle_single_layer_toggle)

        self._winding_group = QButtonGroup()
        self._winding_group.addButton(window.single_layer)
        self._winding_group.addButton(window.double_layer)

        window.slots_spin.setToolTip("Total number of stator slots.")
        window.poles_spin.setToolTip("Number of pole pairs (poles = pairs × 2).")
        window.span_spin.setToolTip(
            "Coil span in slots. Snaps to the pole pitch in double-layer mode.")

        config_group = QGroupBox("Winding Configuration")
        config_form = QFormLayout(config_group)
        config_form.setSpacing(10)
        config_form.setContentsMargins(12, 16, 12, 12)

        config_form.addRow("Number of Slots:", window.slots_spin)
        config_form.addRow("Pair of Poles:", window.poles_spin)
        config_form.addRow("Coil Span (slots):", window.span_spin)

        layer_row = QVBoxLayout()
        layer_row.setSpacing(4)
        layer_row.addWidget(window.single_layer)
        layer_row.addWidget(window.double_layer)
        config_form.addRow("Winding Type:", layer_row)

        control_layout.addWidget(config_group)

        results_group = QGroupBox("Computed Properties")
        results_form = QFormLayout(results_group)
        results_form.setSpacing(10)
        results_form.setContentsMargins(12, 16, 12, 12)

        window.slots_per_pole_label = QLabel("–")
        window.slots_per_phase_label = QLabel("–")
        window.winding_type_label = QLabel("–")

        results_form.addRow("Slots per pole:", window.slots_per_pole_label)
        results_form.addRow("Slots / pole / phase (q):",
                            window.slots_per_phase_label)
        results_form.addRow("Winding type:", window.winding_type_label)

        window.feasibility_label = QLabel("–")
        window.feasibility_label.setWordWrap(True)
        window.feasibility_label.setStyleSheet(badge_style('muted'))
        window.feasibility_label.setSizePolicy(QSizePolicy.Expanding,
                                               QSizePolicy.Minimum)
        results_form.addRow(window.feasibility_label)

        control_layout.addWidget(results_group)
        control_layout.addStretch()

        return control_widget

    def _build_explanation_panel(self):
        window = self.window

        container = QGroupBox("Winding Explanation")
        container.setMinimumWidth(EXPLANATION_PANEL_MIN_WIDTH_PX)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 14, 8, 8)

        window.explanation_text = QLabel()
        window.explanation_text.setWordWrap(True)
        window.explanation_text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        window.explanation_text.setStyleSheet(
            "background: transparent; padding: 6px;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(window.explanation_text)
        layout.addWidget(scroll)

        return container

    def _build_drawing_panel(self):
        window = self.window

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)

        drawing_container = QFrame()
        drawing_container.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #2a313c;"
            "border-radius: 8px; }")
        drawing_layout = QVBoxLayout(drawing_container)
        drawing_layout.setContentsMargins(10, 10, 10, 10)

        window.stator_drawing = StatorDrawing()
        window.stator_drawing.setMinimumSize(*DRAWING_MIN_SIZE_PX)
        window.stator_drawing.setSizePolicy(QSizePolicy.Expanding,
                                            QSizePolicy.Expanding)
        drawing_layout.addWidget(window.stator_drawing, 1)

        save_image_btn = QPushButton("Save Drawing")
        save_image_btn.setToolTip("Export the stator drawing as a PNG image.")
        save_image_btn.clicked.connect(self.save_stator_image)
        drawing_layout.addWidget(save_image_btn, alignment=Qt.AlignRight)

        right_layout.addWidget(drawing_container)
        return right_widget

    # --------------------------------------------------------------- actions

    def actual_poles(self):
        """Actual pole count (UI works in pole pairs)."""
        return self.window.poles_spin.value() * 2

    def update_winding(self):
        """Recompute feasibility, report, drawing, and dependent tabs."""
        window = self.window
        slots = window.slots_spin.value()
        poles = self.actual_poles()
        is_double_layer = window.double_layer.isChecked()
        coil_span = (slots // poles if window.single_layer.isChecked()
                     else window.span_spin.value())

        feasible, messages, q = check_winding_feasibility(slots, poles)

        window.slots_per_pole_label.setText(f"{slots / poles:.2f}")
        window.slots_per_phase_label.setText(str(q))
        window.winding_type_label.setText(
            "Fractional slot winding" if q.denominator > 1
            else "Integer slot winding")

        if feasible:
            window.feasibility_label.setText("✓ FEASIBLE")
            window.feasibility_label.setStyleSheet(badge_style('success'))
        else:
            window.feasibility_label.setText(
                "✗ NOT FEASIBLE\n" + "\n".join(messages))
            window.feasibility_label.setStyleSheet(badge_style('error'))

        window.explanation_text.setText(generate_winding_explanation(
            slots, poles, coil_span, is_double_layer, q))
        window.stator_drawing.update_parameters(slots, poles, coil_span,
                                                is_double_layer)

        # Keep the MMF tab in sync with the new winding pattern.
        if hasattr(window, 'connection_tab'):
            window.connection_tab.update_matrix(
                window.stator_drawing.winding_pattern,
                window.stator_drawing.is_double_layer,
                poles)

    def update_span_for_double_layer(self):
        """Snap the coil span to the pole pitch while in double layer mode."""
        window = self.window
        if window.double_layer.isChecked():
            pole_pitch = window.slots_spin.value() // self.actual_poles()
            window.span_spin.setValue(pole_pitch)

    def handle_single_layer_toggle(self):
        window = self.window
        is_single = window.single_layer.isChecked()
        window.span_spin.setEnabled(not is_single)
        if is_single:
            window.span_spin.clear()
        else:
            pole_pitch = window.slots_spin.value() // self.actual_poles()
            window.span_spin.setValue(pole_pitch)
            window.span_spin.clear()

    def save_stator_image(self):
        """Save the stator drawing with a configuration-derived filename."""
        window = self.window
        slots = window.slots_spin.value()
        pair_of_poles = window.poles_spin.value()
        phases = 3
        is_single = window.single_layer.isChecked()
        winding_type = "SingleL" if is_single else "DoubleL"

        _, _, q = check_winding_feasibility(slots, self.actual_poles())
        q_type = "qfrac" if q.denominator > 1 else "qint"

        if is_single:
            default_filename = (f"{slots}slots_{pair_of_poles}pairpoles_"
                                f"{phases}phases_{winding_type}_{q_type}.png")
        else:
            coil_span = window.span_spin.value()
            default_filename = (f"{slots}slots_{pair_of_poles}pairpoles_"
                                f"{phases}phases_{winding_type}_span{coil_span}_"
                                f"{q_type}.png")

        filename, _ = QFileDialog.getSaveFileName(
            window, "Save Drawing", default_filename, "PNG Files (*.png)")
        if filename:
            window.stator_drawing.save_drawing(filename)
