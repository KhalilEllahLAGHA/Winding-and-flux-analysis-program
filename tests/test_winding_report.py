"""Report angles and factors agree with the modeled coil geometry."""

import math
import unittest

from core.winding_analysis import (calculate_winding_factors,
                                    generate_winding_explanation,
                                    slots_per_pole_per_phase)


class WindingReportTests(unittest.TestCase):
    def test_default_angle_and_full_pitch_percentage_use_actual_poles(self):
        report = generate_winding_explanation(
            36, 4, 9, True, slots_per_pole_per_phase(36, 4))
        self.assertIn('Electrical angle between slots: 20.0°', report)
        self.assertIn('Coil pitch: 100.0% of pole pitch', report)

    def test_default_factors_have_no_unprovided_skew_correction(self):
        factors = calculate_winding_factors(36, 4, 9)
        # Three coil axes separated by 20 electrical degrees per phase belt.
        kd = math.sin(math.radians(30)) / (3 * math.sin(math.radians(10)))
        self.assertAlmostEqual(factors['distribution'], kd, places=12)
        self.assertEqual(factors['pitch'], 1.0)
        self.assertEqual(factors['skew'], 1.0)
        self.assertAlmostEqual(factors['total'], kd, places=12)

    def test_short_pitch_factor_and_report_percentage_agree(self):
        factors = calculate_winding_factors(36, 4, 6)
        self.assertAlmostEqual(factors['pitch'], math.sin(math.radians(60)))
        self.assertAlmostEqual(factors['total'],
                               factors['distribution'] * factors['pitch'])
        report = generate_winding_explanation(
            36, 4, 6, True, slots_per_pole_per_phase(36, 4))
        self.assertIn('Coil pitch: 66.7% of pole pitch', report)

    def test_fractional_distribution_uses_the_actual_single_or_double_layout(self):
        single = calculate_winding_factors(24, 10, 2, False)
        double = calculate_winding_factors(24, 10, 2, True)
        self.assertAlmostEqual(single['distribution'], math.cos(math.radians(7.5)))
        self.assertAlmostEqual(double['distribution'],
                               math.cos(math.radians(7.5)) * math.cos(math.radians(15)))
        self.assertAlmostEqual(single['pitch'], math.sin(math.radians(75)))
        self.assertAlmostEqual(double['pitch'], single['pitch'])

    def test_zero_excitation_pitch_has_finite_distribution_and_zero_total(self):
        factors = calculate_winding_factors(36, 4, 18)
        self.assertEqual(factors['pitch'], 0.0)
        self.assertEqual(factors['total'], 0.0)
        self.assertTrue(math.isfinite(factors['distribution']))

    def test_unsupported_layout_explains_unavailable_factors_without_throwing(self):
        factors = calculate_winding_factors(18, 4, 4, False)
        self.assertIsNone(factors['distribution'])
        self.assertIsNone(factors['total'])
        self.assertIn('odd number', factors['error'])
        report = generate_winding_explanation(
            18, 4, 4, False, slots_per_pole_per_phase(18, 4))
        self.assertIn('not available for this layout', report)
        self.assertIn('odd number', report)


if __name__ == '__main__':
    unittest.main()
