"""效率计算与数据质量判据单元测试（FR-8 / SRS 7.2 / 7.4 / TC-5）。"""

from __future__ import annotations

import unittest

from daccs.algorithm.efficiency import (
    cumulative_volume,
    compute_efficiency,
    eta_a,
)
from daccs.core.quality import (
    check_gray_frame,
    check_rh_divergence,
    check_sensor_divergence,
    check_split_ratio,
    relative_difference,
)
from daccs.core.types import Channel, DataFlag, GrayFrame, SampleRecord


def sample(ts: float, ch: Channel = Channel.A, pm25=None, rh=None, flag=DataFlag.NONE) -> SampleRecord:
    return SampleRecord(ts=ts, ch=ch, pm25=pm25, rh=rh, flag=flag)


class TestEtaA(unittest.TestCase):
    def test_formula(self) -> None:
        """η_A = 1 − C_A,out / C_feed。"""
        self.assertAlmostEqual(eta_a(100.0, 20.0), 0.8)

    def test_none_inputs(self) -> None:
        self.assertIsNone(eta_a(None, 20.0))
        self.assertIsNone(eta_a(100.0, None))

    def test_non_positive_feed(self) -> None:
        self.assertIsNone(eta_a(0.0, 20.0))
        self.assertIsNone(eta_a(-10.0, 20.0))


class TestComputeEfficiency(unittest.TestCase):
    def test_valid_series(self) -> None:
        records = [
            sample(1000.0, pm25=10.0),
            sample(2000.0, pm25=20.0),
            sample(3000.0, pm25=30.0),
        ]
        series = compute_efficiency(records, cfeed=100.0)
        self.assertEqual(len(series.results), 3)
        self.assertAlmostEqual(series.results[0].etaa, 0.9)
        self.assertTrue(all(r.valid for r in series.results))
        self.assertEqual(series.valid_ratio, 1.0)

    def test_invalid_interval_is_excluded_with_reason(self) -> None:
        """FR-8.3：不达标区间自动排除并说明。"""
        records = [
            sample(1000.0, pm25=10.0),
            sample(2000.0, pm25=20.0, flag=DataFlag.RH_DIVERGENCE),
            sample(3000.0, pm25=30.0, flag=DataFlag.RH_DIVERGENCE),
            sample(4000.0, pm25=40.0),
        ]
        series = compute_efficiency(records, cfeed=100.0)
        self.assertFalse(series.results[1].valid)
        self.assertFalse(series.results[2].valid)
        self.assertIsNone(series.results[1].etaa)
        self.assertIn("RH", series.results[1].reason)
        self.assertEqual(len(series.invalid_intervals), 1)
        self.assertAlmostEqual(series.valid_ratio, 0.5)

    def test_only_channel_a_is_used(self) -> None:
        records = [
            sample(1000.0, Channel.A, pm25=10.0),
            sample(1000.0, Channel.B, pm25=90.0),
        ]
        series = compute_efficiency(records, cfeed=100.0)
        self.assertEqual(len(series.results), 1)

    def test_callable_cfeed(self) -> None:
        records = [sample(1000.0, pm25=50.0)]
        series = compute_efficiency(records, cfeed=lambda ts: 100.0)
        self.assertAlmostEqual(series.results[0].etaa, 0.5)


class TestCumulativeVolume(unittest.TestCase):
    def test_linear_accumulation(self) -> None:
        """u = 72 m³/h，10 s → 0.2 m³。"""
        volumes = cumulative_volume([0.0, 10_000.0], [72.0, 72.0])
        self.assertAlmostEqual(volumes[0], 0.0)
        self.assertAlmostEqual(volumes[1], 0.2)

    def test_length_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            cumulative_volume([0.0], [1.0, 2.0])


class TestQualityCriteria(unittest.TestCase):
    def test_relative_difference(self) -> None:
        """相对互差 = |a − b| / mean(a, b) × 100%。"""
        self.assertAlmostEqual(relative_difference(100.0, 110.0), 10.0 / 105.0 * 100.0)
        self.assertIsNone(relative_difference(None, 110.0))

    def test_sensor_divergence_threshold(self) -> None:
        """FR-6.2：互差 > 10% 告警。"""
        a = sample(0.0, Channel.A, pm25=100.0)
        b = sample(0.0, Channel.B, pm25=120.0)
        flag, message = check_sensor_divergence(a, b)
        self.assertTrue(flag & DataFlag.SENSOR_DIVERGENCE)
        self.assertIn("互差", message)

        flag, message = check_sensor_divergence(a, sample(0.0, Channel.B, pm25=105.0))
        self.assertFalse(flag & DataFlag.SENSOR_DIVERGENCE)

    def test_rh_divergence_threshold(self) -> None:
        """FR-2.2：RH 差 > 5%RH 触发。"""
        a = sample(0.0, Channel.A, rh=50.0)
        b = sample(0.0, Channel.B, rh=56.0)
        flag, message = check_rh_divergence(a, b)
        self.assertTrue(flag & DataFlag.RH_DIVERGENCE)
        self.assertIn("RH", message)

    def test_groi_overflow_and_low_brightness(self) -> None:
        """FR-6.2：GROI=255 溢出、GROI/Gbg < 12 亮度不足。"""
        flag, message = check_gray_frame(GrayFrame(ts=0.0, groi=255.0, gbg=200.0, gnorm=127.5))
        self.assertTrue(flag & DataFlag.GROI_OVERFLOW)
        self.assertIn("亮度", message)

        flag, message = check_gray_frame(GrayFrame(ts=0.0, groi=10.0, gbg=200.0, gnorm=5.0))
        self.assertTrue(flag & DataFlag.INSUFFICIENT_BRIGHTNESS)

    def test_split_ratio_threshold(self) -> None:
        """SRS 7.4：分流比 > 1.05 告警。"""
        flag, message = check_split_ratio(1.10)
        self.assertTrue(flag & DataFlag.SPLIT_RATIO_EXCEEDED)
        self.assertIn("配平", message)

        flag, _ = check_split_ratio(1.02)
        self.assertFalse(flag & DataFlag.SPLIT_RATIO_EXCEEDED)


if __name__ == "__main__":
    unittest.main()
