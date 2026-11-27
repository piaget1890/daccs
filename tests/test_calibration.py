"""标定拟合单元测试（FR-7.1 / FR-7.2 / TC-4）。"""

from __future__ import annotations

import unittest

from daccs.algorithm.calibration import (
    DEFAULT_R2_THRESHOLD,
    MIN_POINTS,
    fit_from_pairs,
    fit_linear,
    predicted_curve,
)


class TestFitFromPairs(unittest.TestCase):
    def test_perfect_linear_fit(self) -> None:
        """C = 10·Gnorm + 5 的完美线性数据应给出 R² = 1。"""
        gnorm = [10.0, 20.0, 30.0, 40.0, 50.0]
        conc = [105.0, 205.0, 305.0, 405.0, 505.0]
        result = fit_from_pairs(list(zip(gnorm, conc)))
        self.assertAlmostEqual(result.alpha, 10.0, places=6)
        self.assertAlmostEqual(result.beta, 5.0, places=6)
        self.assertAlmostEqual(result.r2, 1.0, places=9)
        self.assertTrue(result.passed)

    def test_requires_five_points(self) -> None:
        """FR-7.1：至少 5 个浓度点。"""
        with self.assertRaises(ValueError):
            fit_from_pairs([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0)])
        self.assertEqual(MIN_POINTS, 5)

    def test_rejects_constant_gnorm(self) -> None:
        with self.assertRaises(ValueError):
            fit_from_pairs([(1.0, 1.0)] * 5)

    def test_rejects_non_finite(self) -> None:
        with self.assertRaises(ValueError):
            fit_from_pairs([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0), (float("nan"), 5.0)])

    def test_low_r2_triggers_alarm_state(self) -> None:
        """R² 低于阈值时 passed 为 False（FR-7.2 告警）。"""
        gnorm = [1.0, 2.0, 3.0, 4.0, 5.0]
        conc = [1.0, 100.0, 2.0, 110.0, 3.0]
        result = fit_from_pairs(list(zip(gnorm, conc)), threshold=DEFAULT_R2_THRESHOLD)
        self.assertLess(result.r2, DEFAULT_R2_THRESHOLD)
        self.assertFalse(result.passed)

    def test_residuals_length_matches_points(self) -> None:
        gnorm = [1.0, 2.0, 3.0, 4.0, 5.0]
        conc = [2.0, 4.0, 6.0, 8.0, 10.0]
        result = fit_from_pairs(list(zip(gnorm, conc)))
        self.assertEqual(len(result.residuals), 5)
        self.assertEqual(len(result.gnorm), 5)
        self.assertEqual(len(result.concpoints), 5)

    def test_source_expid_is_recorded(self) -> None:
        """SRS 2.4 约束 4：标定值可回溯。"""
        gnorm = [1.0, 2.0, 3.0, 4.0, 5.0]
        conc = [2.0, 4.0, 6.0, 8.0, 10.0]
        result = fit_from_pairs(list(zip(gnorm, conc)), source_expid="EXP-001")
        self.assertEqual(result.source_expid, "EXP-001")


class TestPredict(unittest.TestCase):
    def test_predict_matches_model(self) -> None:
        result = fit_from_pairs([(1.0, 3.0), (2.0, 5.0), (3.0, 7.0), (4.0, 9.0), (5.0, 11.0)])
        self.assertAlmostEqual(result.predict(6.0), 13.0, places=6)
        curve = predicted_curve(result, [1.0, 2.0])
        self.assertEqual(len(curve), 2)


if __name__ == "__main__":
    unittest.main()
