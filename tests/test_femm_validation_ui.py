"""Qt validation-flow regression tests with an isolated mock FEMM worker."""

import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit, QProgressBar, QPushButton, QWidget

from core.femm_runner import REQUIRED_METRICS
from core.meshing_engine import MeshingEngine
from ui.flux_density_page import FluxDensityHeatmapUI
from utils.constants import DEFAULT_MACHINE_PARAMS


class ValidationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='femm-ui-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        settings = {'rotor': 2, 'slot': 2, 'airgap': 5,
                    'stator': 2, 'angle_divider': 1}
        mesh = MeshingEngine().generate_mesh(
            dict(DEFAULT_MACHINE_PARAMS, num_slots=6, slot_angle=30.0), settings)
        self.engine = SimpleNamespace(
            matrix=np.array([[1, 0, 0, -1, 0, 0],
                             [0, 1, 0, 0, -1, 0],
                             [0, 0, 1, 0, 0, -1]]),
            turns=20, phase_current_a=2.0, wt_angle_deg=90.0)
        self.window = QWidget()
        self.window.meshing_page_ui = SimpleNamespace(
            mesh_data=mesh, get_current_mesh_settings=lambda: settings)
        self.window.connection_tab = SimpleNamespace(mmf_calculator=self.engine)
        self.window.flux_ur_stator = QLineEdit('4000')
        self.window.flux_ur_rotor = QLineEdit('4000')
        self.window.flux_calc_axial_length = QLineEdit('110')
        self.window.flux_status_label = QLabel()
        self.window.flux_calculate_btn = QPushButton()
        self.window.flux_femm_validation_btn = QPushButton()
        self.window.flux_progress_bar = QProgressBar()
        self.controller = FluxDensityHeatmapUI(self.window)
        self.addCleanup(self.window.deleteLater)
        for name in ('critical', 'information'):
            patcher = patch(f'ui.flux_density_page.QMessageBox.{name}')
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = patch('ui.flux_density_page.FEMM_VALIDATION_DIR', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_mesh_reports_prerequisite_without_spawning_femm(self):
        self.window.meshing_page_ui.mesh_data = None
        with patch('ui.flux_density_page.QProcess') as process:
            self.controller.run_femm_validation()
        process.assert_not_called()
        self.critical.assert_called_once()
        self.assertIn('Generate a mesh in Step 2',
                      self.window.flux_status_label.text())
        self.assertTrue(self.window.flux_femm_validation_btn.isEnabled())
        self.assertFalse(self.controller._femm_preparing)

    def test_input_edits_during_local_solve_prevent_worker_launch(self):
        def calculate_and_edit():
            self.controller.flux_results = {'dummy': True}
            self.engine.phase_current_a += 1

        with patch.object(self.controller, 'flux_calculate',
                          side_effect=calculate_and_edit), \
                patch('ui.flux_density_page.QProcess') as process:
            self.controller.run_femm_validation()
        process.assert_not_called()
        self.critical.assert_called_once()
        self.assertIn('Inputs changed during the local calculation',
                      self.window.flux_status_label.text())
        self.assertTrue(self.window.flux_femm_validation_btn.isEnabled())
        self.assertIsNone(self.controller.femm_process)

    def test_validation_requests_a_persistent_femm_solution_window(self):
        def calculate():
            mesh = self.window.meshing_page_ui.mesh_data
            self.controller.flux_results = {'flux_densities': {
                e['element_id']: {'Br': 0.1, 'Btheta': 0.0}
                for e in mesh['mesh_elements']}}

        try:
            with patch.object(self.controller, 'flux_calculate',
                              side_effect=calculate), \
                    patch.object(QProcess, 'start') as start:
                self.controller.run_femm_validation()
            self.critical.assert_not_called()
            start.assert_called_once()
            self.assertIn('--keep-open', start.call_args.args[1])
            self.assertFalse(self.window.flux_calculate_btn.isEnabled())
            self.assertFalse(self.window.flux_femm_validation_btn.isEnabled())
        finally:
            if self.controller.femm_process is not None:
                self.controller._femm_watchdog.stop()
                self.controller.femm_process.deleteLater()
                self.controller.femm_process = None

    def prepare_completion(self, *, reference=0.0, local=0.0, stderr=b''):
        results = self.root / 'validation_results.txt'
        results.write_text('\n'.join(f'{key}={reference}'
                                     for key in REQUIRED_METRICS),
                           encoding='utf-8')
        process = Mock()
        process.readAllStandardOutput.return_value = json.dumps(
            {'backend': 'mock-femm'}).encode('utf-8')
        process.readAllStandardError.return_value = stderr
        self.controller.femm_process = process
        self.controller._femm_watchdog = Mock()
        self.controller._femm_run = {
            'directory': self.root,
            'results': results,
            'local': {key: local for key in REQUIRED_METRICS},
            'signature': self.controller._femm_input_signature(),
            'inputs': '6 slots, 20 turns, 2 A, Wt=90 deg',
        }
        self.window.flux_calculate_btn.setEnabled(False)
        self.window.flux_femm_validation_btn.setEnabled(False)
        self.window.flux_progress_bar.setRange(0, 0)
        return process

    def test_zero_reference_reports_absolute_difference_without_relative_percent(self):
        self.prepare_completion(reference=0, local=1)
        self.controller._finish_femm_validation(0, QProcess.NormalExit)
        self.critical.assert_not_called()
        self.information.assert_called_once()
        summary = self.information.call_args.args[2]
        status = self.window.flux_status_label.text()
        self.assertIn('absolute', summary)
        self.assertNotIn('%', summary)
        self.assertNotIn('0.00%', status)
        self.assertIn('Zero FEMM reference', status)
        self.assertTrue((self.root / 'comparison.txt').is_file())

    def test_worker_failure_cleans_up_and_reenables_both_actions(self):
        process = self.prepare_completion(stderr=b'FEMM solver failed')
        self.controller._finish_femm_validation(1, QProcess.CrashExit)
        self.critical.assert_called_once()
        self.information.assert_not_called()
        self.assertIn('FEMM solver failed', self.window.flux_status_label.text())
        self.assertIsNone(self.controller.femm_process)
        self.assertTrue(self.window.flux_calculate_btn.isEnabled())
        self.assertTrue(self.window.flux_femm_validation_btn.isEnabled())
        self.assertEqual(self.window.flux_progress_bar.minimum(), 0)
        self.assertEqual(self.window.flux_progress_bar.maximum(), 100)
        self.assertTrue(self.window.flux_progress_bar.isHidden())
        process.deleteLater.assert_called_once()
        self.controller._femm_watchdog.stop.assert_called_once()

    def test_worker_failed_to_start_uses_failure_cleanup(self):
        self.prepare_completion(stderr=b'Cannot start worker')
        self.controller._femm_process_error(QProcess.FailedToStart)
        self.critical.assert_called_once()
        self.assertIsNone(self.controller.femm_process)
        self.assertTrue(self.window.flux_calculate_btn.isEnabled())
        self.assertTrue(self.window.flux_femm_validation_btn.isEnabled())


if __name__ == '__main__':
    unittest.main()
