"""Automatically prepared field animation, results and FEMM comparison."""

import csv
from copy import deepcopy
import time
import json
import logging
from datetime import datetime
from uuid import uuid4

import numpy as np
from PyQt6.QtCore import QProcess, QTimer, Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QSizePolicy, QSpinBox, QTabWidget, QVBoxLayout,
                             QWidget)

from core.femm_runner import parse_validation_results
from core.femm_validation import (airgap_profile, airgap_samples,
                                  build_validation_script, compare_airgap_profiles,
                                  compute_reference_metrics)
from ui.theme import (FLUX_DENSITY_PAGE_STYLE, PAGE_SUBTITLE_STYLE,
                      PAGE_TITLE_STYLE, set_status)
from utils.constants import (DEFAULT_AXIAL_LENGTH_MM, DEFAULT_CONTOUR_COUNT,
                             DEFAULT_RELATIVE_PERMEABILITIES)
from utils.paths import FEMM_VALIDATION_DIR, PROJECT_ROOT, femm_worker_command

import pyqtgraph as pg
from ui.field_animation import AnimationPreparation, FieldAnimationView

pg.setConfigOptions(imageAxisOrder='row-major')

logger = logging.getLogger(__name__)

EXCITED_EPSILON = 1e-12

VISUALISATION_MODES = ("B Heatmap", "Flux Lines", "Flux Line + Density")
ANALYSIS_REGIONS = ("Air Gap", "Rotor Core", "Tooth", "Stator Core", "Slot")

FEMM_RUN_TIMEOUT_S = 300


