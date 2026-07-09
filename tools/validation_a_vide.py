"""Standalone FEMM tool: no-load (à vide) motor validation with empty slots
(formerly ``validation_a_vide.py`` at the root).

Run directly: ``python tools/validation_a_vide.py`` (requires FEMM + pyfemm).
"""

import json
import math
import sys

import femm
from PyQt5.QtWidgets import (QApplication, QGridLayout, QGroupBox, QLabel,
                             QLineEdit, QMainWindow, QMessageBox, QPushButton,
                             QVBoxLayout, QWidget)

from femm_drawing import (add_common_block_labels, add_standard_materials,
                          apply_asymptotic_boundary, draw_circle,
                          draw_complete_circle, draw_rotor_magnets)

SLOT_HEIGHT_MM = 8
MU0 = 4 * math.pi * 1e-7
PARAMS_EXPORT_FILE = 'motor_params.json'

GEOMETRY_PARAMS = [
    ('R_inner', 'Inner radius (mm)', '20'),
    ('R_rotor_outer', 'Rotor outside radius (mm)', '40'),
    ('R_magnet_extra', 'Magnet thickness (mm)', '5'),
    ('e', 'Air gap (mm)', '1'),
    ('stator_thickness', 'Stator thickness (mm)', '20'),
    ('rotor_length', 'Rotor length (mm)', '50'),
]
MAGNET_PARAMS = [
    ('p', 'Number of pole pairs', '2'),
    ('magnet_open', 'Magnet opening angle (deg)', '23'),
    ('magnet_gap', 'Gap between magnets (deg)', '8'),
    ('Br', 'Magnet remanence Br (T)', '1.2'),
]
SLOT_PARAMS = [
    ('n_slots', 'Number of slots', '36'),
    ('slot_angle', 'Slot opening angle (deg)', '5'),
    ('tooth_angle', 'Tooth opening angle (deg)', '5'),
]


class MotorDesignGUI(QMainWindow):
    """Parameter form for the no-load FEMM validation."""

    def __init__(self):
        super().__init__()
        self.params = {}
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle('Motor Design Parameters')
        self.setGeometry(100, 100, 600, 400)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        layout.addWidget(self._build_group("Geometry Parameters", GEOMETRY_PARAMS))
        layout.addWidget(self._build_group("Magnet Parameters", MAGNET_PARAMS))
        layout.addWidget(self._build_group("Slot Parameters", SLOT_PARAMS))

        run_button = QPushButton('Run Simulation')
        run_button.clicked.connect(self.run_simulation)
        layout.addWidget(run_button)

        export_button = QPushButton('Export Parameters')
        export_button.clicked.connect(self.export_parameters)
        layout.addWidget(export_button)

    def _build_group(self, title, param_definitions):
        group = QGroupBox(title)
        grid = QGridLayout()
        for row, (key, label, default) in enumerate(param_definitions):
            self.params[key] = QLineEdit(default)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(self.params[key], row, 1)
        group.setLayout(grid)
        return group

    def get_parameters(self):
        try:
            params = {key: float(widget.text())
                      for key, widget in self.params.items()}

            params['R_magnet'] = params['R_rotor_outer'] + params['R_magnet_extra']
            params['R_airgap'] = params['R_magnet'] + params['e']
            params['R_stator_extr'] = params['R_airgap'] + params['stator_thickness']
            params['slot_pitch'] = 360 / params['n_slots']

            return params
        except ValueError:
            QMessageBox.warning(self, 'Input Error',
                                'Please enter valid numbers for all parameters.')
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

    def export_parameters(self):
        params = self.get_parameters()
        if not params:
            return
        with open(PARAMS_EXPORT_FILE, 'w') as export_file:
            json.dump(params, export_file, indent=4)
        QMessageBox.information(self, 'Export',
                                f'Parameters exported to {PARAMS_EXPORT_FILE}')


def run_femm_simulation(**params):
    """Build and solve the no-load motor model in FEMM."""
    magnet_remanence = params.get('Br', 1.2)

    femm.openfemm()
    femm.newdocument(0)  # magnetostatic problem
    femm.mi_probdef(0, "millimeters", "planar", 1e-8,
                    params['R_rotor_outer'] * 2,
                    params.get('rotor_length', 50))

    # Coercivity from remanence: Hc = Br / mu0.
    add_standard_materials(ndfeb_hc=magnet_remanence / MU0)

    draw_complete_circle(params['R_inner'])
    draw_complete_circle(params['R_rotor_outer'])
    draw_rotor_magnets(params, magnet_strength=magnet_remanence)

    draw_circle(params['R_airgap'])
    draw_circle(params['R_airgap'], n_slots=params['n_slots'],
                slot_pitch=params['slot_pitch'],
                slot_angle=params['slot_angle'], skip_slots=True)

    # Empty (air-filled) slots.
    r_slot = params['R_magnet'] + params['e'] + SLOT_HEIGHT_MM
    for slot in range(int(params['n_slots'])):
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

        angle_mid = start_angle + params['slot_angle'] / 2
        r_mid = (params['R_airgap'] + r_slot) / 2
        lx = r_mid * math.cos(math.radians(angle_mid))
        ly = r_mid * math.sin(math.radians(angle_mid))
        femm.mi_addblocklabel(lx, ly)
        femm.mi_selectlabel(lx, ly)
        femm.mi_setblockprop("Air", 0, 1, "<None>", 0, 0, 1)
        femm.mi_clearselected()

    draw_circle(r_slot, n_slots=params['n_slots'],
                slot_pitch=params['slot_pitch'],
                slot_angle=params['slot_angle'], skip_slots=True)
    draw_complete_circle(params['R_stator_extr'])

    add_common_block_labels(params, r_slot)

    femm.mi_zoomnatural()
    apply_asymptotic_boundary(params['R_stator_extr'])

    femm.mi_saveas("concentric_circles.fem")
    femm.mi_analyze(1)
    femm.mi_loadsolution()

    femm.mo_hidepoints()
    femm.mo_hidegrid()
    femm.mo_showdensityplot(0, 0, 1.5, 0, "bmag")
    femm.mo_showcontourplot(19, 0, 1.5, "a")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = MotorDesignGUI()
    gui.show()
    sys.exit(app.exec_())
