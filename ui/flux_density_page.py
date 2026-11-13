"""Step 3: flux density heatmap page.

Runs the reluctance -> teeth MMF -> flux solve pipeline, renders the
selected visualisation, plays Wt-sweep animations, and compares results
against a FEMM validation run.
"""

import csv
from copy import deepcopy
import time
import json
import logging
from datetime import datetime
from uuid import uuid4

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from PyQt6.QtCore import QProcess, QSize, QTimer, Qt
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QTabWidget, QVBoxLayout,
                             QWidget)

from core.flux_solver import FluxCalculator
from core.femm_runner import parse_validation_results
from core.femm_validation import (airgap_profile, airgap_samples,
                                  build_validation_script, compare_airgap_profiles,
                                  compute_reference_metrics)
from core.reluctance_calculator import ReluctanceCalculator
from core.teeth_slot_mmf import TeethSlotMMFCalculator
from ui.flux_visualization import (DEFAULT_CONTOUR_COUNT, generate_flux_density_heatmap,
                                   generate_flux_line_density_visualisation,
                                   generate_flux_lines_visualisation)
from ui.theme import (FLUX_DENSITY_PAGE_STYLE, PAGE_SUBTITLE_STYLE,
                      PAGE_TITLE_STYLE, set_status)
from utils.constants import (DEFAULT_AXIAL_LENGTH_MM,
                             DEFAULT_RELATIVE_PERMEABILITIES)
from utils.paths import FEMM_VALIDATION_DIR, PROJECT_ROOT, femm_worker_command

try:
    import pyqtgraph as pg
    from ui.field_animation import AnimationPreparation, FieldAnimationView
    pg.setConfigOptions(imageAxisOrder='row-major')
    PYQTGRAPH_AVAILABLE = True
except Exception:
    pg = None
    PYQTGRAPH_AVAILABLE = False

logger = logging.getLogger(__name__)

SOLVER_OPTIONS = {'method': 'auto', 'tolerance': 1e-6}
SOLVER_LABEL = "Automatic"
EXCITED_EPSILON = 1e-12

VISUALISATION_MODES = ("B Heatmap", "Flux Lines", "Flux Line + Density")
ANALYSIS_REGIONS = ("Air Gap", "Rotor Core", "Tooth", "Stator Core", "Slot")

FEMM_RUN_TIMEOUT_S = 300


