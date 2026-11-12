"""Regression checks for current-model FEMM validation (no FEMM install needed)."""

import math
from contextlib import ExitStack
from itertools import count
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from core.femm_runner import parse_validation_results, run_femm_script
from core.femm_validation import (
    airgap_samples,
    build_validation_script,
    compute_reference_metrics,
    compare_airgap_profiles,
    slot_ampere_turns,
)
from core.meshing_engine import MeshingEngine
from utils.constants import DEFAULT_MACHINE_PARAMS, DEFAULT_RELATIVE_PERMEABILITIES


METRIC_KEYS = (
    'airgap_br_max_t',
    'airgap_br_avg_excited_t',
    'airgap_flux_max_wb',
    'airgap_flux_avg_excited_wb',
)


def make_mesh():
    params = dict(DEFAULT_MACHINE_PARAMS, num_slots=6, slot_angle=30.0)
    settings = {'rotor': 2, 'slot': 2, 'airgap': 5, 'stator': 2,
                'angle_divider': 1}
    return MeshingEngine().generate_mesh(params, settings)


def make_engine(matrix=None):
    if matrix is None:
        matrix = np.array([[1, 0, 0, -1, 0, 0],
                           [0, 1, 0, 0, -1, 0],
                           [0, 0, 1, 0, 0, -1]])
    return SimpleNamespace(matrix=matrix, turns=20, phase_current_a=2.0,
                           wt_angle_deg=90.0, n_slots=6)


