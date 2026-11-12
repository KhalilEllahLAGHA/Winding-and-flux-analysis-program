"""MMF curve semantics and periodic geometry, independent of FEMM output."""

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt5.QtWidgets import QApplication

from core.mmf_engine import MMFCalculationEngine
from ui.mmf_tab import ConnectionMatrixTab, ResultantAnimationWindow


PHASES = ('A', 'B', 'C')
# A known two-pole, six-slot winding. Every complete phase has one return.
SINGLE = np.array([[1, 0, 0, -1, 0, 0],
                   [0, 0, 1, 0, 0, -1],
                   [0, -1, 0, 0, 1, 0]])
PATTERN = [('A', None), ('C', None), ('B', None),
           ('A', None), ('C', None), ('B', None)]


def engine_for(matrix=None, *, arc=17.25):
    engine = MMFCalculationEngine()
    engine.turns = 20
    engine.phase_current_a = 2.0
    engine.wt_angle_deg = 28.0
    engine.slot_arc_deg = arc
    engine.set_connection_matrix(SINGLE.copy() if matrix is None else matrix)
    return engine


class PhaseSnapshotTests(unittest.TestCase):
    def test_instantaneous_phase_snapshots_sum_to_resultant(self):
        for double in (False, True):
            engine = engine_for(np.vstack((SINGLE, SINGLE)) if double else None)
            for wt in (0, 28, 90, 180, 257, 360):
                with self.subTest(double=double, wt=wt):
                    snapshots = [engine.get_profile_data(phase, wt_deg=wt)
                                 for phase in PHASES]
                    angles, resultant = engine.get_profile_data('resultant', wt_deg=wt)
                    for phase_angles, _ in snapshots:
                        np.testing.assert_array_equal(angles, phase_angles)
                    np.testing.assert_allclose(
                        sum(values for _, values in snapshots), resultant,
                        atol=1e-12, rtol=1e-12)

    def test_known_time_factors_include_zero_negative_and_peak_phase_current(self):
        engine = engine_for()
        references = [engine.get_profile_data(phase)[1].copy() for phase in PHASES]
        # At Wt=0: phase A is unenergized, B=+sqrt(3)/2 and C=-sqrt(3)/2.
        for phase, reference, factor in zip(
                PHASES, references, (0.0, np.sqrt(3) / 2, -np.sqrt(3) / 2)):
            np.testing.assert_allclose(
                engine.get_profile_data(phase, wt_deg=0)[1], reference * factor,
                atol=1e-12)
        # At Wt=90: A reaches its peak and B and C both carry -I/2.
        for phase, reference, factor in zip(PHASES, references, (1.0, -0.5, -0.5)):
            np.testing.assert_allclose(
                engine.get_profile_data(phase, wt_deg=90)[1], reference * factor,
                atol=1e-12)

    def test_peak_phase_references_do_not_depend_on_saved_wt(self):
        engine = engine_for()
        references = {phase: engine.get_profile_data(phase)[1].copy() for phase in PHASES}
        for wt in (0, 90, 180, 257):
            engine.update_wt_angle(wt)
            for phase in PHASES:
                np.testing.assert_array_equal(engine.get_profile_data(phase)[1],
                                              references[phase])

    def test_requested_snapshot_does_not_mutate_configured_angle_or_resultant(self):
        engine = engine_for()
        angle = engine.wt_angle_deg
        saved = engine.get_profile_data('resultant')[1].copy()
        for phase in (*PHASES, 'resultant'):
            engine.get_profile_data(phase, wt_deg=137)
        self.assertEqual(engine.wt_angle_deg, angle)
        np.testing.assert_array_equal(engine.get_profile_data('resultant')[1], saved)

    def test_equal_current_split_between_two_layers_is_preserved(self):
        single = engine_for()
        double = engine_for(np.vstack((SINGLE, SINGLE)))
        for phase in PHASES:
            _, one_layer = single.get_profile_data(phase)
            _, both_layers = double.get_profile_data(phase)
            _, top = double.get_profile_data(phase, 'top')
            _, bottom = double.get_profile_data(phase, 'bot')
            np.testing.assert_allclose(both_layers, one_layer, atol=1e-12)
            np.testing.assert_allclose(top, one_layer / 2, atol=1e-12)
            np.testing.assert_allclose(bottom, one_layer / 2, atol=1e-12)

    def test_balanced_fundamental_has_constant_three_halves_phase_amplitude(self):
        engine = engine_for()
        # Interpolate onto a uniform angular grid before Fourier analysis:
        # exact geometry knots make the engine's plotting grid nonuniform.
        uniform = np.linspace(0, 360, 6000, endpoint=False)
        harmonic = np.exp(-1j * np.deg2rad(uniform))

        def fundamental(profile):
            angles, values = profile
            return 2 * np.mean(np.interp(uniform, angles, values) * harmonic)

        phase_amplitude = abs(fundamental(engine.get_profile_data('A')))
        self.assertGreater(phase_amplitude, 0.0)
        for wt in (0, 15, 30, 60, 91, 157, 240, 359):
            with self.subTest(wt=wt):
                actual = abs(fundamental(engine.get_profile_data('resultant', wt_deg=wt)))
                self.assertAlmostEqual(actual / phase_amplitude, 1.5, delta=1e-10)


