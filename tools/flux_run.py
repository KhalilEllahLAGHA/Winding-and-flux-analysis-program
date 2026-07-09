"""Standalone FEMM tool: motor simulation with stator windings driven by a
connection matrix loaded from Excel (formerly ``flux_run.py`` at the root).

Run directly: ``python tools/flux_run.py`` (requires FEMM + pyfemm).
"""

import math
import os
import sys

import femm
import pandas as pd
from PyQt5.QtWidgets import (QApplication, QComboBox, QFileDialog, QGridLayout,
                             QGroupBox, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QPushButton, QVBoxLayout, QWidget)

from femm_drawing import (add_common_block_labels, add_standard_materials,
                          apply_asymptotic_boundary, draw_circle,
                          draw_complete_circle, draw_rotor_magnets)

SLOT_HEIGHT_MM = 8
PROBLEM_DEPTH_MM = 30
# NdFeB coercivity used historically by this tool (Br = -1.3 T equivalent).
NDFEB_HC = -1034560

GEOMETRY_PARAMS = [
    ('R_inner', 'Inner radius (mm)', '20'),
    ('R_rotor_outer', 'Rotor outside radius (mm)', '40'),
    ('R_magnet_extra', 'Magnet thickness (mm)', '5'),
    ('e', 'Air gap (mm)', '1'),
    ('stator_thickness', 'Stator thickness (mm)', '20'),
]
MAGNET_PARAMS = [
    ('p', 'Number of pole pairs', '2'),
    ('magnet_open', 'Magnet opening angle (deg)', '23'),
    ('magnet_gap', 'Gap between magnets (deg)', '8'),
]
SLOT_PARAMS = [
    ('n_slots', 'Number of slots', '36'),
    ('slot_angle', 'Slot opening angle (deg)', '5'),
    ('tooth_angle', 'Tooth opening angle (deg)', '5'),
]
WINDING_PARAMS = [
    ('phase_current', 'Phase Current (A)', '10'),
    ('n_turns', 'Number of turns per slot', '50'),
]

PHASE_ROWS = ("Phase A", "Phase B", "Phase C")


class MotorDesignGUI(QMainWindow):
    """Parameter form for the FEMM winding simulation."""

    def __init__(self):
        super().__init__()
        self.connection_matrix = None
        self.params = {}
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle('Motor Design Parameters')
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        layout.addWidget(self._build_group("Geometry Parameters", GEOMETRY_PARAMS))
        layout.addWidget(self._build_group("Magnet Parameters", MAGNET_PARAMS))
        layout.addWidget(self._build_group("Slot Parameters", SLOT_PARAMS))
        layout.addWidget(self._build_winding_group())

        run_button = QPushButton('Run Simulation')
        run_button.clicked.connect(self.run_simulation)
        layout.addWidget(run_button)

    def _build_group(self, title, param_definitions):
        group = QGroupBox(title)
        grid = QGridLayout()
        for row, (key, label, default) in enumerate(param_definitions):
            self.params[key] = QLineEdit(default)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(self.params[key], row, 1)
        group.setLayout(grid)
        return group

    def _build_winding_group(self):
        group = QGroupBox("Winding Parameters")
        grid = QGridLayout()

        for row, (key, label, default) in enumerate(WINDING_PARAMS):
            self.params[key] = QLineEdit(default)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(self.params[key], row, 1)

        next_row = len(WINDING_PARAMS)
        self.connection_file_label = QLabel("Connection Matrix File: Not selected")
        self.select_file_button = QPushButton("Select Connection Matrix File")
        self.select_file_button.clicked.connect(self.select_connection_file)
        grid.addWidget(self.connection_file_label, next_row, 0, 1, 2)
        grid.addWidget(self.select_file_button, next_row + 1, 0, 1, 2)

        self.winding_type_combo = QComboBox()
        self.winding_type_combo.addItems(["Single Layer", "Double Layer"])
        grid.addWidget(QLabel("Winding Type:"), next_row + 2, 0)
        grid.addWidget(self.winding_type_combo, next_row + 2, 1)

        group.setLayout(grid)
        return group

    def select_connection_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Connection Matrix Excel File", "",
            "Excel Files (*.xlsx *.xls);;All Files (*)")
        if not file_path:
            return

        try:
            matrix = pd.read_excel(file_path, header=None)
            winding_type = self.winding_type_combo.currentText()
            expected_rows = 6 if winding_type == "Double Layer" else 3

            if matrix.shape[0] != expected_rows:
                raise ValueError(
                    f"Connection matrix must have {expected_rows} rows for "
                    f"{winding_type.lower()} winding")

            self.connection_matrix = matrix
            self.connection_file_label.setText(
                f"Connection Matrix File: {os.path.basename(file_path)} "
                f"({winding_type})")
            QMessageBox.information(
                self, "Success",
                f"Connection matrix loaded successfully! "
                f"({winding_type.lower()} winding)")
        except Exception as error:
            self.connection_matrix = None
            self.connection_file_label.setText(
                "Connection Matrix File: Not selected")
            QMessageBox.critical(self, "Error",
                                 f"Failed to load connection matrix: {error}")

    def get_parameters(self):
        try:
            params = {key: float(widget.text())
                      for key, widget in self.params.items()}
            params['winding_type'] = self.winding_type_combo.currentText()

            params['R_magnet'] = params['R_rotor_outer'] + params['R_magnet_extra']
            params['R_airgap'] = params['R_magnet'] + params['e']
            params['R_stator_extr'] = params['R_airgap'] + params['stator_thickness']
            params['slot_pitch'] = 360 / params['n_slots']

            if self.connection_matrix is None:
                raise ValueError("Connection matrix file must be selected")
            params['connection_matrix'] = self.connection_matrix.values.tolist()

            return params
        except ValueError as error:
            QMessageBox.warning(
                self, 'Input Error',
                f'Please enter valid numbers for all parameters and select a '
                f'connection matrix file. Error: {error}')
            return None

    def run_simulation(self):
        params = self.get_parameters()
        if not params:
            return
        try:
            run_femm_simulation(**params)
            QMessageBox.information(self, 'Success',
                                    'Simulation completed successfully!')
        except Exception as error:
            QMessageBox.critical(self, 'Error',
                                 f'Error running simulation: {error}')