class SamplingTests(unittest.TestCase):
    def test_selects_one_complete_middle_airgap_ring(self):
        mesh = make_mesh()
        samples = airgap_samples(mesh)
        self.assertEqual(len(samples), mesh['total_angular'])
        self.assertEqual({e['material'] for e in samples}, {'Air Gap'})
        self.assertEqual(len({e['center_r'] for e in samples}), 1)
        midpoint = (mesh['params']['stator_inner_radius']
                    - mesh['params']['air_gap'] / 2)
        self.assertAlmostEqual(samples[0]['center_r'], midpoint)
        self.assertAlmostEqual(sum(e['theta_end'] - e['theta_start']
                                   for e in samples), 360.0)

    def test_radial_flux_uses_same_br_samples_and_sector_area(self):
        samples = airgap_samples(make_mesh())
        br = [-2.0, 0.0, 1.0] * (len(samples) // 3)
        flux_results = {'flux_densities': {
            sample['element_id']: {'Br': value, 'Btheta': 999.0}
            for sample, value in zip(samples, br)
        }}
        # Deliberately irrelevant branch values: the old implementation
        # mixed radial and tangential branches with incompatible FEMM flux.
        flux_results['branch_fluxes'] = {
            e['element_id']: {'up': 999.0, 'left': 999.0} for e in samples
        }
        result = compute_reference_metrics(flux_results, samples, 110.0)
        area = (samples[0]['center_r'] / 1000
                * math.radians(samples[0]['theta_end']
                               - samples[0]['theta_start']) * 0.110)
        self.assertAlmostEqual(result['airgap_br_max_t'], 2.0)
        self.assertAlmostEqual(result['airgap_br_avg_excited_t'], 1.5)
        self.assertAlmostEqual(result['airgap_flux_max_wb'], 2.0 * area)
        self.assertAlmostEqual(result['airgap_flux_avg_excited_wb'], 1.5 * area)


class ScriptTests(unittest.TestCase):
    def test_generated_script_uses_current_paths_and_lua4_io(self):
        with tempfile.TemporaryDirectory(prefix='femm test ') as tmp:
            path = build_validation_script(
                make_mesh(), make_engine(), DEFAULT_RELATIVE_PERMEABILITIES,
                110.0, Path(tmp))
            source = Path(path).read_text(encoding='utf-8')
            self.assertNotIn('Users/Lagha', source)
            self.assertNotIn('project/backup', source)
            self.assertNotIn('io.open', source)
            self.assertNotIn('string.format', source)
            self.assertIn('openfile(', source)
            self.assertIn('closefile(', source)
            self.assertIn(str(Path(tmp)).replace('\\', '/'), source)

    def test_generated_excitation_matches_active_current_and_angle(self):
        engine = make_engine()
        engine.turns = 37
        engine.phase_current_a = 0.7
        engine.wt_angle_deg = 28.0
        with tempfile.TemporaryDirectory() as tmp:
            path = build_validation_script(
                make_mesh(), engine, DEFAULT_RELATIVE_PERMEABILITIES,
                110.0, Path(tmp))
            source = Path(path).read_text(encoding='utf-8')
            line = re.search(r'^slot_ni = \{(.*)\}$', source, re.MULTILINE)
            self.assertIsNotNone(line)
            actual = [float(value) for value in line.group(1).split(',')]
            np.testing.assert_allclose(actual, slot_ampere_turns(engine))

    def test_generated_solution_keeps_density_and_flux_contours_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_validation_script(
                make_mesh(), make_engine(), DEFAULT_RELATIVE_PERMEABILITIES,
                110.0, Path(tmp))
            source = Path(path).read_text(encoding='utf-8')
            self.assertIn('mo_showdensityplot(', source)
            self.assertIn('mo_showcontourplot(', source)
            self.assertNotIn('mo_close()', source)
            self.assertNotIn('mi_close()', source)


    def test_rejects_winding_and_machine_slot_count_mismatch(self):
        engine = make_engine(np.zeros((3, 12)))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                build_validation_script(
                    make_mesh(), engine, DEFAULT_RELATIVE_PERMEABILITIES,
                    110.0, Path(tmp))

    def test_rejects_invalid_axial_length_and_permeability(self):
        with tempfile.TemporaryDirectory() as tmp:
            for length in (0, -1, math.nan, math.inf):
                with self.subTest(length=length), self.assertRaises(ValueError):
                    build_validation_script(
                        make_mesh(), make_engine(),
                        DEFAULT_RELATIVE_PERMEABILITIES, length, Path(tmp))
            for value in (0, -1, math.nan, math.inf):
                props = dict(DEFAULT_RELATIVE_PERMEABILITIES, ur_stator=value)
                with self.subTest(ur_stator=value), self.assertRaises(ValueError):
                    build_validation_script(make_mesh(), make_engine(), props,
                                            110.0, Path(tmp))


class ExcitationTests(unittest.TestCase):
    def test_three_phase_slots_have_signed_balanced_excitation(self):
        values = slot_ampere_turns(make_engine())
        np.testing.assert_allclose(values, [40, -20, -20, -40, 20, 20],
                                   atol=1e-12)
        self.assertAlmostEqual(float(values.sum()), 0.0)

    def test_double_layer_current_is_shared_between_layers(self):
        single = make_engine()
        both = make_engine(np.vstack((single.matrix, single.matrix)))
        top_only = make_engine(np.vstack((single.matrix,
                                         np.zeros_like(single.matrix))))
        np.testing.assert_allclose(slot_ampere_turns(both),
                                   slot_ampere_turns(single))
        np.testing.assert_allclose(slot_ampere_turns(top_only),
                                   slot_ampere_turns(single) / 2)

    def test_current_turns_and_electrical_angle_affect_reference(self):
        engine = make_engine()
        baseline = slot_ampere_turns(engine)
        engine.turns *= 2
        engine.phase_current_a *= 3
        np.testing.assert_allclose(slot_ampere_turns(engine), baseline * 6)
        engine.wt_angle_deg += 180
        np.testing.assert_allclose(slot_ampere_turns(engine), -baseline * 6,
                                   atol=1e-12)

    def test_invalid_or_unbalanced_connection_matrix_is_rejected(self):
        invalid = [np.zeros((4, 6)), np.full((3, 6), math.nan),
                   np.array([[1, 0, 0, 0, 0, 0], [0] * 6, [0] * 6])]
        for matrix in invalid:
            with self.subTest(matrix=matrix), self.assertRaises(ValueError):
                slot_ampere_turns(make_engine(matrix))


class ResultsTests(unittest.TestCase):
    def parse(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'validation_results.txt'
            path.write_text(source, encoding='utf-8')
            return parse_validation_results(path)

    def test_accepts_complete_finite_results(self):
        metrics = self.parse('\n'.join(f'{key}=1.25e-3' for key in METRIC_KEYS))
        for key in METRIC_KEYS:
            self.assertEqual(metrics[key], 0.00125)

    def test_rejects_missing_or_non_numeric_results(self):
        complete = {key: '1.25e-3' for key in METRIC_KEYS}
        for missing in METRIC_KEYS:
            source = '\n'.join(f'{k}={v}' for k, v in complete.items()
                               if k != missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.parse(source)
        for bad in ('nan', 'inf', '-inf', 'broken'):
            malformed = dict(complete, airgap_br_max_t=bad)
            with self.subTest(value=bad), self.assertRaises(ValueError):
                self.parse('\n'.join(f'{k}={v}' for k, v in malformed.items()))

    def test_rejects_duplicate_and_negative_metrics(self):
        source = '\n'.join(f'{key}=1' for key in METRIC_KEYS)
        with self.assertRaises(ValueError):
            self.parse(source + '\nairgap_br_max_t=2')
        with self.assertRaises(ValueError):
            self.parse(source.replace('airgap_br_max_t=1',
                                      'airgap_br_max_t=-1'))

    def test_old_results_cannot_make_a_failed_run_look_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / 'run.lua'
            results = Path(tmp) / 'results.txt'
            script.write_text('-- no results generated', encoding='utf-8')
            results.write_text('\n'.join(f'{key}=1' for key in METRIC_KEYS),
                               encoding='utf-8')
            process = Mock(returncode=0)
            process.communicate.return_value = (b'', b'')
            process.poll.return_value = 0
            with patch('core.femm_runner.locate_femm_executable',
                       return_value='femm.exe'), \
                    patch('core.femm_runner.subprocess.Popen',
                          return_value=process), \
                    patch('core.femm_runner._windows_job', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'without generating'):
                    run_femm_script(script, results, timeout=5)
            self.assertFalse(results.exists())
            self.assertEqual(list(Path(tmp).glob('.run-femm-*.lua')), [])


class SignedProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'samples.csv'
        self.path.write_text('radius_mm,theta_deg,br_t,btheta_t\n'
                             '40,0,1,2\n40,180,-1,-2\n', encoding='utf-8')
        self.profile = np.array([[40, 0, 1, 2], [40, 180, -1, -2]], dtype=float)

    def test_opposite_polarity_cannot_pass_when_absolute_peaks_match(self):
        self.profile[:, 2:] *= -1
        result = compare_airgap_profiles(self.profile, self.path)
        self.assertAlmostEqual(result['Br']['normalized_l2_percent'], 200)
        self.assertAlmostEqual(result['Btheta']['normalized_l2_percent'], 200)

    def test_different_sampling_positions_are_rejected(self):
        self.profile[1, 1] = 179
        with self.assertRaisesRegex(ValueError, 'radii or angles'):
            compare_airgap_profiles(self.profile, self.path)

    def test_nonfinite_fields_are_rejected(self):
        self.profile[0, 2] = np.nan
        with self.assertRaisesRegex(ValueError, 'finite'):
            compare_airgap_profiles(self.profile, self.path)


class PersistentRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='femm-live-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.script = self.root / 'run.lua'
        self.script.write_text('-- interactive test', encoding='utf-8')
        self.results = self.root / 'validation_results.txt'
        self.done = self.results.with_suffix('.done.txt')
        self.error = self.results.with_suffix('.error.txt')
        self.process = Mock(returncode=None, pid=12345)
        self.process.poll.return_value = None
        self.process.communicate.return_value = (b'', b'')
        self.kernel = Mock()
        self.job = (self.kernel, 123)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('core.femm_runner.locate_femm_executable',
                                      return_value='femm.exe'))
        self.stack.enter_context(patch('core.femm_runner._windows_job',
                                      return_value=self.job))
        self.release = self.stack.enter_context(
            patch('core.femm_runner._release_windows_job'))
        self.stop = self.stack.enter_context(
            patch('core.femm_runner._stop_process_tree',
                  side_effect=self.stop_process))

    def stop_process(self, *args):
        self.process.returncode = -1
        self.process.poll.return_value = -1

    def write_metrics(self, value='1.25e-3'):
        self.results.write_text('\n'.join(f'{key}={value}' for key in METRIC_KEYS),
                                encoding='utf-8')

    def launch(self, *, value='1.25e-3', error=None, mark_done=True):
        def popen(*args, **kwargs):
            self.write_metrics(value)
            if mark_done:
                self.done.write_text('done\n', encoding='utf-8')
            if error:
                self.error.write_text(error, encoding='utf-8')
            return self.process
        return self.stack.enter_context(patch('core.femm_runner.subprocess.Popen',
                                             side_effect=popen))

    def assert_failure_keeps_process_owned_for_cleanup(self):
        self.release.assert_not_called()
        self.assertTrue(self.stop.called or self.kernel.CloseHandle.called,
                        'A failed interactive FEMM run must be terminated.')

    def test_completed_interactive_run_returns_without_closing_femm(self):
        self.launch()
        backend = run_femm_script(self.script, self.results, timeout=5,
                                  keep_open=True)
        self.assertEqual(backend, 'femm-exe')
        self.release.assert_called_once_with(self.job)
        self.stop.assert_not_called()
        self.process.kill.assert_not_called()
        self.process.terminate.assert_not_called()
        self.process.communicate.assert_not_called()

    def test_malformed_done_results_do_not_detach_femm(self):
        self.launch(value='nan')
        with self.assertRaises(ValueError):
            run_femm_script(self.script, self.results, timeout=5,
                            keep_open=True)
        self.assert_failure_keeps_process_owned_for_cleanup()

    def test_lua_error_takes_precedence_over_done_marker(self):
        self.launch(error='Intentional Lua failure')
        with self.assertRaisesRegex(RuntimeError, 'Intentional Lua failure'):
            run_femm_script(self.script, self.results, timeout=5,
                            keep_open=True)
        self.assert_failure_keeps_process_owned_for_cleanup()

    def test_timeout_of_interactive_run_still_terminates_femm(self):
        # A previous completion marker must not detach a new, unfinished run.
        self.done.write_text('stale completion\n', encoding='utf-8')
        self.launch(mark_done=False)
        with patch('core.femm_runner.time.monotonic', side_effect=count()), \
                patch('core.femm_runner.time.sleep'):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_femm_script(self.script, self.results, timeout=1,
                                keep_open=True)
        self.assert_failure_keeps_process_owned_for_cleanup()


if __name__ == '__main__':
    unittest.main()
