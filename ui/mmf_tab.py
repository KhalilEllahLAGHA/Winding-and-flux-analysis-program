"""MMF Curves tab: plot controls, connection
matrix dialog, data export, and the resultant-MMF animation window."""

import logging

import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                             QFrame, QGridLayout, QGroupBox,
                             QHBoxLayout, QHeaderView, QLabel, QPushButton,
                             QSpinBox, QStyleFactory, QScrollArea,
                             QTableWidget, QTableWidgetItem, QVBoxLayout,
                             QWidget)

from core.mmf_engine import MMFCalculationEngine
from utils.phases import phase_names, phase_color
from ui.theme import (DOUBLE_SPIN_BOX_STYLE, MATRIX_DIALOG_STYLE, SPIN_BOX_STYLE,
                      TEXT, badge_style)
from utils.constants import (ANIMATION_FRAME_INTERVAL_MS,
                             ANIMATION_SPEED_STEPS_DEG,
                             DEFAULT_ANIMATION_SPEED,
                             DEFAULT_NUM_SLOTS,
                             DEFAULT_PHASE_CURRENT_A, DEFAULT_TURNS,
                             DEFAULT_WT_ANGLE_DEG, PHASE_CURRENT_RANGE_A,
                             TURNS_RANGE, WT_ANGLE_RANGE_DEG,
                             default_slot_arc_deg, max_slot_arc_deg)

logger = logging.getLogger(__name__)

DEFAULT_PHASE_LINEWIDTH = 2

# Coalesce rapid control changes (spinbox auto-repeat, drags) into one redraw.
PLOT_DEBOUNCE_MS = 40


class SlotArcSpinBox(QDoubleSpinBox):
    """Keep fractional slot pitches precise without trailing display zeroes."""

    def textFromValue(self, value):
        return self.locale().toString(value, 'f', self.decimals()).rstrip('0').rstrip(
            self.locale().decimalPoint())