class PeriodicCurveGeometryTests(unittest.TestCase):
    def test_true_tooth_slot_boundaries_and_periodic_endpoint_are_included(self):
        engine = engine_for(arc=17.25)
        angles, values = engine.get_profile_data('A')
        self.assertEqual(angles[0], 0.0)
        self.assertEqual(angles[-1], 360.0)
        self.assertTrue(np.all(np.diff(angles) > 0))
        self.assertAlmostEqual(values[-1], values[0])
        for slot in range(6):
            for knot in (60.0 * slot, 60.0 * slot + 60.0 - 17.25):
                with self.subTest(knot=knot):
                    self.assertTrue(np.any(np.isclose(angles, knot, rtol=0, atol=1e-11)))

    def test_exact_angular_integral_is_zero_for_asymmetric_balanced_winding(self):
        # This phase has no half-wave symmetry, so mean errors cannot cancel
        # merely because opposite points happen to be sampled in pairs.
        matrix = SINGLE.copy()
        matrix[0] = [1, 1, -2, 0, 0, 0]
        engine = engine_for(matrix, arc=17.25)
        for phase in (*PHASES, 'resultant'):
            angles, values = engine.get_profile_data(phase)
            integral = float(np.trapezoid(values, angles))
            self.assertAlmostEqual(integral / 360, 0.0, delta=1e-11)

    def test_custom_slot_arc_survives_same_slot_count_and_coil_span_updates(self):
        engine = engine_for(arc=17.25)
        for span in (3, 2, 1):
            engine.update_matrix_from_parameters(PATTERN, True, 2, coil_span=span)
            self.assertEqual(engine.slot_arc_deg, 17.25)
            self.assertAlmostEqual(engine.tooth_arc_deg, 60 - 17.25)

    def test_switching_to_single_layer_removes_stale_layer_profiles(self):
        engine = engine_for(np.vstack((SINGLE, SINGLE)))
        self.assertIn('A_top', engine.profiles)
        engine.set_connection_matrix(SINGLE.copy())
        for phase in PHASES:
            for layer in ('top', 'bot', 'sum'):
                self.assertEqual(engine.get_profile_data(phase, layer), (None, None))
                self.assertNotIn(f'{phase}_{layer}', engine.profiles)

    def test_invalid_slot_arc_update_preserves_the_previous_valid_state(self):
        engine = engine_for(arc=17.25)
        before = {key: (a.copy(), v.copy()) for key, (a, v) in engine.profiles.items()}
        for invalid in (0, -1, 60, np.nan, np.inf):
            with self.subTest(arc=invalid), self.assertRaises(ValueError):
                engine.update_slot_arc(invalid)
            self.assertEqual(engine.slot_arc_deg, 17.25)
            self.assertAlmostEqual(engine.tooth_arc_deg, 60 - 17.25)
            for key, (angles, values) in before.items():
                np.testing.assert_array_equal(engine.profiles[key][0], angles)
                np.testing.assert_array_equal(engine.profiles[key][1], values)


class CurveUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_tab(self):
        tab = ConnectionMatrixTab()
        self.addCleanup(tab.close)
        self.addCleanup(tab.deleteLater)
        tab.update_matrix(PATTERN, False, 2)
        tab.turns_spin.setValue(20)
        tab.current_spin.setValue(2.0)
        tab.resultant_checkbox.setChecked(True)
        return tab

    def test_default_instantaneous_plot_phases_sum_to_displayed_resultant(self):
        tab = self.make_tab()
        self.assertEqual(tab.phase_view_combo.currentText(), 'Instantaneous phases')
        for wt in (0, 28, 90, 210):
            tab.wt_spin.setValue(wt)
            tab.update_plot()
            lines = tab.ax.get_lines()
            self.assertEqual(len(lines), 4)
            np.testing.assert_allclose(
                sum(np.asarray(line.get_ydata()) for line in lines[:3]),
                lines[3].get_ydata(), atol=1e-12, rtol=1e-12)

    def test_peak_reference_view_retains_static_phase_shapes(self):
        tab = self.make_tab()
        tab.phase_view_combo.setCurrentText('Peak phase references')
        tab.wt_spin.setValue(0)
        tab.update_plot()
        references = [np.asarray(line.get_ydata()).copy() for line in tab.ax.get_lines()[:3]]
        tab.wt_spin.setValue(90)
        tab.update_plot()
        for actual, reference in zip(tab.ax.get_lines()[:3], references):
            np.testing.assert_array_equal(actual.get_ydata(), reference)

    def test_tab_sync_keeps_custom_slot_arc_for_unchanged_slot_count(self):
        tab = self.make_tab()
        tab.slot_arc_spin.setValue(17.25)
        for span in (3, 1):
            tab.update_matrix(PATTERN, True, 2, coil_span=span)
            self.assertEqual(tab.slot_arc_spin.value(), 17.25)
            self.assertEqual(tab.mmf_calculator.slot_arc_deg, 17.25)

    def test_main_window_tab_changes_preserve_custom_slot_arc_and_flux_geometry(self):
        from main import MainWindow

        window = MainWindow()
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        window.connection_tab.slot_arc_spin.setValue(3.0)
        for tab_index in (2, 1, 0, 1):
            window.tabs.setCurrentIndex(tab_index)
            self.app.processEvents()
            self.assertEqual(window.connection_tab.slot_arc_spin.value(), 3.0)
            self.assertEqual(window.connection_tab.mmf_calculator.slot_arc_deg, 3.0)
            self.assertEqual(float(window.flux_slot_angle.text()), 3.0)

    def test_reset_redraws_paused_animation_at_zero_without_changing_engine_wt(self):
        engine = engine_for()
        animation = ResultantAnimationWindow(None, engine)
        animation.timer.stop()
        self.addCleanup(animation.close)
        self.addCleanup(animation.deleteLater)
        animation.current_wt = 90.0
        animation.plot_resultant()
        animation.is_paused = True
        animation.reset_animation()
        self.assertEqual(animation.current_wt, 0.0)
        self.assertEqual(engine.wt_angle_deg, 28.0)
        expected_angles, expected_values = engine.get_profile_data('resultant', wt_deg=0)
        np.testing.assert_array_equal(animation._resultant_line.get_xdata(), expected_angles)
        np.testing.assert_allclose(animation._resultant_line.get_ydata(), expected_values,
                                   atol=1e-12)


if __name__ == '__main__':
    unittest.main()
