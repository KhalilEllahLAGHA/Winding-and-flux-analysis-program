"""Step 3: flux density heatmap page (formerly ``Meshing_flux_page_UI.py``).

Runs the reluctance -> teeth MMF -> flux solve pipeline, renders the
selected visualisation, plays Wt-sweep animations, and compares results
against a FEMM validation run.
"""

import csv
import json
import logging
import os
import shutil
import subprocess

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtCore import QRectF, QTimer
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QProgressBar, QPushButton,
                             QSpinBox, QStackedWidget, QTabWidget, QVBoxLayout,
                             QWidget)

from core.flux_solver import FluxCalculator
from core.reluctance_calculator import ReluctanceCalculator
from core.teeth_slot_mmf import TeethSlotMMFCalculator
from ui.flux_visualization import (generate_flux_density_heatmap,
                                   generate_flux_line_density_visualisation,
                                   generate_flux_lines_visualisation,
                                   setup_heatmap_animation)
from ui.theme import (FLUX_DENSITY_PAGE_STYLE, PAGE_SUBTITLE_STYLE,
                      PAGE_TITLE_STYLE, set_status)
from utils.constants import (DEFAULT_AXIAL_LENGTH_MM,
                             DEFAULT_RELATIVE_PERMEABILITIES,
                             DEFAULT_WT_ANGLE_DEG)
from utils.paths import (FEMM_VALIDATION_RESULTS, FEMM_VALIDATION_SCRIPT,
                         PROJECT_ROOT)

try:
    import pyqtgraph as pg
    pg.setConfigOptions(imageAxisOrder='row-major')
    PYQTGRAPH_AVAILABLE = True
except Exception:
    pg = None
    PYQTGRAPH_AVAILABLE = False

logger = logging.getLogger(__name__)

SOLVER_OPTIONS = {'method': 'pcg_jacobi', 'tolerance': 1e-6}
SOLVER_LABEL = "PCG (Jacobi)"
EXCITED_EPSILON = 1e-12

VISUALISATION_MODES = ("B Heatmap", "Flux Lines", "Flux Line + Density")
ANALYSIS_REGIONS = ("Air Gap", "Rotor Core", "Tooth", "Stator Core", "Slot")

ANIMATION_FRAME_DPI = 220
ANIMATION_FRAME_RESOLUTION = (1920, 1080)
FEMM_RUN_TIMEOUT_S = 300