def _pad_connection_matrix(connection_matrix, n_slots, winding_type):
    """Zero-pad matrix columns when there are fewer columns than slots."""
    if len(connection_matrix[0]) >= n_slots:
        return

    print(f"Warning: Connection matrix has {len(connection_matrix[0])} "
          f"columns, but there are {n_slots} slots")
    rows = 6 if winding_type == "Double Layer" else 3
    for i in range(rows):
        connection_matrix[i] += [0] * (n_slots - len(connection_matrix[i]))


def _set_slot_block(label_x, label_y, matrix_rows, slot, n_turns):
    """Assign the winding (or air) material at one slot block label.

    ``matrix_rows`` are the three phase rows (A, B, C) of one layer.
    """
    femm.mi_addblocklabel(label_x, label_y)
    femm.mi_selectlabel(label_x, label_y)

    for phase_name, row in zip(PHASE_ROWS, matrix_rows):
        if row[slot] == 1:
            femm.mi_setblockprop("10 SWG Copper", 0, 1, phase_name, 0, 0, n_turns)
            break
        if row[slot] == -1:
            femm.mi_setblockprop("10 SWG Copper", 0, 1, phase_name, 0, 0, -n_turns)
            break
    else:
        femm.mi_setblockprop("Air", 0, 1, "<None>", 0, 0, 1)

    femm.mi_clearselected()


def _draw_slot_geometry(params, slot, r_slot):
    """Draw the straight sides and bottom of one slot opening."""
    start_angle = slot * params['slot_pitch']
    end_angle = start_angle + params['slot_angle']

    x1 = params['R_airgap'] * math.cos(math.radians(start_angle))
    y1 = params['R_airgap'] * math.sin(math.radians(start_angle))
    x2 = params['R_airgap'] * math.cos(math.radians(end_angle))
    y2 = params['R_airgap'] * math.sin(math.radians(end_angle))
    x3 = r_slot * math.cos(math.radians(end_angle))
    y3 = r_slot * math.sin(math.radians(end_angle))
    x4 = r_slot * math.cos(math.radians(start_angle))
    y4 = r_slot * math.sin(math.radians(start_angle))

    femm.mi_addnode(x1, y1)
    femm.mi_addnode(x2, y2)
    femm.mi_addnode(x3, y3)
    femm.mi_addnode(x4, y4)
    femm.mi_addsegment(x2, y2, x3, y3)
    femm.mi_addsegment(x3, y3, x4, y4)
    femm.mi_addsegment(x4, y4, x1, y1)

    return start_angle, end_angle