class FluxDensityHeatmapUI:
    """Controls, statistics, animation, and FEMM validation for Step 3."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.reluctance_calculator = ReluctanceCalculator()
        self.mmf_calculator = TeethSlotMMFCalculator()
        self.flux_calculator = FluxCalculator()
        self.reluctance_results = None
        self._reluctance_cache = None
        self.mmf_results = None
        self.flux_results = None
        self.femm_process = None
        self._femm_run = None

        self.animation_frames = []
        self.animation_frame_index = 0
        self.animation_span_degrees = 360.0
        self.animation_mode = VISUALISATION_MODES[0]
        self.pyqtgraph_available = PYQTGRAPH_AVAILABLE
        self.animation_model = None
        self._animation_worker = None
        self._cached_animation_signature = None
        self._animation_angle = 0.0

        self.animation_timer = QTimer(main_window)
        self.animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.animation_timer.timeout.connect(self._advance_animation_frame)

    def _set_status(self, text, kind='info'):
        """Color-coded feedback on the status line below the controls."""
        set_status(self.main_window.flux_status_label, text, kind)

    # ------------------------------------------------------------- UI setup

    def create_flux_density_heatmap_widget(self):
        widget = QWidget()
        widget.setStyleSheet(FLUX_DENSITY_PAGE_STYLE)

        main_layout = QHBoxLayout(widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(14)
        inspector = QWidget()
        inspector.setLayout(self._build_left_panel())
        scroll = QScrollArea()
        scroll.setObjectName('studySettings')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setFixedWidth(310)
        scroll.setWidget(inspector)
        main_layout.addWidget(scroll)
        main_layout.addWidget(self._build_right_panel(widget), 1)

        self.main_window.flux_density_page_ui = self
        self._connect_animation_inputs()
        return widget

    def _build_left_panel(self):
        window = self.main_window
        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(4, 4, 8, 4)
        left_panel.setSpacing(12)

        title = QLabel("Analysis settings")
        title.setStyleSheet(PAGE_TITLE_STYLE)
        left_panel.addWidget(title)

        subtitle = QLabel("Solve the field, inspect its values and compare with FEMM.")
        subtitle.setStyleSheet(PAGE_SUBTITLE_STYLE)
        subtitle.setWordWrap(True)
        left_panel.addWidget(subtitle)

        window.flux_tabs = QTabWidget()
        window.flux_tabs.addTab(self._create_material_properties_tab(),
                                "Materials")
        window.flux_tabs.addTab(self._create_analysis_statistics_tab(),
                                "Statistics")
        window.flux_tabs.addTab(self._create_animation_tab(), "Animation")
        window.flux_tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

        controls_group = QGroupBox("Solve and validate")
        controls_layout = QVBoxLayout(controls_group)

        window.flux_calculate_btn = QPushButton("Solve field")
        window.flux_calculate_btn.setObjectName("primaryButton")
        window.flux_calculate_btn.setMinimumHeight(36)
        window.flux_calculate_btn.setToolTip(
            "Run the reluctance → teeth MMF → flux solve pipeline on the "
            "generated mesh.")
        window.flux_calculate_btn.clicked.connect(self.flux_calculate)
        controls_layout.addWidget(window.flux_calculate_btn)

        secondary_actions = QHBoxLayout()
        window.flux_export_all_btn = QPushButton("Export results")
        window.flux_export_all_btn.setMinimumHeight(35)
        window.flux_export_all_btn.clicked.connect(self.export_all_results)
        window.flux_export_all_btn.setEnabled(False)
        secondary_actions.addWidget(window.flux_export_all_btn)

        window.flux_visualization_type = QComboBox()
        window.flux_visualization_type.addItems(VISUALISATION_MODES)
        window.flux_visualization_type.setCurrentIndex(2)
        window.flux_visualization_type.currentIndexChanged.connect(self._schedule_field_redraw)

        window.flux_generate_visualisation_btn = QPushButton(
            "Refresh view")
        window.flux_generate_visualisation_btn.setMinimumHeight(35)
        window.flux_generate_visualisation_btn.clicked.connect(
            self.generate_visualisation)
        window.flux_generate_visualisation_btn.setEnabled(False)

        window.flux_femm_validation_btn = QPushButton("Validate in FEMM")
        window.flux_femm_validation_btn.setMinimumHeight(35)
        window.flux_femm_validation_btn.setToolTip(
            "Recalculate this model and compare its air-gap B and radial "
            "sector flux against an independent FEMM solve. Keep FEMM open "
            "with the flux-density map, field lines and values.")
        window.flux_femm_validation_btn.clicked.connect(self.run_femm_validation)
        secondary_actions.addWidget(window.flux_femm_validation_btn)
        controls_layout.addLayout(secondary_actions)

        left_panel.addWidget(controls_group)

        window.flux_progress_bar = QProgressBar()
        window.flux_progress_bar.setVisible(False)
        left_panel.addWidget(window.flux_progress_bar)

        window.flux_status_label = QLabel("")
        window.flux_status_label.setWordWrap(True)
        set_status(window.flux_status_label, "", 'muted')
        left_panel.addWidget(window.flux_status_label)
        window.flux_contour_label = QLabel("")
        window.flux_contour_label.setWordWrap(True)
        window.flux_contour_label.setStyleSheet(PAGE_SUBTITLE_STYLE)
        left_panel.addWidget(window.flux_contour_label)
        left_panel.addWidget(window.flux_tabs, 1)
        return left_panel

    def _build_right_panel(self, parent_widget):
        window = self.main_window

        self._setup_flux_density_visualization()

        right_panel = QVBoxLayout()
        right_panel.setContentsMargins(12, 12, 12, 10)
        right_panel.setSpacing(8)
        display_controls = QHBoxLayout()
        display_controls.addWidget(QLabel("Display"))
        display_controls.addWidget(window.flux_visualization_type)
        display_controls.addStretch()
        display_controls.addWidget(QLabel("Contours"))
        window.flux_contour_count = QSpinBox()
        window.flux_contour_count.setRange(4, 100)
        window.flux_contour_count.setValue(DEFAULT_CONTOUR_COUNT)
        window.flux_contour_count.setToolTip(
            'Equally spaced magnetic vector-potential contours. '
            'Each interval represents the same magnetic flux.')
        window.flux_contour_count.setFixedWidth(88)
        window.flux_contour_count.valueChanged.connect(self._schedule_field_redraw)
        display_controls.addWidget(window.flux_contour_count)
        display_controls.addWidget(window.flux_generate_visualisation_btn)
        right_panel.addLayout(display_controls)
        window.flux_density_toolbar = NavigationToolbar(
            window.flux_density_canvas, parent_widget)
        window.flux_density_toolbar.setIconSize(QSize(18, 18))
        window.flux_density_toolbar.setFixedHeight(34)
        right_panel.addWidget(window.flux_density_toolbar)

        window.flux_display_stack = QStackedWidget()
        window.flux_display_stack.addWidget(window.flux_density_canvas)
        if self.pyqtgraph_available and hasattr(window, 'flux_anim_pg_widget'):
            window.flux_display_stack.addWidget(window.flux_anim_pg_widget)
        right_panel.addWidget(window.flux_display_stack)

        window.flux_probe_label = QLabel("Click the field to inspect flux density.")
        window.flux_probe_label.setWordWrap(True)
        window.flux_probe_label.setStyleSheet(PAGE_SUBTITLE_STYLE)
        right_panel.addWidget(window.flux_probe_label)
        window.flux_density_canvas.mpl_connect('button_press_event', self._inspect_field_point)

        right_widget = QWidget()
        right_widget.setObjectName('fieldViewCard')
        right_widget.setStyleSheet(
            'QWidget#fieldViewCard { background: #1e1e1e; border: 1px solid #353535; border-radius: 10px; }')
        right_widget.setLayout(right_panel)
        return right_widget

    def _schedule_field_redraw(self):
        if not hasattr(self, '_field_redraw_timer'):
            self._field_redraw_timer = QTimer(self.main_window)
            self._field_redraw_timer.setSingleShot(True)
            self._field_redraw_timer.timeout.connect(self.generate_visualisation)
        if self.flux_results:
            self._field_redraw_timer.start(120)

    def _inspect_field_point(self, event):
        window = self.main_window
        if (event.inaxes is not window.flux_density_ax or event.button != 1
                or event.xdata is None or event.ydata is None
                or window.flux_density_toolbar.mode or not self.flux_results):
            return
        radius = float(np.hypot(event.xdata, event.ydata))
        angle = float(np.degrees(np.arctan2(event.ydata, event.xdata)) % 360)
        mesh = self._mesh_data()
        if not mesh:
            return
        for element in mesh['mesh_elements']:
            if (element['rin'] <= radius <= element['rout']
                    and element['theta_start'] <= angle < element['theta_end']):
                eid = element.get('element_id', element.get('id'))
                values = self.flux_results['flux_densities'].get(eid)
                if values is None:
                    values = self.flux_results['flux_densities'].get(str(eid))
                if values is None:
                    return
                window.flux_probe_label.setText(
                    f"r {radius:.2f} mm  ·  θ {angle:.1f}°  ·  "
                    f"|B| {values['B_magnitude']:.4f} T  ·  "
                    f"Br {values['Br']:.4f} T  ·  Bθ {values['Btheta']:.4f} T")
                marker = getattr(self, '_probe_marker', None)
                if marker is not None:
                    marker.remove()
                self._probe_marker, = window.flux_density_ax.plot(
                    [event.xdata], [event.ydata], 'o', markersize=5,
                    markerfacecolor='#4f8cff', markeredgecolor='white', zorder=9)
                window.flux_density_canvas.draw_idle()
                return
        window.flux_probe_label.setText('Select a point inside the solved machine region.')

    def _create_material_properties_tab(self):
        window = self.main_window
        tab = QWidget()
        layout = QVBoxLayout(tab)

        material_group = QGroupBox("Material Permeabilities")
        material_layout = QFormLayout(material_group)
        material_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        defaults = DEFAULT_RELATIVE_PERMEABILITIES
        window.flux_ur_stator = QLineEdit(str(int(defaults['ur_stator'])))
        window.flux_ur_rotor = QLineEdit(str(int(defaults['ur_rotor'])))

        material_layout.addRow("Stator μr", window.flux_ur_stator)
        material_layout.addRow("Rotor μr", window.flux_ur_rotor)
        layout.addWidget(material_group)

        machine_group = QGroupBox("Machine Parameters")
        machine_layout = QFormLayout(machine_group)
        machine_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        window.flux_calc_axial_length = QLineEdit(str(int(DEFAULT_AXIAL_LENGTH_MM)))
        machine_layout.addRow("Axial length [mm]", window.flux_calc_axial_length)
        layout.addWidget(machine_group)

        layout.addStretch()
        return tab

    def _create_analysis_statistics_tab(self):
        window = self.main_window
        tab = QWidget()
        layout = QVBoxLayout(tab)

        stats_group = QGroupBox("Analysis Statistics")
        stats_layout = QFormLayout(stats_group)
        stats_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        region_layout = QHBoxLayout()
        window.flux_region_selector = QComboBox()
        window.flux_region_selector.addItems(ANALYSIS_REGIONS)
        window.flux_region_selector.currentTextChanged.connect(
            self.update_regional_statistics)
        region_layout.addWidget(window.flux_region_selector)
        region_layout.addStretch()

        window.flux_br_max_label = QLabel("Not calculated")
        window.flux_br_avg_label = QLabel("Not calculated")
        window.flux_max_flux_label = QLabel("Not calculated")
        window.flux_avg_flux_label = QLabel("Not calculated")
        window.flux_max_br_airgap_label = QLabel("Not calculated")
        for value in (window.flux_br_max_label, window.flux_br_avg_label,
                      window.flux_max_flux_label, window.flux_avg_flux_label,
                      window.flux_max_br_airgap_label):
            value.setWordWrap(True)

        stats_layout.addRow("Analysis Region:", region_layout)
        stats_layout.addRow("Peak |Br|", window.flux_br_max_label)
        stats_layout.addRow("Mean excited |Br|", window.flux_br_avg_label)
        stats_layout.addRow("Peak branch flux", window.flux_max_flux_label)
        stats_layout.addRow("Mean excited branch flux", window.flux_avg_flux_label)
        stats_layout.addRow("Air-gap peak |Br|", window.flux_max_br_airgap_label)

        layout.addWidget(stats_group)
        layout.addStretch()
        return tab

    def _create_animation_tab(self):
        window = self.main_window
        tab = QWidget()
        layout = QVBoxLayout(tab)

        settings_group = QGroupBox("Animation Settings")
        settings_layout = QFormLayout(settings_group)
        settings_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        window.flux_anim_visualization_type = QComboBox()
        window.flux_anim_visualization_type.addItems(VISUALISATION_MODES)
        settings_layout.addRow("Display Mode:", window.flux_anim_visualization_type)

        window.flux_anim_angle_step_spin = QSpinBox()
        window.flux_anim_angle_step_spin.setRange(1, 30)
        window.flux_anim_angle_step_spin.setValue(1)
        window.flux_anim_angle_step_spin.setSuffix("°")
        settings_layout.addRow("Angle Step:", window.flux_anim_angle_step_spin)

        window.flux_anim_interval_spin = QSpinBox()
        window.flux_anim_interval_spin.setRange(8, 1000)
        window.flux_anim_interval_spin.setValue(16)
        window.flux_anim_interval_spin.setSuffix(" ms")
        window.flux_anim_interval_spin.valueChanged.connect(
            self._update_animation_interval)
        settings_layout.addRow("Frame Interval:", window.flux_anim_interval_spin)

        window.flux_anim_symmetry_check = QCheckBox("Loop over 180° electrical")
        window.flux_anim_symmetry_check.setChecked(True)
        settings_layout.addRow("", window.flux_anim_symmetry_check)

        layout.addWidget(settings_group)

        window.flux_anim_info_label = QLabel("Prepare once, then play continuously.")
        window.flux_anim_info_label.setStyleSheet(PAGE_SUBTITLE_STYLE)
        layout.addWidget(window.flux_anim_info_label)

        buttons_layout = QVBoxLayout()
        playback_layout = QHBoxLayout()

        window.flux_prepare_anim_btn = QPushButton("Prepare animation")
        window.flux_prepare_anim_btn.clicked.connect(self.prepare_animation_frames)
        window.flux_prepare_anim_btn.setEnabled(False)
        buttons_layout.addWidget(window.flux_prepare_anim_btn)

        window.flux_play_anim_btn = QPushButton("Play")
        window.flux_play_anim_btn.clicked.connect(self.play_animation)
        window.flux_play_anim_btn.setEnabled(False)
        playback_layout.addWidget(window.flux_play_anim_btn)

        window.flux_pause_anim_btn = QPushButton("Pause")
        window.flux_pause_anim_btn.clicked.connect(self.pause_animation)
        window.flux_pause_anim_btn.setEnabled(False)
        playback_layout.addWidget(window.flux_pause_anim_btn)

        window.flux_stop_anim_btn = QPushButton("Stop")
        window.flux_stop_anim_btn.clicked.connect(self.stop_animation)
        window.flux_stop_anim_btn.setEnabled(False)
        playback_layout.addWidget(window.flux_stop_anim_btn)
        buttons_layout.addLayout(playback_layout)

        layout.addLayout(buttons_layout)
        layout.addStretch()
        return tab

    def _setup_flux_density_visualization(self):
        window = self.main_window
        window.flux_density_figure, window.flux_density_ax = plt.subplots(
            figsize=(8, 8))
        window.flux_density_figure.patch.set_facecolor('white')
        window.flux_density_ax.set_facecolor('white')
        window.flux_density_figure.set_layout_engine('constrained')

        window.flux_density_canvas = FigureCanvas(window.flux_density_figure)
        self._setup_pyqtgraph_animation_view()
        self._initialize_placeholder_plot()

    def _setup_pyqtgraph_animation_view(self):
        if not self.pyqtgraph_available:
            return
        window = self.main_window
        window.flux_anim_pg_widget = FieldAnimationView()
        window.flux_anim_pg_plot = window.flux_anim_pg_widget.plot
        window.flux_anim_pg_image_item = window.flux_anim_pg_widget.image

    def _initialize_placeholder_plot(self):
        ax = self.main_window.flux_density_ax
        ax.clear()
        ax.text(0.5, 0.55, 'Magnetic field', transform=ax.transAxes,
                ha='center', va='center', fontsize=20, color='#262626')
        ax.text(0.5, 0.46, 'Generate a mesh, then select Solve field.',
                transform=ax.transAxes, ha='center', va='center',
                fontsize=11, color='#666666')
        ax.set_xlim(-100, 100)
        ax.set_ylim(-100, 100)
        ax.set_aspect('equal')
        ax.set_axis_off()
        self.main_window.flux_density_canvas.draw()

    # -------------------------------------------------------------- pipeline

    def _mesh_data(self):
        meshing_page = getattr(self.main_window, 'meshing_page_ui', None)
        return meshing_page.mesh_data if meshing_page else None

    def _mmf_engine(self):
        connection_tab = getattr(self.main_window, 'connection_tab', None)
        return connection_tab.mmf_calculator if connection_tab else None

    def flux_calculate(self):
        """Run reluctance, teeth MMF, and flux calculations on the mesh."""
        window = self.main_window
        try:
            self.flux_results = None
            self.reluctance_results = None
            self.mmf_results = None
            window.flux_export_all_btn.setEnabled(False)
            window.flux_generate_visualisation_btn.setEnabled(False)
            window.flux_prepare_anim_btn.setEnabled(False)
            mesh_data = self._mesh_data()
            if not mesh_data:
                self._set_status("Error: No mesh data available", 'error')
                return

            mmf_engine = self._mmf_engine()
            if mmf_engine is None:
                self._set_status(
                    "Error: No MMF data available. "
                    "Please generate MMF curves first.", 'error')
                return

            material_properties = {
                'ur_stator': float(window.flux_ur_stator.text()),
                'ur_rotor': float(window.flux_ur_rotor.text()),
                'ur_air': DEFAULT_RELATIVE_PERMEABILITIES['ur_air'],
            }
            machine_params = {
                'axial_length': float(window.flux_calc_axial_length.text()),
            }
            mesh_settings = window.meshing_page_ui.get_current_mesh_settings()

            window.flux_calculate_btn.setEnabled(False)
            window.flux_progress_bar.setVisible(True)
            window.flux_progress_bar.setValue(0)
            self._set_status("Calculating reluctances and MMF...")

            total_elements = len(mesh_data['mesh_elements'])

            def progress_callback(message):
                self._set_status(message)
                QApplication.processEvents()

            progress_callback(f"Selected solver: {SOLVER_LABEL}")

            progress_callback("Step 1/4: Calculating reluctances...")
            window.flux_progress_bar.setValue(15)
            cache_key = (id(mesh_data), tuple(sorted(mesh_data['params'].items())),
                         tuple(sorted(material_properties.items())), machine_params['axial_length'])
            if self._reluctance_cache is not None and self._reluctance_cache[0] == cache_key:
                self.reluctance_results = self._reluctance_cache[1]
            else:
                self.reluctance_results = self.reluctance_calculator.calculate_reluctances(
                    mesh_data, material_properties, machine_params, progress_callback)
                self._reluctance_cache = (cache_key, self.reluctance_results)

            window.flux_progress_bar.setValue(35)
            progress_callback("Step 2/4: Calculating teeth MMF...")
            self.mmf_results = self.mmf_calculator.calculate_teeth_mmf(
                mesh_data, mesh_settings, mmf_engine, progress_callback)

            window.flux_progress_bar.setValue(55)
            progress_callback("Step 3/4: Integrating MMF and calculating flux...")
            self.integrate_mmf_with_reluctance()

            window.flux_progress_bar.setValue(70)
            progress_callback("Step 4/4: Calculating flux distribution...")
            self.flux_results = self.flux_calculator.calculate_flux_distribution(
                self.reluctance_results, self.mmf_results, SOLVER_OPTIONS,
                progress_callback)

            window.flux_progress_bar.setValue(90)
            self.update_regional_statistics()
            self.update_flux_statistics()
            window.flux_progress_bar.setValue(100)

            flux_stats = self.flux_results['statistics']
            self._set_status(
                f"Calculation completed with {SOLVER_LABEL} solver! "
                f"({total_elements:,} elements, "
                f"{flux_stats['non_zero_fluxes']:,} active flux branches)",
                'success')

            window.flux_export_all_btn.setEnabled(True)
            window.flux_generate_visualisation_btn.setEnabled(True)
            window.flux_prepare_anim_btn.setEnabled(True)
            self.generate_visualisation()

        except Exception as error:
            self._set_status(f"Calculation failed: {error}", 'error')
            logger.exception("Error in flux calculation")
        finally:
            window.flux_calculate_btn.setEnabled(True)
            window.flux_progress_bar.setVisible(False)

    def integrate_mmf_with_reluctance(self):
        """Attach MMF source values to each reluctance element."""
        if not self.reluctance_results or not self.mmf_results:
            return

        reluctance_data = self.reluctance_results['reluctance_data']
        mmf_data = self.mmf_results['mmf_data']
        mmf_lookup = {data['element_id']: data['mmf_values']
                      for data in mmf_data}

        zero_mmf = {'MMF_up': 0.0, 'MMF_down': 0.0,
                    'MMF_left': 0.0, 'MMF_right': 0.0, 'tooth_number': -1}

        for reluctance_elem in reluctance_data:
            element_id = reluctance_elem['element_id']
            reluctance_elem['mmf_values'] = mmf_lookup.get(element_id,
                                                           dict(zero_mmf))

        self.reluctance_results['statistics']['mmf_integration'] = {
            'elements_with_mmf': sum(
                1 for data in mmf_data
                if data['mmf_values']['MMF_up'] != 0
                or data['mmf_values']['MMF_down'] != 0),
            'tooth_layers': self.mmf_results['statistics']['tooth_layers'],
            'num_teeth': self.mmf_results['statistics']['num_teeth'],
        }

    # ------------------------------------------------------------ statistics

    @staticmethod
    def _abs_metrics(br_values, flux_values):
        """Max and excited-average of absolute Br and flux value lists."""
        br_excited = [value for value in br_values if value > EXCITED_EPSILON]
        flux_excited = [value for value in flux_values if value > EXCITED_EPSILON]

        return {
            'br_max': max(br_values) if br_values else 0.0,
            'br_avg_excited': float(np.mean(br_excited)) if br_excited else 0.0,
            'br_excited_count': len(br_excited),
            'flux_max': max(flux_values) if flux_values else 0.0,
            'flux_avg_excited': (float(np.mean(flux_excited))
                                 if flux_excited else 0.0),
            'flux_excited_count': len(flux_excited),
        }

    def update_regional_statistics(self):
        """Refresh Br/flux statistics for the selected analysis region."""
        window = self.main_window
        if not self.reluctance_results or not self.flux_results:
            for label in (window.flux_br_max_label, window.flux_br_avg_label,
                          window.flux_max_flux_label, window.flux_avg_flux_label):
                label.setText("Not calculated")
            return

        try:
            selected_region = window.flux_region_selector.currentText()
            flux_densities = self.flux_results.get('flux_densities', {})
            branch_fluxes = self.flux_results.get('branch_fluxes', {})

            region_element_ids = [
                data['element_id']
                for data in self.reluctance_results['reluctance_data']
                if data.get('material') == selected_region
            ]

            if not region_element_ids:
                for label in (window.flux_br_max_label, window.flux_br_avg_label,
                              window.flux_max_flux_label,
                              window.flux_avg_flux_label):
                    label.setText("No data for this region")
                return

            br_values = []
            flux_values = []
            for element_id in region_element_ids:
                density_data = flux_densities.get(element_id, {})
                br_values.append(abs(float(density_data.get('Br', 0.0))))

                branch_data = branch_fluxes.get(element_id, {})
                for direction in ('up', 'down', 'left', 'right'):
                    flux_values.append(abs(float(branch_data.get(direction, 0.0))))

            metrics = self._abs_metrics(br_values, flux_values)

            window.flux_br_max_label.setText(
                f"{metrics['br_max']:.3f} T ({len(region_element_ids):,} elements)")
            window.flux_br_avg_label.setText(
                f"{metrics['br_avg_excited']:.3f} T "
                f"({metrics['br_excited_count']:,} excited)")
            window.flux_max_flux_label.setText(f"{metrics['flux_max']:.2e} Wb")
            window.flux_avg_flux_label.setText(
                f"{metrics['flux_avg_excited']:.2e} Wb "
                f"({metrics['flux_excited_count']:,} excited)")

        except Exception:
            logger.exception("Error computing regional statistics")
            window.flux_br_max_label.setText("Error calculating Br max")
            window.flux_br_avg_label.setText("Error calculating Br avg")
            window.flux_max_flux_label.setText("Error calculating flux max")
            window.flux_avg_flux_label.setText("Error calculating flux avg")

    def update_flux_statistics(self):
        """Refresh the dedicated air-gap Br statistic."""
        window = self.main_window
        if not self.flux_results:
            window.flux_max_br_airgap_label.setText("Not calculated")
            return

        try:
            window.flux_max_br_airgap_label.setText(
                f"{self.calculate_air_gap_flux_density():.3f} T")
        except Exception:
            window.flux_max_br_airgap_label.setText("Error calculating")

    def calculate_air_gap_flux_density(self):
        """Maximum absolute radial B over air-gap elements."""
        if not self.flux_results or 'flux_densities' not in self.flux_results:
            return 0.0

        air_gap_b_values = [
            abs(density_data['Br'])
            for density_data in self.flux_results['flux_densities'].values()
            if density_data['element_data']['material'] == 'Air Gap'
        ]
        return max(air_gap_b_values) if air_gap_b_values else 0.0

    # ----------------------------------------------------------------- export

    def export_all_results(self):
        """Export per-element reluctance/MMF/flux/density data to one file."""
        window = self.main_window
        try:
            if not self.reluctance_results or not self.flux_results:
                self._set_status(
                    "ERROR: No calculation results to export", 'error')
                return

            filename, selected_filter = QFileDialog.getSaveFileName(
                window, "Export All Results", "complete_analysis_results.csv",
                "CSV Files (*.csv);;JSON Files (*.json)")
            if not filename:
                return

            if selected_filter.startswith("JSON") or filename.lower().endswith('.json'):
                self._export_comprehensive_json(filename)
            else:
                self._export_comprehensive_csv(filename)

            self._set_status("All results exported successfully!", 'success')

        except Exception as error:
            self._set_status(f"Export error: {error}", 'error')

    def _element_export_rows(self):
        """Combined per-element export records from all result sets."""
        branch_fluxes = self.flux_results['branch_fluxes']
        flux_densities = self.flux_results['flux_densities']

        for data in self.reluctance_results['reluctance_data']:
            element_id = data['element_id']
            mmf_vals = data.get('mmf_values', {})
            flux_data = branch_fluxes.get(
                element_id, {'up': 0, 'down': 0, 'left': 0, 'right': 0})
            density_data = flux_densities.get(
                element_id, {'Br': 0, 'Btheta': 0, 'B_magnitude': 0})
            yield element_id, data, mmf_vals, flux_data, density_data

    def _export_comprehensive_csv(self, filename):
        with open(filename, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow([
                'Element_ID', 'Material',
                'R_Up', 'R_Down', 'R_Left', 'R_Right',
                'MMF_Up', 'MMF_Down',
                'Flux_Up', 'Flux_Down', 'Flux_Left', 'Flux_Right',
                'Br_Radial', 'Btheta_Circumferential', 'B_Magnitude',
            ])

            for (element_id, data, mmf_vals, flux_data,
                 density_data) in self._element_export_rows():
                writer.writerow([
                    element_id,
                    data['material'],
                    data['reluctances']['R_up'],
                    data['reluctances']['R_down'],
                    data['reluctances']['R_left'],
                    data['reluctances']['R_right'],
                    mmf_vals.get('MMF_up', 0),
                    mmf_vals.get('MMF_down', 0),
                    flux_data.get('up', 0),
                    flux_data.get('down', 0),
                    flux_data.get('left', 0),
                    flux_data.get('right', 0),
                    density_data.get('Br', 0),
                    density_data.get('Btheta', 0),
                    density_data.get('B_magnitude', 0),
                ])

    def _export_comprehensive_json(self, filename):
        essential_data = [{
            'Element_ID': element_id,
            'Material': data['material'],
            'Reluctances': {
                'R_Up': data['reluctances']['R_up'],
                'R_Down': data['reluctances']['R_down'],
                'R_Left': data['reluctances']['R_left'],
                'R_Right': data['reluctances']['R_right'],
            },
            'MMF': {
                'MMF_Up': mmf_vals.get('MMF_up', 0),
                'MMF_Down': mmf_vals.get('MMF_down', 0),
            },
            'Flux': {
                'Flux_Up': flux_data.get('up', 0),
                'Flux_Down': flux_data.get('down', 0),
                'Flux_Left': flux_data.get('left', 0),
                'Flux_Right': flux_data.get('right', 0),
            },
            'Flux_Density': {
                'Br_Radial': density_data.get('Br', 0),
                'Btheta_Circumferential': density_data.get('Btheta', 0),
                'B_Magnitude': density_data.get('B_magnitude', 0),
            },
        } for (element_id, data, mmf_vals, flux_data,
               density_data) in self._element_export_rows()]

        with open(filename, 'w') as json_file:
            json.dump(essential_data, json_file, indent=2, default=str)

    # ----------------------------------------------------------- visualisation

    def _reset_visualisation_axis(self):
        window = self.main_window
        window.flux_density_figure.clear()
        window.flux_density_ax = window.flux_density_figure.add_subplot(111)
        self._probe_marker = None
        window.flux_probe_label.setText('Click the field to inspect flux density.')

    def _render_mode(self, mode, ax, figure, mesh_data, flux_densities,
                     branch_fluxes, machine_params):
        """Dispatch one visualisation mode onto the given axis."""
        count_control = getattr(self.main_window, 'flux_contour_count', None)
        contour_count = count_control.value() if count_control is not None else DEFAULT_CONTOUR_COUNT
        if mode == "Flux Lines":
            return generate_flux_lines_visualisation(
                ax, figure, mesh_data, branch_fluxes, machine_params,
                flux_densities=flux_densities, contour_count=contour_count)
        if mode == "Flux Line + Density":
            return generate_flux_line_density_visualisation(
                ax, figure, mesh_data, flux_densities, branch_fluxes,
                machine_params, contour_count=contour_count)
        return generate_flux_density_heatmap(
            ax, figure, mesh_data, flux_densities, machine_params)

    def generate_visualisation(self):
        """Render the selected visualisation onto the main canvas."""
        window = self.main_window
        try:
            if self.animation_timer.isActive():
                self.pause_animation()
            self._show_static_view()

            if not self.flux_results:
                self._set_status(
                    "Error: No flux calculation results available", 'error')
                return

            mesh_data = self._mesh_data()
            if not mesh_data:
                self._set_status("Error: No mesh data available", 'error')
                return

            machine_params = window.meshing_page_ui.get_machine_parameters()
            machine_params['axial_length'] = float(window.flux_calc_axial_length.text())

            visualisation_type = window.flux_visualization_type.currentText()
            self._set_status(
                f"Generating {visualisation_type.lower()}...")
            QApplication.processEvents()

            self._reset_visualisation_axis()

            success = self._render_mode(
                visualisation_type,
                window.flux_density_ax,
                window.flux_density_figure,
                mesh_data,
                self.flux_results.get('flux_densities', {}),
                self.flux_results.get('branch_fluxes', {}),
                machine_params)

            if success:
                info = getattr(window.flux_density_figure, '_flux_contour_info', None)
                window.flux_contour_count.setEnabled(visualisation_type != 'B Heatmap')
                if info and info['count']:
                    window.flux_contour_label.setText(
                        f"{info['count']} contours  ·  Equal flux interval "
                        f"{info['flux_step_wb'] * 1e6:.2f} µWb")
                elif info:
                    window.flux_contour_label.setText('Zero magnetic flux')
                else:
                    window.flux_contour_label.clear()
                window.flux_density_canvas.draw_idle()
                self._set_status(
                    f"{visualisation_type} generated successfully!", 'success')
            else:
                self._set_status(
                    f"Failed to generate {visualisation_type.lower()}", 'error')

        except Exception as error:
            self._set_status(
                f"Visualisation generation failed: {error}", 'error')
            logger.exception("Error generating visualisation")

    # -------------------------------------------------------------- animation

    def _show_static_view(self):
        window = self.main_window
        if hasattr(window, 'flux_density_toolbar'):
            window.flux_density_toolbar.setVisible(True)
        if hasattr(window, 'flux_display_stack'):
            window.flux_display_stack.setCurrentIndex(0)

    def _show_animation_view(self):
        window = self.main_window
        if not (self.pyqtgraph_available and hasattr(window, 'flux_display_stack')):
            self._show_static_view()
            return

        if window.flux_display_stack.count() > 1:
            window.flux_display_stack.setCurrentIndex(1)
            if hasattr(window, 'flux_density_toolbar'):
                window.flux_density_toolbar.setVisible(False)
        else:
            self._show_static_view()

    def _get_animation_span_degrees(self):
        # Wt is ELECTRICAL: its period does not depend on the pole-pair count.
        # |B| and undirected Az contours repeat after 180 electrical degrees.
        return 180.0 if self.main_window.flux_anim_symmetry_check.isChecked() else 360.0

    def _animation_input_signature(self):
        window = self.main_window
        engine = self._mmf_engine()
        matrix = getattr(engine, 'matrix', None)
        geometry = tuple(field.text() for field in (
            window.flux_stator_rout, window.flux_stator_rin,
            window.flux_air_gap_thickness, window.flux_shaft_radius,
            window.flux_num_slots, window.flux_slot_angle, window.flux_slot_height))
        return (id(self._mesh_data()), geometry,
                (matrix.shape, matrix.tobytes()) if matrix is not None else None,
                getattr(engine, 'phase_count', 3), getattr(engine, 'is_double_layer', False),
                getattr(engine, 'turns', None), getattr(engine, 'phase_current_a', None),
                getattr(engine, 'slot_arc_deg', None), window.flux_ur_stator.text(),
                window.flux_ur_rotor.text(), window.flux_calc_axial_length.text())

    def _connect_animation_inputs(self):
        window = self.main_window
        for field in (window.flux_stator_rout, window.flux_stator_rin,
                      window.flux_air_gap_thickness, window.flux_shaft_radius,
                      window.flux_num_slots, window.flux_slot_angle, window.flux_slot_height,
                      window.flux_ur_stator, window.flux_ur_rotor, window.flux_calc_axial_length):
            field.textChanged.connect(self.invalidate_animation)
        for control in (window.phases_spin, window.slots_spin, window.poles_spin, window.span_spin,
                        window.connection_tab.turns_spin, window.connection_tab.current_spin):
            control.valueChanged.connect(self.invalidate_animation)
        window.single_layer.toggled.connect(self.invalidate_animation)

    def invalidate_animation(self, *_):
        self.pause_animation()
        self.animation_model = None
        self.animation_frames = []
        self._cached_animation_signature = None
        if self._animation_worker is not None:
            self._animation_worker.requestInterruption()
        for name in ('flux_play_anim_btn', 'flux_pause_anim_btn', 'flux_stop_anim_btn'):
            if hasattr(self.main_window, name):
                getattr(self.main_window, name).setEnabled(False)
        if hasattr(self.main_window, 'flux_anim_info_label'):
            self.main_window.flux_anim_info_label.setText('Settings changed. Prepare animation again.')
        self._show_static_view()

    def _update_animation_interval(self):
        if self.animation_timer.isActive():
            self._playback_start_angle = self._animation_angle
            self._playback_start_time = time.perf_counter()
            self.animation_timer.setInterval(self.main_window.flux_anim_interval_spin.value())

    def prepare_animation_frames(self):
        """Prepare two basis fields in a worker; playback synthesises any angle."""
        window = self.main_window
        if self._animation_worker is not None:
            self._animation_worker.requestInterruption()
            self._set_status('Cancelling animation preparation...')
            return
        if not self.pyqtgraph_available or not self._mesh_data():
            self._set_status('Generate a mesh and install pyqtgraph before animation.', 'warning')
            return
        signature = self._animation_input_signature()
        if self.animation_model is not None and signature == self._cached_animation_signature:
            self.pause_animation()
            self._activate_animation_model(self.animation_model)
            return
        self.pause_animation()
        try:
            materials = {'ur_stator': float(window.flux_ur_stator.text()),
                         'ur_rotor': float(window.flux_ur_rotor.text()),
                         'ur_air': DEFAULT_RELATIVE_PERMEABILITIES['ur_air']}
            # All worker inputs are snapshots, never live Qt controls/shared engines.
            mesh = deepcopy(self._mesh_data())
            engine = deepcopy(self._mmf_engine())
            resolution = int(np.clip(window.flux_density_canvas.height(), 480, 800))
            worker = AnimationPreparation(
                window, mesh=mesh, engine=engine, materials=materials,
                axial_length_mm=float(window.flux_calc_axial_length.text()),
                mesh_settings=dict(window.meshing_page_ui.get_current_mesh_settings()),
                resolution=resolution)
            self._animation_worker = worker
            self._animation_generation_signature = signature
            worker.progress.connect(self._animation_progress)
            worker.prepared.connect(self._animation_prepared)
            worker.failed.connect(self._animation_failed)
            worker.finished.connect(self._animation_worker_finished)
            window.flux_prepare_anim_btn.setText('Cancel preparation')
            window.flux_progress_bar.setVisible(True)
            window.flux_progress_bar.setValue(0)
            for button in (window.flux_play_anim_btn, window.flux_pause_anim_btn, window.flux_stop_anim_btn):
                button.setEnabled(False)
            worker.start()
        except Exception as error:
            self._set_status(f'Animation preparation failed: {error}', 'error')

    def _animation_progress(self, percent, message):
        self.main_window.flux_progress_bar.setValue(percent)
        self._set_status(message)

    def _animation_prepared(self, model):
        if (self._animation_worker.isInterruptionRequested()
                or self._animation_generation_signature != self._animation_input_signature()):
            self._set_status('Settings changed. Prepare animation again.', 'warning')
            return
        self.animation_model = model
        self._cached_animation_signature = self._animation_generation_signature
        self._activate_animation_model(model)

    def _activate_animation_model(self, model):
        window = self.main_window
        self.animation_mode = window.flux_anim_visualization_type.currentText()
        self.animation_span_degrees = self._get_animation_span_degrees()
        step = window.flux_anim_angle_step_spin.value()
        self.animation_frames = [{'wt': float(a)} for a in np.arange(0, self.animation_span_degrees, step)]
        self.animation_frame_index = 0
        self._animation_angle = 0.0
        window.flux_anim_pg_widget.set_model(model, self.animation_mode,
                                             window.flux_contour_count.value())
        self._render_animation_frame(0)
        window.flux_play_anim_btn.setEnabled(True)
        window.flux_pause_anim_btn.setEnabled(False)
        window.flux_stop_anim_btn.setEnabled(True)
        self._set_status(f'Animation ready in {model.generation_seconds:.2f} s | '
                         f'2 field solves | {model.storage_bytes/1048576:.1f} MB. Press Play.', 'success')

    def _animation_failed(self, message):
        self._set_status(message if 'cancelled' in message.lower()
                         else f'Animation preparation failed: {message}', 'warning')

    def _animation_worker_finished(self):
        worker = self._animation_worker
        self._animation_worker = None
        self.main_window.flux_prepare_anim_btn.setText('Prepare animation')
        self.main_window.flux_progress_bar.setVisible(False)
        worker.deleteLater()

    def _render_animation_angle(self, angle):
        self._animation_angle = angle
        self._show_animation_view()
        self.main_window.flux_anim_pg_widget.show_angle(angle)
        self.main_window.flux_anim_info_label.setText(
            f'Wt={angle:.1f}° | {self.animation_span_degrees:.0f}° loop | continuous playback')

    def _render_animation_frame(self, frame_index):
        if self.animation_frames and self.animation_model is not None:
            self._render_animation_angle(self.animation_frames[frame_index]['wt'])

    def _advance_animation_frame(self):
        if not self.animation_frames or self.animation_model is None:
            self.pause_animation()
            return
        elapsed_ms = (time.perf_counter() - self._playback_start_time) * 1000
        window = self.main_window
        angle = (self._playback_start_angle + elapsed_ms * window.flux_anim_angle_step_spin.value()
                 / window.flux_anim_interval_spin.value()) % self.animation_span_degrees
        self._render_animation_angle(angle)

    def play_animation(self):
        if self.animation_model is None or not self.animation_frames:
            self._set_status('Prepare animation first.', 'warning')
            return
        self._playback_start_time = time.perf_counter()
        self._playback_start_angle = self._animation_angle
        self.animation_timer.start(self.main_window.flux_anim_interval_spin.value())
        self.main_window.flux_play_anim_btn.setEnabled(False)
        self.main_window.flux_pause_anim_btn.setEnabled(True)
        self.main_window.flux_stop_anim_btn.setEnabled(True)
        self._set_status('Animation playing...')

    def pause_animation(self):
        was_running = self.animation_timer.isActive()
        self.animation_timer.stop()
        if hasattr(self.main_window, 'flux_play_anim_btn'):
            self.main_window.flux_play_anim_btn.setEnabled(bool(self.animation_frames))
            self.main_window.flux_pause_anim_btn.setEnabled(False)
        if was_running:
            self._set_status('Animation paused.', 'muted')

    def stop_animation(self):
        self.pause_animation()
        self.animation_frame_index = 0
        if self.animation_frames:
            self._render_animation_frame(0)
            self._set_status('Animation stopped.', 'muted')

    # --------------------------------------------------------- FEMM validation

    def _femm_input_signature(self):
        """Detect edits made while an independent FEMM solve is running."""
        engine = self._mmf_engine()
        window = self.main_window
        mesh = self._mesh_data()
        matrix = getattr(engine, 'matrix', None)
        return (id(mesh), repr(mesh['params']) if mesh else None,
                (matrix.shape, matrix.tobytes()) if matrix is not None else None,
                getattr(engine, 'phase_count', 3), getattr(engine, 'is_double_layer', None),
                getattr(engine, 'turns', None),
                getattr(engine, 'phase_current_a', None),
                getattr(engine, 'wt_angle_deg', None),
                repr(window.meshing_page_ui.get_current_mesh_settings()),
                window.flux_ur_stator.text(), window.flux_ur_rotor.text(),
                window.flux_calc_axial_length.text())

    def run_femm_validation(self):
        """Recompute the active model, then run FEMM without blocking Qt."""
        window = self.main_window
        if self.femm_process is not None or getattr(self, '_femm_preparing', False):
            return
        self._femm_preparing = True
        try:
            mesh = self._mesh_data()
            if not mesh:
                raise ValueError('Generate a mesh in Mesh (stage 04) before validating.')
            engine = self._mmf_engine()
            if engine is None or engine.matrix is None:
                raise ValueError('Generate the winding and MMF curves first.')
            signature = self._femm_input_signature()
            materials = {'ur_stator': float(window.flux_ur_stator.text()),
                         'ur_rotor': float(window.flux_ur_rotor.text())}
            length = float(window.flux_calc_axial_length.text())
            run_dir = (FEMM_VALIDATION_DIR / 'runs'
                       / (datetime.now().strftime('%Y%m%d-%H%M%S-')
                          + uuid4().hex[:8]))
            script = build_validation_script(mesh, engine, materials,
                                              length, run_dir)
            # Never compare FEMM to a stale solve after current/Wt/material edits.
            self.flux_results = None
            window.flux_femm_validation_btn.setEnabled(False)
            self.flux_calculate()
            if not self.flux_results:
                raise RuntimeError(window.flux_status_label.text())
            if signature != self._femm_input_signature():
                raise RuntimeError('Inputs changed during the local calculation. '
                                   'Run validation again for the new settings.')
            local = compute_reference_metrics(
                self.flux_results, airgap_samples(mesh), length)
            self._femm_run = {
                'directory': run_dir,
                'results': run_dir / 'validation_results.txt',
                'response': run_dir / 'worker-response.json',
                'local': local,
                'profile': airgap_profile(self.flux_results, airgap_samples(mesh)),
                'signature': signature,
                'inputs': (f'{getattr(engine, "phase_count", 3)} phases, '
                           f'{mesh["params"]["num_slots"]} slots, '
                           f'{engine.turns} turns, '
                           f'{engine.phase_current_a:g} A, '
                           f'Wt={engine.wt_angle_deg:g} deg'),
            }
            self.femm_process = QProcess(window)
            self.femm_process.finished.connect(self._finish_femm_validation)
            self.femm_process.errorOccurred.connect(self._femm_process_error)
            self._femm_watchdog = QTimer(self.femm_process)
            self._femm_watchdog.setSingleShot(True)
            self._femm_watchdog.timeout.connect(self._femm_timeout)
            self._femm_watchdog.start((FEMM_RUN_TIMEOUT_S + 15) * 1000)
            window.flux_calculate_btn.setEnabled(False)
            window.flux_progress_bar.setRange(0, 0)
            window.flux_progress_bar.setVisible(True)
            self._set_status('Running FEMM comparison for the current model...')
            self.femm_process.setWorkingDirectory(str(PROJECT_ROOT))
            command = femm_worker_command()
            self.femm_process.start(command[0], command[1:] + [
                '--script', str(script),
                '--results', str(self._femm_run['results']),
                '--response', str(self._femm_run['response']),
                '--timeout', str(FEMM_RUN_TIMEOUT_S), '--keep-open'])
        except Exception as error:
            window.flux_femm_validation_btn.setEnabled(True)
            self._femm_failure(str(error))
        finally:
            self._femm_preparing = False

    def _femm_timeout(self):
        if self.femm_process is not None:
            self._femm_run['timed_out'] = True
            self.femm_process.kill()

    def _femm_process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.femm_process is not None:
            self._finish_femm_validation(-1, QProcess.ExitStatus.CrashExit)

    def _femm_failure(self, message):
        self._set_status(f'FEMM validation failed: {message}', 'error')
        logger.error('FEMM validation failed: %s', message)
        QMessageBox.critical(self.main_window, 'Validation using FEMM', message)

    def _finish_femm_validation(self, exit_code, exit_status):
        process = self.femm_process
        if process is None:
            return
        window = self.main_window
        run = self._femm_run
        self._femm_watchdog.stop()
        stdout = bytes(process.readAllStandardOutput()).decode('utf-8', 'replace')
        stderr = bytes(process.readAllStandardError()).decode('utf-8', 'replace')
        self.femm_process = None
        process.deleteLater()
        window.flux_calculate_btn.setEnabled(True)
        window.flux_femm_validation_btn.setEnabled(True)
        window.flux_progress_bar.setVisible(False)
        window.flux_progress_bar.setRange(0, 100)
        try:
            response_path = run.get('response')
            response = (json.loads(response_path.read_text(encoding='utf-8'))
                        if response_path and response_path.is_file() else {})
            if run.get('timed_out'):
                raise RuntimeError('FEMM validation timed out.')
            if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
                raise RuntimeError(response.get('error') or stderr.strip()
                                   or 'FEMM worker could not run.')
            payload = response or json.loads(stdout)
            femm_metrics = parse_validation_results(run['results'])
            summary = [run['inputs'], f'Run backend: {payload["backend"]}',
                       'FEMM remains open: |B| colour map, flux lines and field values.',
                       'Matched air-gap samples; radial sector flux = |Br| r dtheta L.', '']
            if 'profile' in run:
                summary.insert(3, f'{len(run["profile"])} points at radius '
                               f'{run["profile"][0, 0]:.6g} mm.')
            deviations = []
            mean_br_key = ('airgap_br_mean_abs_t' if 'airgap_br_mean_abs_t' in femm_metrics
                           and 'airgap_br_mean_abs_t' in run['local']
                           else 'airgap_br_avg_excited_t')
            mean_flux_key = ('airgap_flux_mean_abs_wb' if 'airgap_flux_mean_abs_wb' in femm_metrics
                             and 'airgap_flux_mean_abs_wb' in run['local']
                             else 'airgap_flux_avg_excited_wb')
            for key, label, unit in (
                    ('airgap_br_max_t', 'Br max', 'T'),
                    (mean_br_key, 'Mean |Br|', 'T'),
                    ('airgap_flux_max_wb', 'Radial flux max', 'Wb'),
                    (mean_flux_key, 'Mean absolute radial flux', 'Wb')):
                reference, local = femm_metrics[key], run['local'][key]
                if reference > 1e-12:
                    difference = abs(local - reference) / reference * 100
                    deviations.append(difference)
                    delta = f'{difference:.2f}%'
                else:
                    delta = f'absolute {abs(local-reference):.3e} {unit}'
                summary += [f'{label}: FEMM {reference:.6e} {unit}',
                            f'  Current model {local:.6e} {unit}; difference {delta}']
            samples_file = run['directory'] / 'airgap_samples.csv'
            if 'profile' in run and samples_file.is_file():
                profile_errors = compare_airgap_profiles(run['profile'], samples_file)
                summary.append('')
                for component, metrics in profile_errors.items():
                    normalized = metrics['normalized_l2_percent']
                    relative = (f'{normalized:.2f}%' if normalized is not None
                                else 'zero reference')
                    summary.append(f'Signed {component} curve error (L2): {relative}, '
                                   f'max absolute {metrics["max_absolute_error_t"]:.3e} T')
            summary += ['', 'Independent linear-material comparison. Review the differences;',
                        'no acceptance tolerance is configured.']
            changed = self._femm_input_signature() != run['signature']
            if changed:
                summary += ['Inputs changed during the run. Rerun for the new settings.']
            report = run['directory'] / 'comparison.txt'
            summary += ['', f'Results: {report}']
            report.write_text('\n'.join(summary), encoding='utf-8')
            difference_text = (
                f'Largest relative difference: {max(deviations):.2f}%.'
                if deviations else 'Zero FEMM reference; review absolute differences.')
            self._set_status(
                f'FEMM comparison completed. {difference_text}'
                + (' Inputs changed; rerun validation.' if changed else ''),
                'warning' if changed else 'info')
            QMessageBox.information(window, 'Validation using FEMM',
                                    '\n'.join(summary))
        except Exception as error:
            self._femm_failure(str(error))
