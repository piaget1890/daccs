"""分流比、压降与时间轴对齐单元测试（FR-3.3 / FR-7.3 / FR-7.4 / SRS 5.3）。"""

from __future__ import annotations

import unittest

from daccs.algorithm.flow import (
    compute_split_ratio,
    evaluate_plunge_dp,
)
from daccs.core.aligner import align_frames_to_samples, nearest_index
from daccs.core.types import Channel, DataFlag, GrayFrame, SampleRecord


class TestSplitRatio(unittest.TestCase):
    def test_balanced_branches(self) -> None:
        result = compute_split_ratio([1.0, 1.1, 0.9], [1.0, 1.0, 1.0])
        self.assertAlmostEqual(result.mean_a, 1.0)
        self.assertAlmostEqual(result.ratio, 1.0)
        self.assertTrue(result.passed)

    def test_unbalanced_branches_flagged(self) -> None:
        """SRS 7.4：uA/uB > 1.05 判不合格。"""
        result = compute_split_ratio([1.2, 1.2, 1.2], [1.0, 1.0, 1.0])
        self.assertAlmostEqual(result.ratio, 1.2)
        self.assertFalse(result.passed)

    def test_requires_three_points(self) -> None:
        with self.assertRaises(ValueError):
            compute_split_ratio([1.0, 1.0], [1.0, 1.0, 1.0])

    def test_rejects_non_positive(self) -> None:
        with self.assertRaises(ValueError):
            compute_split_ratio([1.0, 0.0, 1.0], [1.0, 1.0, 1.0])


class TestPlungeDp(unittest.TestCase):
    def test_below_threshold_passes(self) -> None:
        result = evaluate_plunge_dp(0.3)
        self.assertTrue(result.passed)
        self.assertEqual(result.suggestion, "")

    def test_above_threshold_suggests_mesh(self) -> None:
        """FR-7.4：超阈值提示是否需加稳定网。"""
        result = evaluate_plunge_dp(0.8)
        self.assertFalse(result.passed)
        self.assertIn("稳定网", result.suggestion)


class TestNearestIndex(unittest.TestCase):
    def test_nearest(self) -> None:
        idx, error = nearest_index([0.0, 1000.0, 2000.0], 950.0)
        self.assertEqual(idx, 1)
        self.assertAlmostEqual(error, 50.0)

    def test_empty(self) -> None:
        idx, error = nearest_index([], 100.0)
        self.assertEqual(idx, -1)
        self.assertEqual(error, float("inf"))


class TestAligner(unittest.TestCase):
    def test_nearest_neighbor_within_tolerance(self) -> None:
        samples = [
            SampleRecord(ts=1000.0, ch=Channel.A, pm25=10.0),
            SampleRecord(ts=2000.0, ch=Channel.A, pm25=20.0),
        ]
        frames = [
            GrayFrame(ts=1100.0, groi=200.0, gbg=100.0, gnorm=200.0),
            GrayFrame(ts=1900.0, groi=210.0, gbg=100.0, gnorm=210.0),
        ]
        aligned, summary = align_frames_to_samples(samples, frames)
        self.assertEqual(summary.matched, 2)
        self.assertAlmostEqual(aligned[0].gnorm, 200.0)
        self.assertAlmostEqual(aligned[1].gnorm, 210.0)

    def test_out_of_tolerance_marked_unaligned(self) -> None:
        """SRS 5.3：对齐误差 ≤ ±0.5 s，超出则标记。"""
        samples = [SampleRecord(ts=1000.0, ch=Channel.A, pm25=10.0)]
        frames = [GrayFrame(ts=3000.0, groi=200.0, gbg=100.0, gnorm=200.0)]
        aligned, summary = align_frames_to_samples(samples, frames)
        self.assertEqual(summary.matched, 0)
        self.assertTrue(aligned[0].flag & DataFlag.GRAY_UNALIGNED)

    def test_frame_not_reused(self) -> None:
        samples = [
            SampleRecord(ts=1000.0, ch=Channel.A),
            SampleRecord(ts=1010.0, ch=Channel.A),
        ]
        frames = [GrayFrame(ts=1005.0, groi=200.0, gbg=100.0, gnorm=200.0)]
        aligned, summary = align_frames_to_samples(samples, frames)
        self.assertEqual(summary.matched, 1)
        self.assertEqual(sum(1 for a in aligned if a.gnorm is not None), 1)

    def test_empty_inputs(self) -> None:
        aligned, summary = align_frames_to_samples([], [])
        self.assertEqual(aligned, [])
        self.assertEqual(summary.matched, 0)


if __name__ == "__main__":
    unittest.main()
