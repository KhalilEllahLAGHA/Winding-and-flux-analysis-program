"""Step 2: meshing configuration page (formerly ``Meshing_Page_UI.py``).

Fixes a bug from the original file where ``update_mesh_visualization`` was
defined twice: the duplicate silently disabled mesh invalidation, so stale
meshes survived machine-parameter changes. The two roles are now explicit:
``invalidate_mesh`` (parameters changed) and ``refresh_visualization``
(page redisplayed).
"""

import csv
import json
import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (QApplication, QComboBox, QFileDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QProgressBar,
                             QPushButton, QSpinBox, QTabWidget, QTextEdit,
                             QVBoxLayout, QWidget)

from core.meshing_engine import MeshingEngine
from ui.machine_drawer import MachineDrawer
from ui.theme import (MESHING_PAGE_STYLE, PAGE_SUBTITLE_STYLE,
                      PAGE_TITLE_STYLE, SECTION_LABEL_STYLE, set_status)
from utils.constants import (DEFAULT_MACHINE_PARAMS, DEFAULT_MESH_PRESET_INDEX,
                             MESH_PRESETS)
from utils.safe_eval import parse_float_field, parse_int_field

logger = logging.getLogger(__name__)

REDRAW_DEBOUNCE_MS = 300
MESH_OVERLAY_LINEWIDTH = 0.3
MESH_OVERLAY_ALPHA = 0.7