def run_femm_simulation(**params):
    """Build, solve, and post-process the motor model in FEMM."""
    femm.openfemm()
    femm.newdocument(0)  # magnetostatic problem
    femm.mi_probdef(0, "millimeters", "planar", 1e-8,
                    params['R_rotor_outer'] * 2, PROBLEM_DEPTH_MM)

    add_standard_materials(ndfeb_hc=NDFEB_HC)

    # 10 SWG copper: 3.251 mm wire diameter, 1.68e-8 ohm·m resistivity.
    try:
        femm.mi_getmaterial("10 SWG Copper")
    except Exception:
        femm.mi_addmaterial("10 SWG Copper", 1, 1, 0, 1.68e-8, 0, 0, 0,
                            1, 0, 0, 0, 1, 3.251)

    # Balanced three-phase currents (A at peak, B and C at -I/2).
    current = params['phase_current']
    femm.mi_addcircprop("Phase A", current, 1)
    femm.mi_addcircprop("Phase B", -current / 2, 1)
    femm.mi_addcircprop("Phase C", -current / 2, 1)

    draw_complete_circle(params['R_inner'])
    draw_complete_circle(params['R_rotor_outer'])
    draw_rotor_magnets(params, magnet_strength=1.2)

    draw_circle(params['R_airgap'])
    draw_circle(params['R_airgap'], n_slots=params['n_slots'],
                slot_pitch=params['slot_pitch'],
                slot_angle=params['slot_angle'], skip_slots=True)

    r_slot = params['R_magnet'] + params['e'] + SLOT_HEIGHT_MM
    connection_matrix = params['connection_matrix']
    n_slots = int(params['n_slots'])
    winding_type = params.get('winding_type', 'Double Layer')
    n_turns = params['n_turns']

    _pad_connection_matrix(connection_matrix, n_slots, winding_type)

    for slot in range(n_slots):
        start_angle, end_angle = _draw_slot_geometry(params, slot, r_slot)
        angle_mid = start_angle + params['slot_angle'] / 2

        if winding_type == "Double Layer":
            # Arc dividing the slot into top and bottom halves.
            r_mid = (params['R_airgap'] + r_slot) / 2
            x_mid1 = r_mid * math.cos(math.radians(start_angle))
            y_mid1 = r_mid * math.sin(math.radians(start_angle))
            x_mid2 = r_mid * math.cos(math.radians(end_angle))
            y_mid2 = r_mid * math.sin(math.radians(end_angle))
            femm.mi_addnode(x_mid1, y_mid1)
            femm.mi_addnode(x_mid2, y_mid2)
            femm.mi_addarc(x_mid1, y_mid1, x_mid2, y_mid2,
                           params['slot_angle'], 1)

            quarter = (r_slot - params['R_airgap']) / 4
            r_top = r_mid + quarter
            r_bottom = r_mid - quarter

            _set_slot_block(r_top * math.cos(math.radians(angle_mid)),
                            r_top * math.sin(math.radians(angle_mid)),
                            connection_matrix[0:3], slot, n_turns)
            _set_slot_block(r_bottom * math.cos(math.radians(angle_mid)),
                            r_bottom * math.sin(math.radians(angle_mid)),
                            connection_matrix[3:6], slot, n_turns)
        else:
            r_label = (params['R_airgap'] + r_slot) / 2
            _set_slot_block(r_label * math.cos(math.radians(angle_mid)),
                            r_label * math.sin(math.radians(angle_mid)),
                            connection_matrix[0:3], slot, n_turns)

    draw_circle(r_slot, n_slots=params['n_slots'],
                slot_pitch=params['slot_pitch'],
                slot_angle=params['slot_angle'], skip_slots=True)
    draw_complete_circle(params['R_stator_extr'])

    add_common_block_labels(params, r_slot)

    femm.mi_zoomnatural()
    apply_asymptotic_boundary(params['R_stator_extr'])

    femm.mi_saveas("motor_with_windings.fem")
    femm.mi_analyze(1)
    femm.mi_loadsolution()

    femm.mo_hidepoints()
    femm.mo_hidegrid()
    femm.mo_showdensityplot(0, 0.00000005, 1.9, 0, "bmag")
    femm.mo_showcontourplot(19, 0, 1.5, "a")

    print("\nCircuit Properties:")
    for phase in PHASE_ROWS:
        circuit_props = femm.mo_getcircuitproperties(phase)
        print(f"{phase}: Current={circuit_props[0]} A, "
              f"Voltage={circuit_props[1]} V, "
              f"Flux Linkage={circuit_props[2]} Wb")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = MotorDesignGUI()
    gui.show()
    sys.exit(app.exec_())