class ResultantAnimationWindow(QDialog):
    """Animates the resultant MMF profile as Wt sweeps 0-360°.

    Uses the engine's side-effect-free ``compute_resultant_profile`` so the
    configured Wt angle is never modified by the animation (the previous
    implementation permanently overwrote it).
    """

    def __init__(self, parent, mmf_engine):
        super().__init__(parent)
        self.mmf_engine = mmf_engine
        self.current_wt = 0.0
        self.current_speed = DEFAULT_ANIMATION_SPEED
        self.wt_step = ANIMATION_SPEED_STEPS_DEG[self.current_speed]
        self.is_paused = False

        self.setWindowTitle("Resultant MMF Animation - Wt Variable")
        self.setGeometry(80, 80, 1180, 720)

        self._init_ui()
        self.plot_resultant()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(ANIMATION_FRAME_INTERVAL_MS)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self.canvas = FigureCanvas(Figure(figsize=(16, 8)))
        self.ax = self.canvas.figure.add_subplot(111)
        layout.addWidget(self.canvas)

        # Static axis decoration set up once; each frame only updates the
        # line's data (set_data + draw_idle) instead of clearing and
        # rebuilding the whole axis at 20 fps.
        self.ax.set_xlabel('Mechanical Angle [degrees]')
        self.ax.set_ylabel('MMF [A·t]')
        self.ax.set_title('Variation of Resultant MMF with Time')
        self.ax.grid(True)
        self.ax.set_xlim(0, 360)
        (self._resultant_line,) = self.ax.plot([], [], color='red',
                                               linestyle='-', linewidth=3)

        controls_layout = QHBoxLayout()

        self.wt_label = QLabel(f"Current Wt: {self.current_wt:.1f}°")
        self.wt_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {TEXT};")
        controls_layout.addWidget(self.wt_label)
        controls_layout.addStretch()

        speed_group = QGroupBox("Animation Speed")
        speed_group.setStyleSheet(f"QGroupBox {{ color: {TEXT}; }}")
        speed_layout = QHBoxLayout(speed_group)
        speed_layout.setSpacing(5)

        self.speed_buttons = {}
        for speed_name in ANIMATION_SPEED_STEPS_DEG:
            button = QPushButton(speed_name)
            button.setCheckable(True)
            button.setMinimumWidth(60)
            button.clicked.connect(
                lambda checked, name=speed_name: self.set_speed(name))
            self.speed_buttons[speed_name] = button
            speed_layout.addWidget(button)
        self.speed_buttons[self.current_speed].setChecked(True)

        controls_layout.addWidget(speed_group)
        controls_layout.addStretch()

        self.pause_btn = QPushButton("Pause")
        self.pause_btn.clicked.connect(self.toggle_animation)
        self.pause_btn.setMinimumWidth(80)
        controls_layout.addWidget(self.pause_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self.reset_animation)
        reset_btn.setMinimumWidth(80)
        controls_layout.addWidget(reset_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_btn.setMinimumWidth(80)
        controls_layout.addWidget(close_btn)

        layout.addLayout(controls_layout)

    def set_speed(self, speed_name):
        self.current_speed = speed_name
        self.wt_step = ANIMATION_SPEED_STEPS_DEG[speed_name]
        for name, button in self.speed_buttons.items():
            button.setChecked(name == speed_name)

    def update_animation(self):
        if self.is_paused:
            return

        self.current_wt += self.wt_step
        if self.current_wt >= 360:
            self.current_wt = 0.0

        self.plot_resultant()
        self.wt_label.setText(f"Current Wt: {self.current_wt:.1f}°")

    def plot_resultant(self):
        profile = self.mmf_engine.compute_resultant_profile(self.current_wt)
        if profile is None:
            self._resultant_line.set_data([], [])
            self.canvas.draw_idle()
            return

        angles, values = profile
        self._resultant_line.set_data(angles, values)
        self.ax.relim()
        self.ax.autoscale_view(scalex=False)
        self.canvas.draw_idle()

    def toggle_animation(self):
        self.is_paused = not self.is_paused
        self.pause_btn.setText("Resume" if self.is_paused else "Pause")

    def reset_animation(self):
        self.current_wt = 0.0
        self.wt_label.setText(f"Current Wt: {self.current_wt:.1f}°")
        self.set_speed(DEFAULT_ANIMATION_SPEED)
        self.plot_resultant()

    def closeEvent(self, event):
        self.timer.stop()
        event.accept()


class ConnectionMatrixTab(QWidget):
    """MMF plot with phase selection, parameters, and matrix/export tools."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.matrix = None
        self.animation_window = None
        self.mmf_calculator = MMFCalculationEngine()
        self._plot_timer = None
        self._winding_error = None

        self.canvas = FigureCanvas(Figure(figsize=(10, 4)))
        self.fig = self.canvas.figure
        self.ax = self.fig.add_subplot(111)

        self._init_ui()

    def _schedule_plot(self):
        """Debounced replot: collapses bursts of control changes into one
        matplotlib redraw (the expensive part) instead of one per event."""
        if self._plot_timer is None:
            self._plot_timer = QTimer(self)
            self._plot_timer.setSingleShot(True)
            self._plot_timer.timeout.connect(self.update_plot)
        self._plot_timer.start(PLOT_DEBOUNCE_MS)

    # ------------------------------------------------------------- UI setup

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        plot_card = QFrame()
        plot_card.setObjectName('mmfPlotCard')
        plot_card.setStyleSheet(
            'QFrame#mmfPlotCard { background: white; border: 1px solid #dedede; border-radius: 8px; }')
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(6, 6, 6, 6)
        plot_layout.addWidget(self.canvas)
        layout.addWidget(plot_card, 1)
        layout.addWidget(self._build_control_panel())

    def _build_control_panel(self):
        """Two horizontal control rows below the full-width MMF plot."""
        control_panel = QWidget()
        control_panel.setObjectName('studySettings')
        panel_layout = QVBoxLayout(control_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(8)
        groups_layout = QHBoxLayout()
        groups_layout.setSpacing(12)
        groups_layout.addWidget(self._build_phase_group())
        groups_layout.addWidget(self._build_linewidth_group())
        groups_layout.addWidget(self._build_parameters_group())
        groups_layout.addWidget(self._build_slot_arc_group())
        panel_layout.addLayout(groups_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        self.phase_view_combo = QComboBox()
        self.phase_view_combo.addItems(['Instantaneous phases', 'Peak phase references'])
        self.phase_view_combo.setToolTip(
            'Instantaneous phase contributions use the configured Wt. '
            'Peak references show each phase at its positive peak current.')
        self.phase_view_combo.currentIndexChanged.connect(self._schedule_plot)
        buttons_layout.addWidget(self.phase_view_combo)
        buttons_layout.addStretch()

        reset_btn = QPushButton("Reset")
        reset_btn.setToolTip("Restore all plot controls to their defaults.")
        reset_btn.clicked.connect(self.reset_controls)
        reset_btn.setMinimumHeight(35)
        buttons_layout.addWidget(reset_btn)

        save_plot_btn = QPushButton("Save Plot")
        save_plot_btn.setToolTip("Save the current MMF plot as an image.")
        save_plot_btn.clicked.connect(self.save_plot)
        save_plot_btn.setMinimumHeight(35)
        buttons_layout.addWidget(save_plot_btn)

        export_tooth_btn = QPushButton("Export Data")
        export_tooth_btn.setToolTip(
            "Export per-tooth resultant MMF values to Excel.")
        export_tooth_btn.clicked.connect(self.export_tooth_data)
        export_tooth_btn.setMinimumHeight(35)
        buttons_layout.addWidget(export_tooth_btn)

        resultant_anim_btn = QPushButton("Animate MMF")
        resultant_anim_btn.setToolTip(
            "Animate the resultant MMF as Wt sweeps 0–360°.")
        resultant_anim_btn.clicked.connect(self.show_resultant_animation)
        resultant_anim_btn.setMinimumHeight(35)
        buttons_layout.addWidget(resultant_anim_btn)

        matrix_btn = QPushButton("Connection matrix")
        matrix_btn.setObjectName('primaryButton')
        matrix_btn.setToolTip("Show the phase/slot connection matrix.")
        matrix_btn.clicked.connect(self.show_matrix_window)
        matrix_btn.setMinimumHeight(35)
        buttons_layout.addWidget(matrix_btn)

        panel_layout.addLayout(buttons_layout)
        return control_panel

    def _build_phase_group(self):
        group = QGroupBox('Visible curves')
        layout = QVBoxLayout(group)
        panel = QWidget()
        self.phase_layout = QGridLayout(panel)
        self.phase_layout.setContentsMargins(0, 0, 0, 0)
        self.phase_layout.setSpacing(8)
        self.phase_checkboxes = {}
        self._set_phase_controls(phase_names(3))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(65)
        scroll.setMinimumWidth(180)
        scroll.setWidget(panel)
        layout.addWidget(scroll)
        self.resultant_checkbox = QCheckBox('Resultant')
        self.resultant_checkbox.stateChanged.connect(self._schedule_plot)
        layout.addWidget(self.resultant_checkbox)
        return group

    def _set_phase_controls(self, phases):
        if tuple(self.phase_checkboxes) == tuple(phases):
            return
        previous = {phase: checkbox.isChecked() for phase, checkbox in self.phase_checkboxes.items()}
        while self.phase_layout.count():
            item = self.phase_layout.takeAt(0)
            item.widget().hide()
            item.widget().deleteLater()
        self.phase_checkboxes = {}
        for index, phase in enumerate(phases):
            checkbox = QCheckBox(f'Phase {phase}')
            checkbox.setChecked(previous.get(phase, True))
            checkbox.stateChanged.connect(self._schedule_plot)
            self.phase_checkboxes[phase] = checkbox
            self.phase_layout.addWidget(checkbox, index//2, index%2)

    def _build_linewidth_group(self):
        linewidth_group = QGroupBox("Line width")
        linewidth_layout = QVBoxLayout(linewidth_group)
        linewidth_layout.setSpacing(10)

        self.phase_linewidth_spin = QSpinBox()
        self.phase_linewidth_spin.setRange(1, 10)
        self.phase_linewidth_spin.setValue(DEFAULT_PHASE_LINEWIDTH)
        self.phase_linewidth_spin.setSuffix(" px")
        self.phase_linewidth_spin.setStyleSheet(SPIN_BOX_STYLE)
        self.phase_linewidth_spin.valueChanged.connect(self._schedule_plot)

        linewidth_layout.addWidget(QLabel('Phase curves'))
        linewidth_layout.addWidget(self.phase_linewidth_spin)
        return linewidth_group

    def _build_parameters_group(self):
        params_group = QGroupBox("Excitation")
        params_layout = QGridLayout(params_group)
        params_layout.setSpacing(8)

        self.turns_spin = QSpinBox()
        self.turns_spin.setRange(*TURNS_RANGE)
        self.turns_spin.setValue(DEFAULT_TURNS)
        self.turns_spin.setStyleSheet(SPIN_BOX_STYLE)
        self.turns_spin.setToolTip(
            'Turns parameter multiplying each occupied coil-side current.')
        self.turns_spin.valueChanged.connect(self.update_turns)
        params_layout.addWidget(QLabel('Turns · N'), 0, 0)
        params_layout.addWidget(self.turns_spin, 1, 0)

        self.current_spin = QDoubleSpinBox()
        self.current_spin.setRange(*PHASE_CURRENT_RANGE_A)
        self.current_spin.setValue(DEFAULT_PHASE_CURRENT_A)
        self.current_spin.setDecimals(3)
        self.current_spin.setSuffix(" A")
        self.current_spin.setStyleSheet(DOUBLE_SPIN_BOX_STYLE)
        self.current_spin.setToolTip(
            'Peak current parameter. A double-layer winding uses I/2 in each layer.')
        self.current_spin.valueChanged.connect(self.update_current)
        params_layout.addWidget(QLabel('Peak current · I'), 0, 1)
        params_layout.addWidget(self.current_spin, 1, 1)

        self.wt_spin = QSpinBox()
        self.wt_spin.setRange(*WT_ANGLE_RANGE_DEG)
        self.wt_spin.setValue(DEFAULT_WT_ANGLE_DEG)
        self.wt_spin.setSuffix("°")
        self.wt_spin.setStyleSheet(SPIN_BOX_STYLE)
        self.wt_spin.setToolTip(
            'Electrical angle. Phase shifts use 360/m degrees for odd '
            'phase counts and 180/m degrees for even phase counts.')
        self.wt_spin.valueChanged.connect(self.update_wt_angle)
        params_layout.addWidget(QLabel('Angle · Wt'), 0, 2)
        params_layout.addWidget(self.wt_spin, 1, 2)

        return params_group

    def _build_slot_arc_group(self):
        slot_arc_group = QGroupBox("Slot opening")
        slot_arc_layout = QVBoxLayout(slot_arc_group)
        slot_arc_layout.setSpacing(10)

        self.slot_arc_spin = SlotArcSpinBox()
        self.slot_arc_spin.setDecimals(8)
        self.slot_arc_spin.setMinimum(0.5)
        self.slot_arc_spin.setSingleStep(0.5)
        self.slot_arc_spin.setValue(default_slot_arc_deg(DEFAULT_NUM_SLOTS))
        self.slot_arc_spin.setSuffix("°")
        self.slot_arc_spin.setStyleSheet(DOUBLE_SPIN_BOX_STYLE)
        self.slot_arc_spin.valueChanged.connect(self.update_slot_arc)

        slot_arc_layout.addWidget(QLabel('Arc angle'))
        slot_arc_layout.addWidget(self.slot_arc_spin)
        return slot_arc_group

    # ------------------------------------------------------ engine bindings

    def update_slot_arc(self):
        self.mmf_calculator.update_slot_arc(self.slot_arc_spin.value())
        self._schedule_plot()

    def update_turns(self):
        self.mmf_calculator.update_turns(self.turns_spin.value())
        self._schedule_plot()

    def update_current(self):
        self.mmf_calculator.update_current(self.current_spin.value())
        self._schedule_plot()

    def update_wt_angle(self):
        self.mmf_calculator.update_wt_angle(self.wt_spin.value())
        self._schedule_plot()

    def update_matrix(self, winding_pattern, is_double_layer, poles, coil_span=None, phase_count=3):
        """Rebuild the connection matrix from main-tab winding parameters."""
        self._set_phase_controls(phase_names(phase_count))
        try:
            self.matrix = self.mmf_calculator.update_matrix_from_parameters(
                winding_pattern, is_double_layer, poles, coil_span=coil_span, phase_count=phase_count)
        except ValueError as error:
            self.invalidate_winding(str(error))
            return

        if self.matrix is not None:
            self._winding_error = None
            n_slots = self.matrix.shape[1]
            max_arc = max_slot_arc_deg(n_slots)
            self.slot_arc_spin.setMaximum(max_arc)

            # Push the current UI values into the engine.
            self.mmf_calculator.update_slot_arc(self.slot_arc_spin.value())
            self.mmf_calculator.update_turns(self.turns_spin.value())
            self.mmf_calculator.update_current(self.current_spin.value())
            self.mmf_calculator.update_wt_angle(self.wt_spin.value())

        self.update_plot()

    def invalidate_winding(self, message):
        self.matrix = None
        self.mmf_calculator.matrix = None
        self.mmf_calculator.profiles.clear()
        self.mmf_calculator._tooth_mmf_base = None
        self._winding_error = message
        if self.main_window is not None:
            self.main_window.feasibility_label.setText(f'INVALID WINDING\n{message}')
            self.main_window.feasibility_label.setStyleSheet(badge_style('error'))
        self.update_plot()

    # ---------------------------------------------------------------- plots

    def update_plot(self):
        self.ax.clear()

        if self.matrix is not None:
            selected_phases = [phase for phase, checkbox
                               in self.phase_checkboxes.items()
                               if checkbox.isChecked()]
            self._plot_selected_phases(selected_phases)
        elif self._winding_error:
            self.ax.text(0.5, 0.5, self._winding_error, transform=self.ax.transAxes,
                         ha='center', va='center', wrap=True)

        self.ax.set_xlabel('Mechanical Angle [degrees]')
        self.ax.set_ylabel('MMF [A·t]')
        instantaneous = self.phase_view_combo.currentIndex() == 0
        title = (f'Instantaneous MMF at Wt = {self.wt_spin.value()}°'
                 if instantaneous else 'Peak-current phase MMF references')
        self.ax.set_title(title)
        self.ax.grid(True)
        self.ax.set_xlim(0, 360)

        if self.ax.get_lines():
            self.ax.legend(ncol=max(1, (len(self.ax.get_lines())+7)//8), fontsize=9)

        self.canvas.draw()

    def _is_double_layer(self):
        return self.matrix is not None and self.mmf_calculator.is_double_layer

    def _plot_selected_phases(self, selected_phases):
        linewidth = self.phase_linewidth_spin.value()
        layer_type = 'sum' if self._is_double_layer() else None
        wt = self.wt_spin.value()
        instantaneous = self.phase_view_combo.currentIndex() == 0

        for phase in selected_phases:
            angles, values = self.mmf_calculator.get_profile_data(
                phase, layer_type, wt_deg=wt if instantaneous else None)
            if angles is not None:
                color, linestyle = phase_color(phase), '-'
                label = f'Phase {phase}' if instantaneous else f'Phase {phase} (peak)'
                self.ax.plot(angles, values, label=label,
                             color=color, linestyle=linestyle, linewidth=linewidth)

        if self.resultant_checkbox.isChecked():
            angles, values = self.mmf_calculator.get_profile_data('resultant')
            if angles is not None:
                wt = self.wt_spin.value()
                label = f'Resultant at Wt = {wt}°'
                self.ax.plot(angles, values, label=label, color='black',
                             linestyle='-', linewidth=linewidth + 1)

    # ------------------------------------------------------- dialog windows

    def show_matrix_window(self):
        """Show the connection matrix in a table dialog."""
        if self.matrix is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Connection Matrix")
        dialog.setStyle(QStyleFactory.create("Fusion"))
        dialog.setStyleSheet(MATRIX_DIALOG_STYLE)

        layout = QVBoxLayout(dialog)
        table = QTableWidget()
        rows, cols = self.matrix.shape

        phases = self.mmf_calculator.phases
        row_labels = ([f'{phase}_top' for phase in phases] + [f'{phase}_bot' for phase in phases]
                      if self._is_double_layer() else list(phases))

        table.setRowCount(rows)
        table.setColumnCount(cols)
        table.setVerticalHeaderLabels(row_labels)
        table.setHorizontalHeaderLabels([str(i + 1) for i in range(cols)])

        table.setShowGrid(True)
        table.setWordWrap(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        table.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        header_font = table.horizontalHeader().font()
        header_font.setPointSize(12)
        table.horizontalHeader().setFont(header_font)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)

        table.horizontalHeader().setFixedHeight(50)
        table.verticalHeader().setFixedWidth(70)
        table.verticalHeader().setDefaultSectionSize(43)
        table.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        table.verticalHeader().setStretchLastSection(False)

        table.setFrameShape(QFrame.Shape.NoFrame)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        for row in range(rows):
            for col in range(cols):
                table.setItem(row, col,
                              QTableWidgetItem(str(self.matrix[row][col])))

        save_btn = QPushButton("Save as Excel")
        save_btn.clicked.connect(lambda: self._save_matrix_to_excel(self.matrix))

        layout.addWidget(table)
        layout.addWidget(save_btn)
        dialog.resize(1920, min(800, 150+rows*43))
        dialog.exec()

    def _save_matrix_to_excel(self, matrix):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Matrix", "connection_matrix.xlsx", "Excel Files (*.xlsx)")
        if filename:
            pd.DataFrame(matrix).to_excel(filename, index=False, header=False)
            logger.info("Matrix saved to %s", filename)

    def show_resultant_animation(self):
        if self.matrix is None:
            logger.warning("No matrix available for animation")
            return
        self.animation_window = ResultantAnimationWindow(self, self.mmf_calculator)
        self.animation_window.show()

    # --------------------------------------------------------------- actions

    def reset_controls(self):
        """Reset all controls to their default configuration."""
        for checkbox in self.phase_checkboxes.values():
            checkbox.setChecked(True)
        self.resultant_checkbox.setChecked(False)
        self.phase_view_combo.setCurrentIndex(0)
        self.phase_linewidth_spin.setValue(DEFAULT_PHASE_LINEWIDTH)

        n_slots = (self.matrix.shape[1] if self.matrix is not None
                   else DEFAULT_NUM_SLOTS)
        self.slot_arc_spin.setValue(min(default_slot_arc_deg(n_slots),
                                        self.slot_arc_spin.maximum()))

        self.turns_spin.setValue(DEFAULT_TURNS)
        self.current_spin.setValue(DEFAULT_PHASE_CURRENT_A)
        self.wt_spin.setValue(DEFAULT_WT_ANGLE_DEG)

        self.update_plot()

    def _poles_value(self):
        poles_spin = getattr(self.main_window, 'poles_spin', None)
        return poles_spin.value() if poles_spin else 0

    def save_plot(self):
        """Save the current plot with an auto-generated filename."""
        try:
            n_slots = self.matrix.shape[1] if self.matrix is not None else 0

            selected = sorted(phase for phase, checkbox
                              in self.phase_checkboxes.items()
                              if checkbox.isChecked())
            phases_str = "".join(selected) if selected else "no_phases"
            if self.resultant_checkbox.isChecked():
                phases_str += "_resultant"

            layer_str = ("double_layer_sum" if self._is_double_layer()
                         else "single_layer")
            view_str = (f'instantaneous_Wt{self.wt_spin.value()}'
                        if self.phase_view_combo.currentIndex() == 0 else 'peak_reference')
            filename = (f"{n_slots}slots_{self._poles_value()}poles_"
                        f"{phases_str}_{layer_str}_{view_str}.png")

            save_path, _ = QFileDialog.getSaveFileName(
                self, "Save Plot", filename,
                "PNG Files (*.png);;PDF Files (*.pdf);;SVG Files (*.svg);;"
                "All Files (*)")

            if save_path:
                self.fig.savefig(save_path, dpi=300, bbox_inches='tight',
                                 facecolor='white', edgecolor='none')
                logger.info("Plot saved to %s", save_path)

        except Exception as error:
            logger.error("Error saving plot: %s", error)

    def export_tooth_data(self):
        """Export resultant tooth MMF values at the configured Wt to Excel."""
        try:
            wt_deg = self.wt_spin.value()
            tooth_data = self.mmf_calculator.get_tooth_mmf_data(wt_deg=wt_deg)
            if tooth_data is None:
                logger.warning("No tooth data available for export")
                return

            n_slots = self.matrix.shape[1] if self.matrix is not None else 0
            layer_str = "double_layer" if self._is_double_layer() else "single_layer"
            filename = (f"{self.mmf_calculator.phase_count}phases_{n_slots}slots_{self._poles_value()}poles_"
                        f"resultant_tooth_mmf_Wt{wt_deg}deg_{layer_str}.xlsx")

            save_path, _ = QFileDialog.getSaveFileName(
                self, "Export Tooth Data", filename,
                "Excel Files (*.xlsx);;All Files (*)")

            if save_path:
                pd.DataFrame({
                    'Tooth_Number': list(range(1, n_slots + 1)),
                    'Resultant_Tooth_MMF': tooth_data['Resultant']['tooth_mmf'],
                    'Wt_Angle_Degrees': [wt_deg] * n_slots,
                }).to_excel(save_path, index=False)
                logger.info("Tooth data exported to %s (Wt = %s°)",
                            save_path, wt_deg)

        except Exception as error:
            logger.error("Error exporting tooth data: %s", error)


def setup_connection_matrix_tab(main_window):
    """Create the MMF tab and keep it in sync with the winding tab."""
    main_window.connection_tab = ConnectionMatrixTab(main_window)
    layout = QVBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(main_window.connection_tab)
    main_window.tab_connection.setLayout(layout)

    def sync_with_winding_tab():
        actual_poles = main_window.poles_spin.value()
        main_window.connection_tab.update_matrix(
            main_window.stator_drawing.winding_pattern,
            main_window.stator_drawing.is_double_layer,
            actual_poles, coil_span=main_window.span_spin.value(), phase_count=main_window.phases_spin.value())

    sync_with_winding_tab()