class FluxDensityHeatmapUI:
    """One prepared model shared by playback, statistics and validation."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.reluctance_results = None
        self.mmf_results = None
        self.flux_results = None
        self.femm_process = None
        self._femm_run = None

        self.animation_span_degrees = 360.0
        self.animation_mode = VISUALISATION_MODES[2]
        self.pyqtgraph_available = True
        self.animation_model = None
        self._animation_worker = None
        self._cached_animation_signature = None
        self._animation_angle = 0.0
        self._prepare_pending = False
        self._play_when_ready = False
        self._closing = False
        self._auto_prepare_timer = QTimer(main_window)
        self._auto_prepare_timer.setSingleShot(True)
        self._auto_prepare_timer.timeout.connect(self.prepare_animation_frames)

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
        panel = QVBoxLayout()
        panel.setContentsMargins(4, 4, 8, 4)
        panel.setSpacing(12)
        title = QLabel("Field animation")
        title.setStyleSheet(PAGE_TITLE_STYLE)
        panel.addWidget(title)
        subtitle = QLabel("The field prepares automatically after meshing. Press Play when ready.")
        subtitle.setStyleSheet(PAGE_SUBTITLE_STYLE)
        subtitle.setWordWrap(True)
        panel.addWidget(subtitle)

        window.flux_progress_bar = QProgressBar()
        window.flux_progress_bar.setVisible(False)
        panel.addWidget(window.flux_progress_bar)
        window.flux_status_label = QLabel("")
        window.flux_status_label.setWordWrap(True)
        set_status(window.flux_status_label, "Generate a mesh to prepare the field.", 'muted')
        panel.addWidget(window.flux_status_label)
        window.flux_contour_label = QLabel("Arrows follow B: N to S across the air gap.")
        window.flux_contour_label.setWordWrap(True)
        window.flux_contour_label.setStyleSheet(PAGE_SUBTITLE_STYLE)
        panel.addWidget(window.flux_contour_label)

        window.flux_tabs = QTabWidget()
        window.flux_tabs.addTab(self._create_animation_tab(), "Playback")
        window.flux_tabs.addTab(self._create_material_properties_tab(), "Materials")
        window.flux_tabs.addTab(self._create_analysis_statistics_tab(), "Statistics")
        window.flux_tabs.currentChanged.connect(self._analysis_tab_changed)
        window.flux_tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        panel.addWidget(window.flux_tabs, 1)
        actions = QHBoxLayout()
        window.flux_export_all_btn = QPushButton("Export results")
        window.flux_export_all_btn.clicked.connect(self.export_all_results)
        window.flux_export_all_btn.setEnabled(False)
        window.flux_femm_validation_btn = QPushButton("Validate in FEMM")
        window.flux_femm_validation_btn.clicked.connect(self.run_femm_validation)
        window.flux_femm_validation_btn.setEnabled(False)
        actions.addWidget(window.flux_export_all_btn)
        actions.addWidget(window.flux_femm_validation_btn)
        panel.addLayout(actions)
        return panel

    def _build_right_panel(self, parent_widget):
        window = self.main_window
        panel = QVBoxLayout()
        panel.setContentsMargins(12, 12, 12, 10)
        panel.setSpacing(8)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Display"))
        window.flux_visualization_type = QComboBox()
        window.flux_visualization_type.addItems(VISUALISATION_MODES)
        window.flux_visualization_type.setCurrentIndex(2)
        window.flux_anim_visualization_type = window.flux_visualization_type
        window.flux_visualization_type.currentTextChanged.connect(self._refresh_animation_display)
        controls.addWidget(window.flux_visualization_type)
        controls.addStretch()
        window.flux_show_arrows_check = QCheckBox("Show arrows")
        window.flux_show_arrows_check.setChecked(True)
        window.flux_show_arrows_check.toggled.connect(self._toggle_arrows)
        controls.addWidget(window.flux_show_arrows_check)
        controls.addWidget(QLabel("Contours"))
        window.flux_contour_count = QSpinBox()
        window.flux_contour_count.setRange(4, 100)
        window.flux_contour_count.setValue(DEFAULT_CONTOUR_COUNT)
        window.flux_contour_count.setFixedWidth(78)
        window.flux_contour_count.valueChanged.connect(self._refresh_animation_display)
        controls.addWidget(window.flux_contour_count)
        panel.addLayout(controls)
        window.flux_anim_pg_widget = FieldAnimationView()
        window.flux_anim_pg_plot = window.flux_anim_pg_widget.plot
        window.flux_anim_pg_image_item = window.flux_anim_pg_widget.image
        window.flux_anim_pg_widget.scene().sigMouseClicked.connect(self._inspect_field_point)
        panel.addWidget(window.flux_anim_pg_widget, 1)
        window.flux_probe_label = QLabel("Click the field to inspect flux density.")
        window.flux_probe_label.setWordWrap(True)
        window.flux_probe_label.setStyleSheet(PAGE_SUBTITLE_STYLE)
        panel.addWidget(window.flux_probe_label)
        card = QWidget()
        card.setObjectName('fieldViewCard')
        card.setStyleSheet('QWidget#fieldViewCard { background: #1e1e1e; border: 1px solid #353535; border-radius: 10px; }')
        card.setLayout(panel)
        return card

    def _refresh_animation_display(self, *_):
        window = self.main_window
        mode = window.flux_visualization_type.currentText()
        window.flux_contour_count.setEnabled(mode != 'B Heatmap')
        window.flux_show_arrows_check.setEnabled(mode != 'B Heatmap')
        window.flux_anim_symmetry_check.setEnabled(mode == 'B Heatmap')
        if self.animation_model is not None:
            self.animation_mode = mode
            self.animation_span_degrees = self._get_animation_span_degrees()
            self._animation_angle %= self.animation_span_degrees
            self._playback_start_angle = self._animation_angle
            self._playback_start_time = time.perf_counter()
            view = window.flux_anim_pg_widget
            view.set_model(self.animation_model, mode, window.flux_contour_count.value())
            view.set_arrows_visible(window.flux_show_arrows_check.isChecked())
            self._render_animation_angle(self._animation_angle)

    def _toggle_arrows(self, visible):
        self.main_window.flux_anim_pg_widget.set_arrows_visible(visible)

    def _analysis_tab_changed(self, index):
        if index == 2 and self.animation_model is not None:
            self.pause_animation(sync_results=False)
            self._sync_field_results(self._animation_angle)

    def _inspect_field_point(self, event):
        window = self.main_window
        view = window.flux_anim_pg_widget
        if (self.animation_model is None or event.button() != Qt.MouseButton.LeftButton
                or not view.plot.sceneBoundingRect().contains(event.scenePos())):
            return
        point = view.plot.vb.mapSceneToView(event.scenePos())
        radius = float(np.hypot(point.x(), point.y()))
        angle = float(np.degrees(np.arctan2(point.y(), point.x())) % 360)
        field = self.animation_model.field_at(self._animation_angle)
        for index, element in enumerate(self._mesh_data()['mesh_elements']):
            if (element['rin'] <= radius <= element['rout']
                    and element['theta_start'] <= angle < element['theta_end']):
                br, bt = field[index]
                window.flux_probe_label.setText(
                    f"r {radius:.2f} mm | theta {angle:.1f} deg | "
                    f"|B| {np.hypot(br, bt):.4f} T | Br {br:.4f} T | Bt {bt:.4f} T")
                view.probe.setData([point.x()], [point.y()])
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
        settings = QFormLayout()
        settings.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        window.flux_anim_angle_step_spin = QSpinBox()
        window.flux_anim_angle_step_spin.setRange(1, 30)
        window.flux_anim_angle_step_spin.setValue(1)
        window.flux_anim_angle_step_spin.setSuffix(" deg")
        window.flux_anim_angle_step_spin.valueChanged.connect(self._update_animation_interval)
        settings.addRow("Angle step", window.flux_anim_angle_step_spin)
        window.flux_anim_interval_spin = QSpinBox()
        window.flux_anim_interval_spin.setRange(8, 1000)
        window.flux_anim_interval_spin.setValue(16)
        window.flux_anim_interval_spin.setSuffix(" ms")
        window.flux_anim_interval_spin.valueChanged.connect(self._update_animation_interval)
        settings.addRow("Frame time", window.flux_anim_interval_spin)
        window.flux_anim_symmetry_check = QCheckBox("Short heatmap loop (180 deg)")
        window.flux_anim_symmetry_check.setChecked(True)
        window.flux_anim_symmetry_check.setEnabled(False)
        window.flux_anim_symmetry_check.toggled.connect(self._refresh_animation_display)
        settings.addRow("", window.flux_anim_symmetry_check)
        layout.addLayout(settings)
        window.flux_anim_info_label = QLabel("The field will prepare automatically.")
        window.flux_anim_info_label.setWordWrap(True)
        window.flux_anim_info_label.setStyleSheet(PAGE_SUBTITLE_STYLE)
        layout.addWidget(window.flux_anim_info_label)
        buttons = QHBoxLayout()
        window.flux_play_anim_btn = QPushButton("Play")
        window.flux_play_anim_btn.setObjectName('primaryButton')
        window.flux_play_anim_btn.clicked.connect(self.toggle_animation)
        window.flux_play_anim_btn.setEnabled(False)
        buttons.addWidget(window.flux_play_anim_btn)
        layout.addLayout(buttons)
        layout.addStretch()
        return tab


    # -------------------------------------------------------------- pipeline

    def _mesh_data(self):
        meshing_page = getattr(self.main_window, 'meshing_page_ui', None)
        return meshing_page.mesh_data if meshing_page else None

    def _mmf_engine(self):
        connection_tab = getattr(self.main_window, 'connection_tab', None)
        return connection_tab.mmf_calculator if connection_tab else None

    def flux_calculate(self):
        """Use the prepared field at the configured angle without another solve."""
        if self.animation_model is not None:
            self.pause_animation(sync_results=False)
            self._render_animation_angle(self._mmf_engine().wt_angle_deg)
            self._sync_field_results(self._mmf_engine().wt_angle_deg)
        else:
            self.prepare_animation_frames()

    def _sync_field_results(self, angle):
        if self.animation_model is None:
            return
        self.flux_results = self.animation_model.solution_at(angle)
        self.reluctance_results = self.animation_model.reluctance_results
        self.mmf_results = self.animation_model.mmf_results
        self.update_regional_statistics()
        self.update_flux_statistics()


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
        self.pause_animation(sync_results=False)
        if self.animation_model is not None:
            self._sync_field_results(self._animation_angle)
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

    # -------------------------------------------------------------- animation

    def generate_visualisation(self):
        """Update the live view without drawing a separate static figure."""
        self._refresh_animation_display()

    def _get_animation_span_degrees(self):
        # Wt is ELECTRICAL: its period does not depend on the pole-pair count.
        window = self.main_window
        heatmap = window.flux_anim_visualization_type.currentText() == 'B Heatmap'
        return 180.0 if heatmap and window.flux_anim_symmetry_check.isChecked() else 360.0

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
                      window.flux_num_slots, window.flux_slot_angle, window.flux_slot_height):
            field.textChanged.connect(self._geometry_changed)
        for field in (window.flux_ur_stator, window.flux_ur_rotor, window.flux_calc_axial_length):
            field.textChanged.connect(self.invalidate_animation)
        for control in (window.phases_spin, window.slots_spin, window.poles_spin, window.span_spin,
                        window.connection_tab.turns_spin, window.connection_tab.current_spin):
            control.valueChanged.connect(self.invalidate_animation)
        window.single_layer.toggled.connect(self.invalidate_animation)

    def _geometry_changed(self, *_):
        self.invalidate_animation()
        self._prepare_pending = False
        self._auto_prepare_timer.stop()
        self.main_window.flux_anim_pg_widget.clear_model('Generate a new mesh for this geometry.')

    def invalidate_animation(self, *_):
        self.pause_animation(sync_results=False)
        self.animation_model = None
        self.flux_results = self.reluctance_results = self.mmf_results = None
        self._cached_animation_signature = None
        self._prepare_pending = bool(self._mesh_data()) and not self._closing
        self._auto_prepare_timer.stop()
        if self._animation_worker is not None:
            self._animation_worker.requestInterruption()
        window = self.main_window
        window.flux_export_all_btn.setEnabled(False)
        window.flux_femm_validation_btn.setEnabled(False)
        window.flux_play_anim_btn.setEnabled(self._prepare_pending)
        window.flux_anim_pg_widget.clear_model(
            'Preparing field...' if self._prepare_pending else 'Generate a mesh to prepare the field.')
        window.flux_anim_info_label.setText('Field preparation runs automatically in the background.')
        if self._prepare_pending:
            self._set_status('Preparing the updated field...')
            self._auto_prepare_timer.start(180)
        else:
            self._play_when_ready = False
            self._set_status('Generate a mesh to prepare the field.', 'muted')

    def _update_animation_interval(self):
        if self.animation_timer.isActive():
            self._playback_start_angle = self._animation_angle
            self._playback_start_time = time.perf_counter()
            self.animation_timer.setInterval(self.main_window.flux_anim_interval_spin.value())

    def prepare_animation_frames(self):
        """Prepare the current model once; repeated requests join the same job."""
        window = self.main_window
        if self._closing or not self._mesh_data():
            self._prepare_pending = False
            return
        mesh = self._mesh_data()
        current = window.meshing_page_ui.get_machine_parameters()
        matrix = getattr(self._mmf_engine(), 'matrix', None)
        if (mesh['params'] != current or matrix is None
                or matrix.shape[1] != current['num_slots']):
            self._prepare_pending = False
            return
        signature = self._animation_input_signature()
        if self.animation_model is not None and signature == self._cached_animation_signature:
            self._prepare_pending = False
            if self._play_when_ready:
                self.play_animation()
            return
        self._prepare_pending = True
        if self._animation_worker is not None:
            return
        self._auto_prepare_timer.stop()
        try:
            materials = {'ur_stator': float(window.flux_ur_stator.text()),
                         'ur_rotor': float(window.flux_ur_rotor.text()),
                         'ur_air': DEFAULT_RELATIVE_PERMEABILITIES['ur_air']}
            length = float(window.flux_calc_axial_length.text())
            if length <= 0 or not np.isfinite(length) or any(
                    value <= 0 or not np.isfinite(value) for value in materials.values()):
                raise ValueError('Material permeabilities and axial length must be positive.')
            # Workers receive snapshots; live Qt controls are never read off-thread.
            worker = AnimationPreparation(
                window, mesh=deepcopy(self._mesh_data()), engine=deepcopy(self._mmf_engine()),
                materials=materials, axial_length_mm=length,
                mesh_settings=dict(window.meshing_page_ui.get_current_mesh_settings()),
                resolution=int(np.clip(window.flux_anim_pg_widget.height(), 480, 800)))
            worker.input_signature = signature
            self._animation_worker = worker
            self._prepare_pending = False
            worker.progress.connect(self._animation_progress)
            worker.prepared.connect(self._animation_prepared)
            worker.failed.connect(self._animation_failed)
            worker.finished.connect(self._animation_worker_finished)
            window.flux_progress_bar.setVisible(True)
            window.flux_progress_bar.setValue(0)
            window.flux_play_anim_btn.setEnabled(True)
            worker.start()
        except Exception as error:
            self._prepare_pending = False
            self._play_when_ready = False
            window.flux_play_anim_btn.setText('Play')
            self._set_status(f'Check field settings: {error}', 'warning')

    def _animation_progress(self, percent, message):
        worker = self._animation_worker
        if worker is not None and not worker.isInterruptionRequested():
            self.main_window.flux_progress_bar.setValue(percent)
            self._set_status(message)

    def _animation_prepared(self, model):
        worker = self._animation_worker
        if (worker is None or worker.isInterruptionRequested() or self._closing
                or worker.input_signature != self._animation_input_signature()):
            return
        self.animation_model = model
        self._cached_animation_signature = worker.input_signature
        self.reluctance_results = model.reluctance_results
        self.mmf_results = model.mmf_results
        self.flux_results = model.initial_solution
        self.update_regional_statistics()
        self.update_flux_statistics()
        self._activate_animation_model(model)

    def _activate_animation_model(self, model):
        window = self.main_window
        self._animation_angle = float(self._mmf_engine().wt_angle_deg)
        self._refresh_animation_display()
        window.flux_export_all_btn.setEnabled(True)
        window.flux_femm_validation_btn.setEnabled(True)
        window.flux_play_anim_btn.setEnabled(True)
        window.flux_play_anim_btn.setText('Play')
        window.flux_anim_pg_widget.probe.clear()
        self._set_status(f'Field ready in {model.generation_seconds:.2f} s. Press Play.', 'success')
        if self._play_when_ready:
            self.play_animation()

    def _animation_failed(self, message):
        worker = self._animation_worker
        if worker is not None and not worker.isInterruptionRequested() and not self._closing:
            self._play_when_ready = False
            self.main_window.flux_play_anim_btn.setText('Play')
            self._set_status(f'Field preparation failed: {message}', 'warning')

    def _animation_worker_finished(self):
        worker = self._animation_worker
        self._animation_worker = None
        self.main_window.flux_progress_bar.setVisible(False)
        if worker is not None:
            worker.deleteLater()
        if self._prepare_pending and self._mesh_data() and not self._closing:
            self._auto_prepare_timer.start(0)

    def _render_animation_angle(self, angle):
        self._animation_angle = angle
        self.main_window.flux_anim_pg_widget.show_angle(angle)
        self.main_window.flux_anim_info_label.setText(
            f'Wt={angle:.1f} deg | {self.animation_span_degrees:.0f} deg loop')

    def _advance_animation_frame(self):
        if self.animation_model is None:
            self.pause_animation(sync_results=False)
            return
        elapsed_ms = (time.perf_counter() - self._playback_start_time) * 1000
        window = self.main_window
        angle = (self._playback_start_angle + elapsed_ms * window.flux_anim_angle_step_spin.value()
                 / window.flux_anim_interval_spin.value()) % self.animation_span_degrees
        self._render_animation_angle(angle)

    def toggle_animation(self):
        if self.animation_timer.isActive() or self._play_when_ready:
            self.pause_animation()
        else:
            self.play_animation()

    def play_animation(self):
        if self.animation_model is None:
            if self._mesh_data():
                self._play_when_ready = True
                self.main_window.flux_play_anim_btn.setText('Pause')
                self.main_window.flux_play_anim_btn.setEnabled(True)
                self._set_status('Preparing the field. Playback will start when ready.')
                self.prepare_animation_frames()
            return
        self._play_when_ready = False
        self._playback_start_time = time.perf_counter()
        self._playback_start_angle = self._animation_angle
        self.animation_timer.start(self.main_window.flux_anim_interval_spin.value())
        self.main_window.flux_play_anim_btn.setText('Pause')
        self.main_window.flux_play_anim_btn.setEnabled(True)
        self._set_status('Animation playing...')

    def pause_animation(self, *, sync_results=True):
        was_running = self.animation_timer.isActive()
        was_queued = self._play_when_ready
        self.animation_timer.stop()
        self._play_when_ready = False
        if hasattr(self.main_window, 'flux_play_anim_btn'):
            self.main_window.flux_play_anim_btn.setText('Play')
            self.main_window.flux_play_anim_btn.setEnabled(
                self.animation_model is not None or bool(self._mesh_data()))
        if was_running:
            if sync_results and self.animation_model is not None:
                self._sync_field_results(self._animation_angle)
            self._set_status('Animation paused.', 'muted')
        elif was_queued:
            self._set_status('Playback paused. Field preparation continues.', 'muted')

    def stop_animation(self):
        self.pause_animation(sync_results=False)
        if self.animation_model is not None:
            self._render_animation_angle(0.0)
            self._sync_field_results(0.0)
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