class FluxDensityHeatmapUI:
    """Controls, statistics, animation, and FEMM validation for Step 3."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.reluctance_calculator = ReluctanceCalculator()
        self.mmf_calculator = TeethSlotMMFCalculator()
        self.flux_calculator = FluxCalculator()
        self.reluctance_results = None
        self.mmf_results = None
        self.flux_results = None

        self.animation_frames = []
        self.animation_frame_index = 0
        self.animation_span_degrees = 360.0
        self.animation_mode = VISUALISATION_MODES[0]
        self.pyqtgraph_available = PYQTGRAPH_AVAILABLE
        self.animation_frame_dpi = ANIMATION_FRAME_DPI
        self.animation_frame_resolution = ANIMATION_FRAME_RESOLUTION
        self.animation_frame_figsize = self._figsize_for_resolution()

        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self._advance_animation_frame)

    def _figsize_for_resolution(self):
        width, height = self.animation_frame_resolution
        return (width / self.animation_frame_dpi,
                height / self.animation_frame_dpi)

    def _set_status(self, text, kind='info'):
        """Color-coded feedback on the status line below the controls."""
        set_status(self.main_window.flux_status_label, text, kind)

    # ------------------------------------------------------------- UI setup

    def create_flux_density_heatmap_widget(self):
        widget = QWidget()
        widget.setStyleSheet(FLUX_DENSITY_PAGE_STYLE)

        main_layout = QHBoxLayout(widget)
        main_layout.addLayout(self._build_left_panel(), 3)
        main_layout.addWidget(self._build_right_panel(widget), 5)

        self.main_window.flux_density_page_ui = self
        return widget

    def _build_left_panel(self):
        window = self.main_window
        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(4, 4, 8, 4)
        left_panel.setSpacing(12)

        title = QLabel("Step 3: Flux Density Analysis")
        title.setStyleSheet(PAGE_TITLE_STYLE)
        left_panel.addWidget(title)

        subtitle = QLabel("Run the flux calculation, then explore "
                          "visualisations, statistics, and animations.")
        subtitle.setStyleSheet(PAGE_SUBTITLE_STYLE)
        subtitle.setWordWrap(True)
        left_panel.addWidget(subtitle)

        window.flux_tabs = QTabWidget()
        window.flux_tabs.addTab(self._create_material_properties_tab(),
                                "Material Properties")
        window.flux_tabs.addTab(self._create_analysis_statistics_tab(),
                                "Analysis Statistics")
        window.flux_tabs.addTab(self._create_animation_tab(), "Animation")
        left_panel.addWidget(window.flux_tabs)

        controls_group = QGroupBox("Analysis Controls")
        controls_layout = QVBoxLayout(controls_group)

        window.flux_calculate_btn = QPushButton("Calculate")
        window.flux_calculate_btn.setObjectName("primaryButton")
        window.flux_calculate_btn.setMinimumHeight(36)
        window.flux_calculate_btn.setToolTip(
            "Run the reluctance → teeth MMF → flux solve pipeline on the "
            "generated mesh.")
        window.flux_calculate_btn.clicked.connect(self.flux_calculate)
        controls_layout.addWidget(window.flux_calculate_btn)

        window.flux_export_all_btn = QPushButton("Export All Results")
        window.flux_export_all_btn.setMinimumHeight(35)
        window.flux_export_all_btn.clicked.connect(self.export_all_results)
        window.flux_export_all_btn.setEnabled(False)
        controls_layout.addWidget(window.flux_export_all_btn)

        window.flux_visualization_type = QComboBox()
        window.flux_visualization_type.addItems(VISUALISATION_MODES)
        controls_layout.addWidget(window.flux_visualization_type)

        window.flux_generate_visualisation_btn = QPushButton(
            "Generate Visualisation")
        window.flux_generate_visualisation_btn.setMinimumHeight(35)
        window.flux_generate_visualisation_btn.clicked.connect(
            self.generate_visualisation)
        window.flux_generate_visualisation_btn.setEnabled(False)
        controls_layout.addWidget(window.flux_generate_visualisation_btn)

        window.flux_femm_validation_btn = QPushButton("Validation using FEMM")
        window.flux_femm_validation_btn.setMinimumHeight(35)
        window.flux_femm_validation_btn.clicked.connect(self.run_femm_validation)
        controls_layout.addWidget(window.flux_femm_validation_btn)

        left_panel.addWidget(controls_group)

        window.flux_progress_bar = QProgressBar()
        window.flux_progress_bar.setVisible(False)
        left_panel.addWidget(window.flux_progress_bar)

        window.flux_status_label = QLabel("")
        window.flux_status_label.setWordWrap(True)
        set_status(window.flux_status_label, "", 'muted')
        left_panel.addWidget(window.flux_status_label)

        left_panel.addStretch()
        return left_panel

    def _build_right_panel(self, parent_widget):
        window = self.main_window

        self._setup_flux_density_visualization()

        right_panel = QVBoxLayout()
        window.flux_density_toolbar = NavigationToolbar(
            window.flux_density_canvas, parent_widget)
        right_panel.addWidget(window.flux_density_toolbar)

        window.flux_display_stack = QStackedWidget()
        window.flux_display_stack.addWidget(window.flux_density_canvas)
        if self.pyqtgraph_available and hasattr(window, 'flux_anim_pg_widget'):
            window.flux_display_stack.addWidget(window.flux_anim_pg_widget)
        right_panel.addWidget(window.flux_display_stack)

        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        return right_widget

    def _create_material_properties_tab(self):
        window = self.main_window
        tab = QWidget()
        layout = QVBoxLayout(tab)

        material_group = QGroupBox("Material Permeabilities")
        material_layout = QFormLayout(material_group)

        defaults = DEFAULT_RELATIVE_PERMEABILITIES
        window.flux_ur_stator = QLineEdit(str(int(defaults['ur_stator'])))
        window.flux_ur_rotor = QLineEdit(str(int(defaults['ur_rotor'])))

        material_layout.addRow("Stator Steel μr:", window.flux_ur_stator)
        material_layout.addRow("Rotor Steel μr:", window.flux_ur_rotor)
        layout.addWidget(material_group)

        machine_group = QGroupBox("Machine Parameters")
        machine_layout = QFormLayout(machine_group)

        window.flux_calc_axial_length = QLineEdit(str(int(DEFAULT_AXIAL_LENGTH_MM)))
        machine_layout.addRow("Axial Length (mm):", window.flux_calc_axial_length)
        layout.addWidget(machine_group)

        layout.addStretch()
        return tab

    def _create_analysis_statistics_tab(self):
        window = self.main_window
        tab = QWidget()
        layout = QVBoxLayout(tab)

        stats_group = QGroupBox("Analysis Statistics")
        stats_layout = QFormLayout(stats_group)

        region_layout = QHBoxLayout()
        window.flux_region_selector = QComboBox()
        window.flux_region_selector.addItems(ANALYSIS_REGIONS)
        window.flux_region_selector.currentTextChanged.connect(
            self.update_regional_statistics)
        region_layout.addWidget(QLabel("Region:"))
        region_layout.addWidget(window.flux_region_selector)
        region_layout.addStretch()

        window.flux_br_max_label = QLabel("Not calculated")
        window.flux_br_avg_label = QLabel("Not calculated")
        window.flux_max_flux_label = QLabel("Not calculated")
        window.flux_avg_flux_label = QLabel("Not calculated")
        window.flux_max_br_airgap_label = QLabel("Not calculated")

        stats_layout.addRow("Analysis Region:", region_layout)
        stats_layout.addRow("Br Max (Region):", window.flux_br_max_label)
        stats_layout.addRow("Br Avg Excited (Region):", window.flux_br_avg_label)
        stats_layout.addRow("Flux Max (Region):", window.flux_max_flux_label)
        stats_layout.addRow("Flux Avg Excited (Region):", window.flux_avg_flux_label)
        stats_layout.addRow("Max Br in Air Gap:", window.flux_max_br_airgap_label)

        layout.addWidget(stats_group)
        layout.addStretch()
        return tab

    def _create_animation_tab(self):
        window = self.main_window
        tab = QWidget()
        layout = QVBoxLayout(tab)

        settings_group = QGroupBox("Animation Settings")
        settings_layout = QFormLayout(settings_group)

        window.flux_anim_visualization_type = QComboBox()
        window.flux_anim_visualization_type.addItems(VISUALISATION_MODES)
        settings_layout.addRow("Display Mode:", window.flux_anim_visualization_type)

        window.flux_anim_angle_step_spin = QSpinBox()
        window.flux_anim_angle_step_spin.setRange(1, 30)
        window.flux_anim_angle_step_spin.setValue(1)
        window.flux_anim_angle_step_spin.setSuffix("°")
        settings_layout.addRow("Angle Step:", window.flux_anim_angle_step_spin)

        window.flux_anim_interval_spin = QSpinBox()
        window.flux_anim_interval_spin.setRange(30, 1000)
        window.flux_anim_interval_spin.setValue(33)
        window.flux_anim_interval_spin.setSuffix(" ms")
        window.flux_anim_interval_spin.valueChanged.connect(
            self._update_animation_interval)
        settings_layout.addRow("Frame Interval:", window.flux_anim_interval_spin)

        window.flux_anim_symmetry_check = QCheckBox("Use pair-pole symmetry")
        window.flux_anim_symmetry_check.setChecked(True)
        settings_layout.addRow("", window.flux_anim_symmetry_check)

        layout.addWidget(settings_group)

        window.flux_anim_info_label = QLabel("Frames not generated")
        window.flux_anim_info_label.setStyleSheet(
            "color: #aaaaaa; font-size: 12px;")
        layout.addWidget(window.flux_anim_info_label)

        buttons_layout = QHBoxLayout()

        window.flux_prepare_anim_btn = QPushButton("Generate Frames")
        window.flux_prepare_anim_btn.clicked.connect(self.prepare_animation_frames)
        window.flux_prepare_anim_btn.setEnabled(False)
        buttons_layout.addWidget(window.flux_prepare_anim_btn)

        window.flux_play_anim_btn = QPushButton("Play")
        window.flux_play_anim_btn.clicked.connect(self.play_animation)
        window.flux_play_anim_btn.setEnabled(False)
        buttons_layout.addWidget(window.flux_play_anim_btn)

        window.flux_pause_anim_btn = QPushButton("Pause")
        window.flux_pause_anim_btn.clicked.connect(self.pause_animation)
        window.flux_pause_anim_btn.setEnabled(False)
        buttons_layout.addWidget(window.flux_pause_anim_btn)

        window.flux_stop_anim_btn = QPushButton("Stop")
        window.flux_stop_anim_btn.clicked.connect(self.stop_animation)
        window.flux_stop_anim_btn.setEnabled(False)
        buttons_layout.addWidget(window.flux_stop_anim_btn)

        layout.addLayout(buttons_layout)
        layout.addStretch()
        return tab

    def _setup_flux_density_visualization(self):
        window = self.main_window
        window.flux_density_figure, window.flux_density_ax = plt.subplots(
            figsize=(8, 8))
        window.flux_density_figure.patch.set_facecolor('white')
        window.flux_density_ax.set_facecolor('white')
        window.flux_density_figure.set_tight_layout(True)

        window.flux_density_canvas = FigureCanvas(window.flux_density_figure)
        self._setup_pyqtgraph_animation_view()
        self._initialize_placeholder_plot()

    def _setup_pyqtgraph_animation_view(self):
        if not self.pyqtgraph_available:
            return

        window = self.main_window
        window.flux_anim_pg_widget = pg.GraphicsLayoutWidget()
        window.flux_anim_pg_widget.setBackground('w')
        window.flux_anim_pg_plot = window.flux_anim_pg_widget.addPlot()
        window.flux_anim_pg_plot.hideAxis('left')
        window.flux_anim_pg_plot.hideAxis('bottom')
        window.flux_anim_pg_plot.setAspectLocked(True)
        window.flux_anim_pg_plot.setMenuEnabled(False)
        window.flux_anim_pg_plot.setMouseEnabled(x=False, y=False)
        window.flux_anim_pg_plot.invertY(True)
        view_box = window.flux_anim_pg_plot.getViewBox()
        view_box.setDefaultPadding(0.0)
        view_box.setAspectLocked(True)

        window.flux_anim_pg_image_item = pg.ImageItem()
        if hasattr(window.flux_anim_pg_image_item, 'setAutoDownsample'):
            window.flux_anim_pg_image_item.setAutoDownsample(False)
        window.flux_anim_pg_plot.addItem(window.flux_anim_pg_image_item)

    def _initialize_placeholder_plot(self):
        ax = self.main_window.flux_density_ax
        ax.clear()
        ax.text(0, 0,
                "Flux Visualisation\n\nSelect a mode, then press "
                "'Generate Visualisation'",
                ha='center', va='center', fontsize=14, color='gray',
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#f0f0f0",
                          alpha=0.8))
        ax.set_xlim(-100, 100)
        ax.set_ylim(-100, 100)
        ax.set_aspect('equal')
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
            self.reluctance_results = self.reluctance_calculator.calculate_reluctances(
                mesh_data, material_properties, machine_params, progress_callback)

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
        """Maximum |B| over air-gap elements."""
        if not self.flux_results or 'flux_densities' not in self.flux_results:
            return 0.0

        air_gap_b_values = [
            density_data['B_magnitude']
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

    def _render_mode(self, mode, ax, figure, mesh_data, flux_densities,
                     branch_fluxes, machine_params):
        """Dispatch one visualisation mode onto the given axis."""
        if mode == "Flux Lines":
            return generate_flux_lines_visualisation(
                ax, figure, mesh_data, branch_fluxes, machine_params)
        if mode == "Flux Line + Density":
            return generate_flux_line_density_visualisation(
                ax, figure, mesh_data, flux_densities, branch_fluxes,
                machine_params)
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
                window.meshing_page_ui.get_machine_parameters())

            if success:
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

    def _get_pair_poles(self):
        """Pole-pair count from the drawing inputs or the winding tab."""
        window = self.main_window
        if hasattr(window, 'flux_num_pair_poles'):
            try:
                return max(1, int(float(window.flux_num_pair_poles.text())))
            except (ValueError, TypeError):
                pass

        if hasattr(window, 'poles_spin'):
            return max(1, int(window.poles_spin.value()))

        return 1

    def _get_animation_span_degrees(self):
        """Wt span to animate; pair-pole symmetry shortens the sweep."""
        window = self.main_window
        use_symmetry = (hasattr(window, 'flux_anim_symmetry_check')
                        and window.flux_anim_symmetry_check.isChecked())
        if not use_symmetry:
            return 360.0
        return 360.0 / self._get_pair_poles()

    def _update_animation_interval(self):
        window = self.main_window
        if self.animation_timer.isActive():
            self.animation_timer.setInterval(
                int(window.flux_anim_interval_spin.value()))

    def _sync_animation_frame_resolution(self):
        """Match the frame render size to the playback viewport."""
        target_width, target_height = ANIMATION_FRAME_RESOLUTION
        window = self.main_window

        if self.pyqtgraph_available and hasattr(window, 'flux_anim_pg_widget'):
            widget = window.flux_anim_pg_widget
            widget_width = int(widget.width())
            widget_height = int(widget.height())

            if widget_width > 32 and widget_height > 32:
                dpr = (float(widget.devicePixelRatioF())
                       if hasattr(widget, 'devicePixelRatioF') else 1.0)
                target_width = int(np.clip(
                    np.round(widget_width * dpr * 1.35), 960, 1920))
                target_height = int(np.clip(
                    np.round(widget_height * dpr * 1.35), 540, 1080))

        self.animation_frame_resolution = (target_width, target_height)
        self.animation_frame_figsize = self._figsize_for_resolution()

    def prepare_animation_frames(self):
        """Solve the flux problem at each Wt sample and pre-render frames."""
        window = self.main_window
        try:
            if not self.pyqtgraph_available:
                self._set_status(
                    "PyQtGraph is not available. Install pyqtgraph for "
                    "high-speed animation playback.", 'warning')
                return

            mesh_data = self._mesh_data()
            if not mesh_data:
                self._set_status("Error: No mesh data available", 'error')
                return

            mmf_engine = self._mmf_engine()
            if mmf_engine is None:
                self._set_status("Error: No MMF data available", 'error')
                return

            # Run the base calculation first when needed.
            if self.reluctance_results is None:
                self._set_status(
                    "Running base calculation before animation...")
                QApplication.processEvents()
                self.flux_calculate()
                if self.reluctance_results is None:
                    return

            self.pause_animation()
            self.animation_frames = []
            self.animation_frame_index = 0
            self.animation_mode = window.flux_anim_visualization_type.currentText()
            self._sync_animation_frame_resolution()

            step_deg = int(window.flux_anim_angle_step_spin.value())
            self.animation_span_degrees = self._get_animation_span_degrees()
            angles = np.arange(0.0, self.animation_span_degrees,
                               float(step_deg), dtype=np.float64)
            if angles.size == 0:
                angles = np.array([0.0], dtype=np.float64)

            machine_params = window.meshing_page_ui.get_machine_parameters()
            mesh_settings = window.meshing_page_ui.get_current_mesh_settings()

            if hasattr(window.connection_tab, 'wt_spin'):
                original_wt = float(window.connection_tab.wt_spin.value())
            else:
                original_wt = float(getattr(mmf_engine, 'wt_angle_deg',
                                            DEFAULT_WT_ANGLE_DEG))

            # For the heatmap mode, build one persistent figure whose patch
            # collection and colorbar are created once; each frame only swaps
            # the colour array. This skips rebuilding ~thousands of wedge paths
            # and the colorbar every frame (the dominant per-frame render cost).
            heatmap_figure = heatmap_ax = heatmap_update = None
            if self.animation_mode == VISUALISATION_MODES[0]:  # "B Heatmap"
                heatmap_figure, heatmap_ax = plt.subplots(
                    figsize=self.animation_frame_figsize,
                    dpi=self.animation_frame_dpi)
                heatmap_figure.patch.set_facecolor('white')
                heatmap_figure.set_tight_layout(True)
                heatmap_update = setup_heatmap_animation(
                    heatmap_ax, heatmap_figure, mesh_data, machine_params)

            window.flux_progress_bar.setVisible(True)
            window.flux_progress_bar.setValue(0)

            try:
                total_frames = len(angles)
                for idx, wt in enumerate(angles):
                    mmf_engine.update_wt_angle(float(wt))

                    # Animation only needs the aligned MMF array
                    # (build_full=False skips assembling thousands of
                    # per-element dicts) and never reads the per-solve
                    # statistics, so skip computing those too.
                    mmf_results = self.mmf_calculator.calculate_teeth_mmf(
                        mesh_data, mesh_settings, mmf_engine,
                        progress_callback=None, build_full=False)

                    flux_results = self.flux_calculator.calculate_flux_distribution(
                        self.reluctance_results, mmf_results, SOLVER_OPTIONS,
                        progress_callback=None, include_statistics=False)

                    flux_densities = flux_results.get('flux_densities', {})
                    branch_fluxes = flux_results.get('branch_fluxes', {})

                    if heatmap_update is not None:
                        frame_image = self._render_persistent_heatmap_frame(
                            heatmap_figure, heatmap_ax, heatmap_update,
                            flux_densities, branch_fluxes, wt,
                            mesh_data, machine_params)
                    else:
                        frame_image = self._build_animation_image_frame(
                            self.animation_mode, mesh_data, machine_params,
                            flux_densities, branch_fluxes, wt)

                    self.animation_frames.append({
                        'wt': float(wt),
                        'flux_densities': flux_densities,
                        'branch_fluxes': branch_fluxes,
                        'image': frame_image,
                    })

                    progress = int(((idx + 1) / total_frames) * 100)
                    window.flux_progress_bar.setValue(progress)
                    self._set_status(
                        f"Generating animation frames... {idx + 1}/{total_frames} "
                        f"(Wt={wt:.1f}°, solver={SOLVER_LABEL})")
                    QApplication.processEvents()
            finally:
                if heatmap_figure is not None:
                    plt.close(heatmap_figure)

            # Restore the configured Wt after the sweep.
            mmf_engine.update_wt_angle(original_wt)
            if hasattr(window.connection_tab, 'wt_spin'):
                window.connection_tab.wt_spin.blockSignals(True)
                window.connection_tab.wt_spin.setValue(int(round(original_wt)))
                window.connection_tab.wt_spin.blockSignals(False)

            window.flux_anim_info_label.setText(
                f"{len(self.animation_frames)} frames | {self.animation_mode} | "
                f"span 0°-{self.animation_span_degrees:.1f}° | step {step_deg}° | "
                f"{self.animation_frame_resolution[0]}x"
                f"{self.animation_frame_resolution[1]} @ "
                f"{self.animation_frame_dpi} dpi")

            if self.animation_frames:
                self._render_animation_frame(0)
                window.flux_play_anim_btn.setEnabled(True)
                window.flux_pause_anim_btn.setEnabled(False)
                window.flux_stop_anim_btn.setEnabled(True)
                self._set_status(
                    "Animation frames ready. Press Play.", 'success')
            else:
                self._set_status(
                    "Failed to generate animation frames", 'error')

        except Exception as error:
            self._set_status(
                f"Animation generation failed: {error}", 'error')
            logger.exception("Error generating animation frames")
        finally:
            window.flux_progress_bar.setVisible(False)

    def _render_persistent_heatmap_frame(self, figure, ax, update,
                                         flux_densities, branch_fluxes, wt,
                                         mesh_data, machine_params):
        """Render one heatmap frame by updating the persistent collection only.

        Falls back to the full per-frame builder when a frame has no flux data
        (matching the original heatmap behaviour exactly in that case).
        """
        if not update(flux_densities):
            return self._build_animation_image_frame(
                self.animation_mode, mesh_data, machine_params,
                flux_densities, branch_fluxes, wt)

        ax.set_title(f"{self.animation_mode} | Wt={wt:.1f}°", color='black',
                     fontsize=13, pad=14)
        figure.canvas.draw()
        width, height = figure.canvas.get_width_height()
        image = np.frombuffer(figure.canvas.buffer_rgba(), dtype=np.uint8)
        image = image.reshape(height, width, 4)
        return np.ascontiguousarray(image[:, :, :3])

    def _build_animation_image_frame(self, mode, mesh_data, machine_params,
                                     flux_densities, branch_fluxes, wt):
        """Render one RGB frame image for pyqtgraph playback."""
        frame_figure, frame_ax = plt.subplots(
            figsize=self.animation_frame_figsize, dpi=self.animation_frame_dpi)
        frame_figure.patch.set_facecolor('white')
        frame_figure.set_tight_layout(True)

        try:
            success = self._render_mode(mode, frame_ax, frame_figure, mesh_data,
                                        flux_densities, branch_fluxes,
                                        machine_params)
            if success:
                frame_ax.set_title(f"{mode} | Wt={wt:.1f}°", color='black',
                                   fontsize=13, pad=14)
            else:
                frame_ax.clear()
                frame_ax.text(0, 0, f"Failed to render {mode}\nWt={wt:.1f}°",
                              ha='center', va='center', fontsize=12, color='red',
                              bbox=dict(boxstyle="round,pad=0.5",
                                        facecolor="#ffcccc", alpha=0.8))
                frame_ax.set_xlim(-100, 100)
                frame_ax.set_ylim(-100, 100)
                frame_ax.set_aspect('equal')

            frame_figure.canvas.draw()
            width, height = frame_figure.canvas.get_width_height()
            image = np.frombuffer(frame_figure.canvas.buffer_rgba(),
                                  dtype=np.uint8)
            image = image.reshape(height, width, 4)
            return np.ascontiguousarray(image[:, :, :3])
        finally:
            plt.close(frame_figure)

    def _render_animation_frame(self, frame_index):
        """Display one precomputed frame (pyqtgraph or matplotlib fallback)."""
        if not self.animation_frames:
            return

        window = self.main_window
        frame = self.animation_frames[frame_index]
        frame_image = frame.get('image')

        if (self.pyqtgraph_available and frame_image is not None
                and hasattr(window, 'flux_anim_pg_image_item')):
            self._show_animation_view()
            window.flux_anim_pg_image_item.setImage(
                frame_image, autoLevels=False, levels=(0, 255))
            img_h, img_w = frame_image.shape[:2]
            window.flux_anim_pg_image_item.setRect(
                QRectF(0, 0, float(img_w), float(img_h)))
            view_box = window.flux_anim_pg_plot.getViewBox()
            view_box.setRange(xRange=(0.0, float(img_w)),
                              yRange=(0.0, float(img_h)),
                              padding=0.0, disableAutoRange=True)
        else:
            self._show_static_view()
            self._reset_visualisation_axis()

            success = self._render_mode(
                self.animation_mode,
                window.flux_density_ax,
                window.flux_density_figure,
                self._mesh_data(),
                frame['flux_densities'],
                frame['branch_fluxes'],
                window.meshing_page_ui.get_machine_parameters())
            if success:
                window.flux_density_canvas.draw_idle()

        window.flux_anim_info_label.setText(
            f"Frame {frame_index + 1}/{len(self.animation_frames)} | "
            f"Wt={frame['wt']:.1f}° | "
            f"span 0°-{self.animation_span_degrees:.1f}°")

    def _advance_animation_frame(self):
        if not self.animation_frames:
            self.pause_animation()
            return

        self.animation_frame_index = ((self.animation_frame_index + 1)
                                      % len(self.animation_frames))
        self._render_animation_frame(self.animation_frame_index)

    def play_animation(self):
        window = self.main_window
        if not self.pyqtgraph_available:
            self._set_status(
                "PyQtGraph backend unavailable for animation playback",
                'warning')
            return

        if not self.animation_frames:
            self._set_status(
                "No frames found. Generate frames first.", 'warning')
            return

        self._show_animation_view()
        self.animation_timer.start(int(window.flux_anim_interval_spin.value()))
        window.flux_play_anim_btn.setEnabled(False)
        window.flux_pause_anim_btn.setEnabled(True)
        window.flux_stop_anim_btn.setEnabled(True)
        self._set_status("Animation playing...")

    def pause_animation(self):
        window = self.main_window
        if self.animation_timer.isActive():
            self.animation_timer.stop()
        if hasattr(window, 'flux_play_anim_btn'):
            window.flux_play_anim_btn.setEnabled(bool(self.animation_frames))
        if hasattr(window, 'flux_pause_anim_btn'):
            window.flux_pause_anim_btn.setEnabled(False)
        if self.animation_frames:
            self._set_status("Animation paused", 'muted')

    def stop_animation(self):
        self.pause_animation()
        self.animation_frame_index = 0
        if self.animation_frames:
            self._render_animation_frame(0)
            self._set_status("Animation stopped", 'muted')

    # --------------------------------------------------------- FEMM validation

    @staticmethod
    def _locate_femm_executable():
        """Locate femm.exe for systems without the Python femm module."""
        env_path = os.environ.get('FEMM_EXE', '').strip()
        if env_path and os.path.isfile(env_path):
            return env_path

        in_path = shutil.which('femm.exe')
        if in_path:
            return in_path

        candidates = [
            r'C:\femm42\bin\femm.exe',
            os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'),
                         'femm42', 'bin', 'femm.exe'),
            os.path.join(os.environ.get('ProgramFiles(x86)',
                                        r'C:\Program Files (x86)'),
                         'femm42', 'bin', 'femm.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''),
                         'Programs', 'femm42', 'bin', 'femm.exe'),
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate

        return None

    @staticmethod
    def _parse_validation_results(results_path):
        """Parse the key=value FEMM validation output file."""
        metrics = {}
        with open(results_path, 'r', encoding='utf-8') as results_file:
            for raw_line in results_file:
                line = raw_line.strip()
                if not line or '=' not in line:
                    continue

                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                try:
                    metrics[key] = float(value)
                except ValueError:
                    metrics[key] = value
        return metrics

    def _compute_airgap_reference_metrics(self):
        """Current in-app air-gap metrics for the FEMM comparison."""
        if not self.flux_results:
            return {}

        flux_densities = self.flux_results.get('flux_densities', {})
        branch_fluxes = self.flux_results.get('branch_fluxes', {})

        br_values = []
        flux_values = []
        for element_id, density_data in flux_densities.items():
            if density_data.get('element_data', {}).get('material') != 'Air Gap':
                continue

            br_values.append(abs(float(density_data.get('Br', 0.0))))
            branch_data = branch_fluxes.get(element_id, {})
            for direction in ('up', 'down', 'left', 'right'):
                flux_values.append(abs(float(branch_data.get(direction, 0.0))))

        if not br_values and not flux_values:
            return {}

        metrics = self._abs_metrics(br_values, flux_values)
        return {
            'airgap_br_max_t': metrics['br_max'],
            'airgap_br_avg_excited_t': metrics['br_avg_excited'],
            'airgap_flux_max_wb': metrics['flux_max'],
            'airgap_flux_avg_excited_wb': metrics['flux_avg_excited'],
        }

    def _run_femm_script(self, lua_path):
        """Execute the validation Lua script via the femm module or femm.exe.

        Returns the backend name that succeeded; raises when neither works.
        """
        import_failure = None
        femm_module = None
        try:
            import femm as femm_module  # type: ignore

            femm_module.openfemm()
            lua_for_femm = lua_path.replace('\\', '/')
            if not hasattr(femm_module, 'callfemm'):
                raise RuntimeError(
                    'Installed femm module does not expose callfemm.')
            femm_module.callfemm(f'dofile("{lua_for_femm}")')
            return 'python-femm'
        except Exception as femm_error:
            import_failure = femm_error
        finally:
            if femm_module is not None and hasattr(femm_module, 'closefemm'):
                try:
                    femm_module.closefemm()
                except Exception:
                    pass

        femm_exe = self._locate_femm_executable()
        if femm_exe is None:
            raise RuntimeError(
                'Could not run FEMM: Python femm module is unavailable and '
                'femm.exe was not found.') from import_failure

        subprocess.run(
            [femm_exe, f'-lua-script={lua_path}', '-windowhide'],
            cwd=str(PROJECT_ROOT), check=True, timeout=FEMM_RUN_TIMEOUT_S)
        return 'femm-exe'

    def run_femm_validation(self):
        """Run the FEMM validation and report metrics next to local results."""
        window = self.main_window
        try:
            lua_path = str(FEMM_VALIDATION_SCRIPT)
            results_path = str(FEMM_VALIDATION_RESULTS)

            if not os.path.isfile(lua_path):
                self._set_status('FEMM validation script not found.', 'error')
                QMessageBox.warning(window, 'Validation using FEMM',
                                    f'Missing script:\n{lua_path}')
                return

            if os.path.isfile(results_path):
                try:
                    os.remove(results_path)
                except OSError:
                    pass

            self._set_status('Running FEMM validation...')
            QApplication.processEvents()

            run_source = self._run_femm_script(lua_path)

            if not os.path.isfile(results_path):
                raise RuntimeError(
                    'FEMM finished but validation_results.txt was not generated.')

            femm_metrics = self._parse_validation_results(results_path)
            local_metrics = self._compute_airgap_reference_metrics()

            summary_lines = [
                f'Run backend: {run_source}',
                f'Br max (FEMM): {femm_metrics.get("airgap_br_max_t", 0.0):.6e} T',
                f'Br avg excited (FEMM): '
                f'{femm_metrics.get("airgap_br_avg_excited_t", 0.0):.6e} T',
                f'Flux max (FEMM): '
                f'{femm_metrics.get("airgap_flux_max_wb", 0.0):.6e} Wb',
                f'Flux avg excited (FEMM): '
                f'{femm_metrics.get("airgap_flux_avg_excited_wb", 0.0):.6e} Wb',
            ]

            if local_metrics:
                summary_lines.extend([
                    '',
                    f'Br max (Current Model): '
                    f'{local_metrics.get("airgap_br_max_t", 0.0):.6e} T',
                    f'Br avg excited (Current Model): '
                    f'{local_metrics.get("airgap_br_avg_excited_t", 0.0):.6e} T',
                    f'Flux max (Current Model): '
                    f'{local_metrics.get("airgap_flux_max_wb", 0.0):.6e} Wb',
                    f'Flux avg excited (Current Model): '
                    f'{local_metrics.get("airgap_flux_avg_excited_wb", 0.0):.6e} Wb',
                ])

            self._set_status(
                'FEMM validation completed successfully.', 'success')
            QMessageBox.information(window, 'Validation using FEMM',
                                    '\n'.join(summary_lines))

        except subprocess.TimeoutExpired:
            self._set_status('FEMM validation timed out.', 'error')
            QMessageBox.critical(window, 'Validation using FEMM',
                                 'FEMM validation timed out.')
        except Exception as error:
            self._set_status(f'FEMM validation failed: {error}', 'error')
            QMessageBox.critical(window, 'Validation using FEMM',
                                 f'Validation failed:\n{error}')