class MeshingPageUI:
    """Mesh settings (presets + manual), generation, preview, and export."""

    def __init__(self, main_window):
        self.main_window = main_window
        self.meshing_engine = MeshingEngine()
        self.mesh_data = None

    def create_meshing_widget(self):
        widget = QWidget()
        widget.setStyleSheet(MESHING_PAGE_STYLE)

        main_layout = QHBoxLayout(widget)
        main_layout.addLayout(self._build_settings_panel(), 3)
        main_layout.addWidget(self._build_visualization_panel(widget), 5)

        return widget

    # ------------------------------------------------------------- UI setup

    def _build_settings_panel(self):
        window = self.main_window
        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(4, 4, 8, 4)
        left_panel.setSpacing(12)

        title = QLabel("Step 2: Meshing Configuration")
        title.setStyleSheet(PAGE_TITLE_STYLE)
        left_panel.addWidget(title)

        subtitle = QLabel("Pick a quality preset (or tune the layers "
                          "manually), then generate the mesh to continue.")
        subtitle.setStyleSheet(PAGE_SUBTITLE_STYLE)
        subtitle.setWordWrap(True)
        left_panel.addWidget(subtitle)

        window.mesh_tabs = QTabWidget()
        window.mesh_tabs.addTab(self._create_basic_settings_tab(), "Basic Settings")
        window.mesh_tabs.addTab(self._create_advanced_settings_tab(),
                                "Advanced Settings")
        left_panel.addWidget(window.mesh_tabs)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        window.generate_mesh_btn = QPushButton("Generate Mesh")
        window.generate_mesh_btn.setObjectName("primaryButton")
        window.generate_mesh_btn.setMinimumHeight(40)
        window.generate_mesh_btn.setToolTip(
            "Build the polar mesh from the Step 1 machine parameters.")
        window.generate_mesh_btn.clicked.connect(self.generate_mesh)
        button_layout.addWidget(window.generate_mesh_btn)

        window.export_mesh_btn = QPushButton("Export Mesh Data")
        window.export_mesh_btn.setMinimumHeight(40)
        window.export_mesh_btn.setToolTip(
            "Save the generated mesh as Excel, CSV, or JSON.")
        window.export_mesh_btn.clicked.connect(self.export_mesh_data)
        window.export_mesh_btn.setEnabled(False)
        button_layout.addWidget(window.export_mesh_btn)

        left_panel.addLayout(button_layout)

        window.mesh_progress = QProgressBar()
        window.mesh_progress.setVisible(False)
        left_panel.addWidget(window.mesh_progress)

        window.mesh_status = QLabel("")
        set_status(window.mesh_status, "", 'muted')
        left_panel.addWidget(window.mesh_status)

        log_label = QLabel("GENERATION LOG")
        log_label.setStyleSheet(SECTION_LABEL_STYLE)
        left_panel.addWidget(log_label)

        window.mesh_log = QTextEdit()
        window.mesh_log.setMaximumHeight(110)
        window.mesh_log.setReadOnly(True)
        window.mesh_log.setPlainText("Mesh generation log will appear here...")
        left_panel.addWidget(window.mesh_log)

        return left_panel

    def _create_basic_settings_tab(self):
        window = self.main_window
        tab = QWidget()
        layout = QVBoxLayout(tab)

        preset_group = QGroupBox("Mesh Quality Presets")
        preset_layout = QFormLayout(preset_group)

        window.mesh_preset = QComboBox()
        window.mesh_preset.addItems([
            "Low Precision (Fast Calculation)",
            "Mid Precision (Recommended)",
            "High Precision (Slow Calculation)",
        ])
        window.mesh_preset.setCurrentIndex(DEFAULT_MESH_PRESET_INDEX)
        window.mesh_preset.currentIndexChanged.connect(self.apply_preset)
        preset_layout.addRow("Quality Preset:", window.mesh_preset)
        layout.addWidget(preset_group)

        settings_group = QGroupBox("Current Settings")
        settings_layout = QFormLayout(settings_group)

        window.preset_rotor_layers = QLabel()
        window.preset_slot_layers = QLabel()
        window.preset_airgap_layers = QLabel()
        window.preset_stator_layers = QLabel()
        window.preset_angle_divider = QLabel()

        settings_layout.addRow("Rotor Core Layers:", window.preset_rotor_layers)
        settings_layout.addRow("Slot/Tooth Layers:", window.preset_slot_layers)
        settings_layout.addRow("Air Gap Layers:", window.preset_airgap_layers)
        settings_layout.addRow("Stator Yoke Layers:", window.preset_stator_layers)
        settings_layout.addRow("Angle Divider:", window.preset_angle_divider)

        layout.addWidget(settings_group)
        layout.addStretch()

        self.apply_preset(DEFAULT_MESH_PRESET_INDEX)
        return tab

    def _create_advanced_settings_tab(self):
        window = self.main_window
        tab = QWidget()
        layout = QVBoxLayout(tab)

        manual_group = QGroupBox("Manual Configuration")
        manual_layout = QFormLayout(manual_group)

        window.manual_rotor_layers = _layer_spin_box(maximum=50)
        window.manual_slot_layers = _layer_spin_box(maximum=50)
        window.manual_airgap_layers = _layer_spin_box(maximum=100)
        window.manual_stator_layers = _layer_spin_box(maximum=50)

        window.manual_angle_divider = _layer_spin_box(maximum=50)
        window.manual_angle_divider.setToolTip(
            "Higher values create finer angular mesh (more elements)")

        manual_layout.addRow("Rotor Core Layers:", window.manual_rotor_layers)
        manual_layout.addRow("Slot/Tooth Layers:", window.manual_slot_layers)
        manual_layout.addRow("Air Gap Layers:", window.manual_airgap_layers)
        manual_layout.addRow("Stator Yoke Layers:", window.manual_stator_layers)
        manual_layout.addRow("Angle Divider:", window.manual_angle_divider)

        layout.addWidget(manual_group)

        reset_btn = QPushButton("RESET")
        reset_btn.clicked.connect(self.reset_to_default)
        reset_btn.setMinimumHeight(35)
        layout.addWidget(reset_btn)

        layout.addStretch()
        return tab

    def _build_visualization_panel(self, parent_widget):
        window = self.main_window

        window.mesh_figure, window.mesh_ax = plt.subplots(figsize=(8, 8))
        window.mesh_figure.patch.set_facecolor('white')
        window.mesh_ax.set_facecolor('white')
        window.mesh_figure.set_tight_layout(True)

        window.mesh_canvas = FigureCanvas(window.mesh_figure)
        window.mesh_machine_drawer = MachineDrawer(window.mesh_figure,
                                                   window.mesh_ax)

        self._connect_to_machine_parameters()
        window.meshing_page_ui = self
        self.draw_base_machine()

        right_panel = QVBoxLayout()
        window.mesh_toolbar = NavigationToolbar(window.mesh_canvas, parent_widget)
        right_panel.addWidget(window.mesh_toolbar)
        right_panel.addWidget(window.mesh_canvas)

        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        return right_widget

    def _connect_to_machine_parameters(self):
        """Invalidate the mesh (debounced) when machine parameters change."""
        window = self.main_window
        if not hasattr(window, 'flux_stator_rout'):
            return

        input_fields = [
            window.flux_stator_rout, window.flux_stator_rin,
            window.flux_num_slots, window.flux_slot_angle,
            window.flux_slot_height, window.flux_air_gap_thickness,
            window.flux_shaft_radius, window.flux_num_pair_poles,
        ]
        for field in input_fields:
            field.textChanged.connect(self._on_machine_params_changed)

    def _on_machine_params_changed(self):
        window = self.main_window
        if not hasattr(window, 'mesh_redraw_timer'):
            window.mesh_redraw_timer = QTimer()
            window.mesh_redraw_timer.setSingleShot(True)
            window.mesh_redraw_timer.timeout.connect(self.invalidate_mesh)

        window.mesh_redraw_timer.stop()
        window.mesh_redraw_timer.start(REDRAW_DEBOUNCE_MS)

    # ------------------------------------------------------------- settings

    def apply_preset(self, index):
        """Show the preset values in the read-only labels."""
        window = self.main_window
        preset = MESH_PRESETS[index]

        window.preset_rotor_layers.setText(str(preset["rotor"]))
        window.preset_slot_layers.setText(str(preset["slot"]))
        window.preset_airgap_layers.setText(str(preset["airgap"]))
        window.preset_stator_layers.setText(str(preset["stator"]))
        window.preset_angle_divider.setText(str(preset["angle_divider"]))

    def reset_to_default(self):
        """Reset all manual layer settings to 1."""
        window = self.main_window
        for spin in (window.manual_rotor_layers, window.manual_slot_layers,
                     window.manual_airgap_layers, window.manual_stator_layers,
                     window.manual_angle_divider):
            spin.setValue(1)

    def get_current_mesh_settings(self):
        """Mesh settings from the active tab (preset or manual)."""
        window = self.main_window
        if window.mesh_tabs.currentIndex() == 0:
            return MESH_PRESETS[window.mesh_preset.currentIndex()]

        return {
            "rotor": window.manual_rotor_layers.value(),
            "slot": window.manual_slot_layers.value(),
            "airgap": window.manual_airgap_layers.value(),
            "stator": window.manual_stator_layers.value(),
            "quality": "custom",
            "angle_divider": window.manual_angle_divider.value(),
        }

    def get_machine_parameters(self):
        """Machine parameters from the Step 1 inputs, with safe fallbacks."""
        window = self.main_window
        defaults = DEFAULT_MACHINE_PARAMS

        try:
            params = {
                'stator_outer_radius': parse_float_field(window.flux_stator_rout.text()),
                'stator_inner_radius': parse_float_field(window.flux_stator_rin.text()),
                'air_gap': parse_float_field(window.flux_air_gap_thickness.text()),
                'shaft_radius': parse_float_field(window.flux_shaft_radius.text()),
                'num_slots': parse_int_field(window.flux_num_slots.text()),
                'slot_angle': parse_float_field(window.flux_slot_angle.text()),
                'slot_height': parse_float_field(window.flux_slot_height.text()),
            }
        except Exception as error:
            logger.error("Error reading machine parameters: %s", error)
            return dict(defaults)

        # Fall back to defaults for any non-positive value.
        for key, default_value in defaults.items():
            if params[key] <= 0:
                params[key] = default_value

        return params

    def validate_machine_parameters(self, params):
        """Geometric sanity checks before mesh generation."""
        required = ('stator_outer_radius', 'stator_inner_radius', 'air_gap',
                    'shaft_radius', 'num_slots', 'slot_angle', 'slot_height')
        try:
            if any(key not in params or params[key] <= 0 for key in required):
                return False
            if params['stator_inner_radius'] >= params['stator_outer_radius']:
                return False
            if params['shaft_radius'] >= (params['stator_inner_radius']
                                          - params['air_gap']):
                return False
            if params['num_slots'] < 3:
                return False
            if params['slot_angle'] >= (360 / params['num_slots']):
                return False
            return True
        except (TypeError, KeyError):
            return False

    # ------------------------------------------------------------ generation

    def generate_mesh(self):
        """Generate the mesh with the current settings and draw the result."""
        window = self.main_window
        try:
            machine_params = self.get_machine_parameters()
            mesh_settings = self.get_current_mesh_settings()

            if not self.validate_machine_parameters(machine_params):
                set_status(window.mesh_status,
                           "Error: Invalid machine parameters", 'error')
                window.mesh_log.append(
                    "ERROR: Please check machine parameters in Step 1")
                return

            slot_pitch = 360 / machine_params['num_slots']
            slot_arc = machine_params['slot_angle']
            tooth_arc = slot_pitch - slot_arc

            window.generate_mesh_btn.setEnabled(False)
            window.mesh_progress.setVisible(True)
            window.mesh_progress.setValue(0)
            set_status(window.mesh_status, "Generating mesh...", 'info')
            window.mesh_log.clear()
            window.mesh_log.append("Starting mesh generation...")
            window.mesh_log.append(
                f"Machine parameters: {machine_params['num_slots']} slots, "
                f"{machine_params['stator_outer_radius']:.1f}mm outer radius")
            window.mesh_log.append(
                f"Slot arc: {slot_arc:.3f}°, Tooth arc: {tooth_arc:.3f}°")
            window.mesh_log.append(
                f"Mesh settings: {mesh_settings['quality']} quality, "
                f"angle divider: {mesh_settings['angle_divider']}")

            window.mesh_progress.setValue(20)
            QApplication.processEvents()

            self.mesh_data = self.meshing_engine.generate_mesh(
                machine_params, mesh_settings)

            window.mesh_progress.setValue(60)
            QApplication.processEvents()

            if not self.mesh_data or not self.mesh_data.get('mesh_elements'):
                raise RuntimeError("Mesh generation failed - no elements created")

            window.mesh_progress.setValue(80)
            QApplication.processEvents()

            self._log_mesh_statistics(mesh_settings, slot_arc, tooth_arc)

            window.mesh_progress.setValue(90)
            QApplication.processEvents()
            self.draw_meshed_machine()

            total_elements = len(self.mesh_data['mesh_elements'])
            window.mesh_progress.setValue(100)
            set_status(window.mesh_status,
                       f"Mesh completed! ({total_elements:,} elements)",
                       'success')
            window.export_mesh_btn.setEnabled(True)

            self._notify_navigation_changed()

        except Exception as error:
            set_status(window.mesh_status, f"Error: {error}", 'error')
            window.mesh_log.append(f"ERROR: {error}")
            logger.exception("Mesh generation error")
        finally:
            window.generate_mesh_btn.setEnabled(True)
            window.mesh_progress.setVisible(False)

    def _log_mesh_statistics(self, mesh_settings, slot_arc, tooth_arc):
        window = self.main_window
        mesh_stats = self.mesh_data.get('mesh_stats', {})
        total_elements = len(self.mesh_data['mesh_elements'])
        mesh_angle = mesh_stats.get('mesh_angle', 0)
        base_mesh_angle = mesh_stats.get('base_mesh_angle', mesh_angle)
        gcd_value = self.meshing_engine.calculate_gcd_fractional(slot_arc, tooth_arc)

        window.mesh_log.append("Mesh generation complete!")
        window.mesh_log.append(f"Total elements: {total_elements:,}")
        window.mesh_log.append(f"GCD of arcs: {gcd_value:.3f}°")
        window.mesh_log.append(f"Optimal mesh angle: {base_mesh_angle:.3f}°")
        window.mesh_log.append(
            f"Final mesh angle: {mesh_angle:.3f}° "
            f"(÷{mesh_settings['angle_divider']})")
        window.mesh_log.append(
            f"Radial divisions: {len(self.mesh_data['r_divisions'])}")
        window.mesh_log.append(
            f"Angular divisions: {len(self.mesh_data['theta_divisions'])}")

        region_counts = mesh_stats.get('region_counts', {})
        if region_counts:
            window.mesh_log.append("Element distribution by region:")
            for region, count in region_counts.items():
                percentage = (count / total_elements) * 100
                window.mesh_log.append(
                    f"  {region}: {count:,} ({percentage:.1f}%)")

    def _notify_navigation_changed(self):
        """Tell the flux viewer to refresh its Next/Previous buttons."""
        window = self.main_window
        if hasattr(window, 'update_flux_navigation'):
            window.update_flux_navigation()

    # ----------------------------------------------------------- visualization

    def invalidate_mesh(self):
        """Machine parameters changed: drop the stale mesh and redraw."""
        window = self.main_window
        self.mesh_data = None
        window.export_mesh_btn.setEnabled(False)
        self._notify_navigation_changed()

        set_status(window.mesh_status,
                   "Machine parameters changed — mesh needs regeneration.",
                   'warning')
        window.mesh_log.clear()
        window.mesh_log.append(
            "Machine parameters updated. Ready to generate new mesh...")

        self.draw_base_machine()

    def refresh_visualization(self):
        """Redraw the current state (meshed when data exists, base otherwise)."""
        if not hasattr(self.main_window, 'mesh_canvas'):
            return
        if self.mesh_data:
            self.draw_meshed_machine()
        else:
            self.draw_base_machine()

    # Backwards-compatible name used by older callers.
    update_mesh_visualization = refresh_visualization

    def draw_base_machine(self):
        """Draw the machine cross-section without mesh overlay."""
        window = self.main_window
        try:
            params = self.get_machine_parameters()
            drawer_params = {
                'stator_rout': params['stator_outer_radius'],
                'stator_rin': params['stator_inner_radius'],
                'air_gap_thickness': params['air_gap'],
                'shaft_radius': params['shaft_radius'],
                'num_slots': params['num_slots'],
                'slot_angle': params['slot_angle'],
                'slot_height': params['slot_height'],
            }
            window.mesh_machine_drawer.draw_machine(drawer_params)
            window.mesh_canvas.draw()

        except Exception as error:
            logger.error("Error drawing base machine: %s", error)
            window.mesh_ax.clear()
            window.mesh_ax.text(
                0, 0,
                f"Error drawing machine\nCheck parameter values\n{str(error)[:50]}...",
                ha='center', va='center', fontsize=12, color='red',
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#ffcccc", alpha=0.8))
            window.mesh_ax.set_xlim(-100, 100)
            window.mesh_ax.set_ylim(-100, 100)
            window.mesh_canvas.draw()

    def draw_meshed_machine(self):
        """Draw the base machine with the mesh-line overlay on top."""
        if not self.mesh_data:
            self.draw_base_machine()
            return

        try:
            self.draw_base_machine()
            self._draw_mesh_overlay(
                self.mesh_data['r_divisions'],
                self.mesh_data['theta_divisions'],
                self.mesh_data['params'])
            self.main_window.mesh_canvas.draw()

        except Exception as error:
            logger.error("Error drawing meshed machine: %s", error)
            self.draw_base_machine()

    def _draw_mesh_overlay(self, r_divisions, theta_divisions, machine_params):
        """Thin blue radial lines and red circles marking mesh divisions."""
        ax = self.main_window.mesh_ax
        inner_radius = machine_params['shaft_radius']
        outer_radius = machine_params['stator_outer_radius']

        for theta in theta_divisions[:-1]:  # skip 360° (duplicate of 0°)
            theta_rad = np.radians(theta)
            ax.plot([inner_radius * np.cos(theta_rad),
                     outer_radius * np.cos(theta_rad)],
                    [inner_radius * np.sin(theta_rad),
                     outer_radius * np.sin(theta_rad)],
                    'b-', linewidth=MESH_OVERLAY_LINEWIDTH,
                    alpha=MESH_OVERLAY_ALPHA)

        circle_angles = np.linspace(0, 2 * np.pi, 100)
        for radius in r_divisions:
            ax.plot(radius * np.cos(circle_angles),
                    radius * np.sin(circle_angles),
                    'r-', linewidth=MESH_OVERLAY_LINEWIDTH,
                    alpha=MESH_OVERLAY_ALPHA)

    # ---------------------------------------------------------------- export

    def export_mesh_data(self):
        """Export the generated mesh as Excel, CSV, or JSON."""
        if not self.mesh_data:
            return

        window = self.main_window
        try:
            filename, selected_filter = QFileDialog.getSaveFileName(
                window, "Export Mesh Data", "mesh_data",
                "Excel Files (*.xlsx);;CSV Files (*.csv);;JSON Files (*.json)")
            if not filename:
                return

            if selected_filter.startswith("Excel") or filename.lower().endswith('.xlsx'):
                self._export_to_excel(filename)
            elif selected_filter.startswith("CSV") or filename.lower().endswith('.csv'):
                self._export_to_csv(filename)
            else:
                self._export_to_json(filename)

            window.mesh_log.append(f"Mesh data exported to: {filename}")
            set_status(window.mesh_status,
                       "Mesh data exported successfully!", 'success')

        except Exception as error:
            window.mesh_log.append(f"Export error: {error}")
            set_status(window.mesh_status, f"Export failed: {error}", 'error')

    def _export_to_json(self, filename):
        export_data = {
            'mesh_summary': {
                'total_elements': len(self.mesh_data['mesh_elements']),
                'total_radial_divisions': len(self.mesh_data['r_divisions']),
                'total_angular_divisions': len(self.mesh_data['theta_divisions']),
                'mesh_angle': self.mesh_data.get('mesh_stats', {}).get('mesh_angle', 0),
            },
            'machine_parameters': self.get_machine_parameters(),
            'mesh_settings': self.get_current_mesh_settings(),
            'mesh_statistics': self.mesh_data.get('mesh_stats', {}),
            'radial_divisions': self.mesh_data['r_divisions'],
            'angular_divisions': self.mesh_data['theta_divisions'],
            'mesh_elements': self.mesh_data['mesh_elements'],
        }
        with open(filename, 'w') as json_file:
            json.dump(export_data, json_file, indent=2, default=str)

    def _export_to_csv(self, filename):
        with open(filename, 'w', newline='') as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(['Element_ID', 'Material', 'R_Inner', 'R_Outer',
                             'Theta_Start', 'Theta_End', 'Center_R',
                             'Center_Theta', 'Center_X', 'Center_Y'])

            for element in self.mesh_data['mesh_elements']:
                writer.writerow([
                    element.get('element_id', ''),
                    element['material'],
                    element['rin'],
                    element['rout'],
                    element['theta_start'],
                    element['theta_end'],
                    element.get('center_r', ''),
                    element.get('center_theta', ''),
                    element.get('center_x', ''),
                    element.get('center_y', ''),
                ])

            writer.writerow([])
            writer.writerow(['MESH SUMMARY'])
            writer.writerow(['Total Elements', len(self.mesh_data['mesh_elements'])])
            writer.writerow(['Radial Divisions', len(self.mesh_data['r_divisions'])])
            writer.writerow(['Angular Divisions', len(self.mesh_data['theta_divisions'])])

            mesh_stats = self.mesh_data.get('mesh_stats', {})
            if mesh_stats:
                writer.writerow(['Mesh Angle', mesh_stats.get('mesh_angle', '')])
                region_counts = mesh_stats.get('region_counts', {})
                if region_counts:
                    writer.writerow([])
                    writer.writerow(['REGION DISTRIBUTION'])
                    for region, count in region_counts.items():
                        writer.writerow([region, count])

    def _export_to_excel(self, filename):
        elements_df = pd.DataFrame([{
            'Element_ID': element.get('element_id', ''),
            'Material': element['material'],
            'R_Inner': element['rin'],
            'R_Outer': element['rout'],
            'Theta_Start': element['theta_start'],
            'Theta_End': element['theta_end'],
            'Center_R': element.get('center_r', ''),
            'Center_Theta': element.get('center_theta', ''),
            'Center_X': element.get('center_x', ''),
            'Center_Y': element.get('center_y', ''),
        } for element in self.mesh_data['mesh_elements']])

        mesh_stats = self.mesh_data.get('mesh_stats', {})
        summary_df = pd.DataFrame({
            'Parameter': ['Total Elements', 'Radial Divisions',
                          'Angular Divisions', 'Mesh Angle'],
            'Value': [
                len(self.mesh_data['mesh_elements']),
                len(self.mesh_data['r_divisions']),
                len(self.mesh_data['theta_divisions']),
                mesh_stats.get('mesh_angle', 0),
            ],
        })

        region_counts = mesh_stats.get('region_counts', {})
        region_df = pd.DataFrame({
            'Region': list(region_counts.keys()),
            'Element_Count': list(region_counts.values()),
        })

        machine_params = self.get_machine_parameters()
        params_df = pd.DataFrame({
            'Parameter': list(machine_params.keys()),
            'Value': list(machine_params.values()),
        })

        try:
            with pd.ExcelWriter(filename, engine='openpyxl') as writer:
                elements_df.to_excel(writer, sheet_name='Mesh_Elements', index=False)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
                region_df.to_excel(writer, sheet_name='Region_Distribution',
                                   index=False)
                params_df.to_excel(writer, sheet_name='Machine_Parameters',
                                   index=False)

                # Pad the shorter list so both columns share one frame.
                r_divisions = self.mesh_data['r_divisions']
                theta_divisions = self.mesh_data['theta_divisions']
                padding = [None] * (len(theta_divisions) - len(r_divisions))
                pd.DataFrame({
                    'Radial_Divisions': r_divisions + padding,
                    'Angular_Divisions': theta_divisions,
                }).to_excel(writer, sheet_name='Divisions', index=False)

        except ImportError:
            self.main_window.mesh_log.append(
                "Warning: openpyxl not available. Exporting as CSV instead.")
            self._export_to_csv(filename.replace('.xlsx', '.csv'))


def _layer_spin_box(maximum):
    spin = QSpinBox()
    spin.setRange(1, maximum)
    spin.setValue(1)
    return spin
