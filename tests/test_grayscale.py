"""灰度归一化单元测试（FR-4.2 / FR-4.3 / SRS 7.1 / TC-3）。"""

from __future__ import annotations

import unittest

import numpy as np

from daccs.algorithm.grayscale import (
    DarkBaseline,
    compute_gt_series,
    expand_roi,
    extract_dark_baseline,
    extract_frame_grayness,
    extract_gbg,
    extract_groi,
    normalize_gray,
    percentile_95,
)


class TestPercentile(unittest.TestCase):
    def test_95_percentile(self) -> None:
        values = list(range(101))  # 0..100
        self.assertAlmostEqual(percentile_95(values), 95.0)

    def test_empty_returns_nan(self) -> None:
        self.assertTrue(np.isnan(percentile_95([])))


class TestRoiExtraction(unittest.TestCase):
    def setUp(self) -> None:
        # 100x100 图：中央 20x20 区域亮（200），其余暗（50）
        self.frame = np.full((100, 100), 50, dtype=np.uint8)
        self.frame[40:60, 40:60] = 200
        self.roi = (40, 40, 20, 20)

    def test_groi(self) -> None:
        self.assertAlmostEqual(extract_groi(self.frame, self.roi), 200.0)

    def test_gbg_is_background_percentile(self) -> None:
        """Gbg 取外扩环带（扣除 ROI 自身）的 95 百分位，即周边背景值。

        若把 ROI 一起算进去，ROI 在 2 倍外扩框中恒占 25% 面积，
        95 百分位必然落在 ROI 上，Gnorm 将恒为 100。
        """
        gbg = extract_gbg(self.frame, self.roi)
        self.assertAlmostEqual(gbg, 50.0)

    def test_expand_roi_doubles_size(self) -> None:
        rows, cols = expand_roi(self.roi, self.frame.shape)
        self.assertEqual(rows.stop - rows.start, 40)
        self.assertEqual(cols.stop - cols.start, 40)

    def test_expand_roi_clipped_to_image(self) -> None:
        rows, cols = expand_roi((0, 0, 20, 20), (100, 100))
        self.assertGreaterEqual(rows.start, 0)
        self.assertGreaterEqual(cols.start, 0)
        self.assertLessEqual(rows.stop, 100)
        self.assertLessEqual(cols.stop, 100)

    def test_normalize_ratio(self) -> None:
        self.assertAlmostEqual(normalize_gray(50.0, 100.0), 50.0)

    def test_normalize_with_dark_baseline(self) -> None:
        """扣暗电流基线：分子分母同时扣除（SRS 7.1）。"""
        result = normalize_gray(60.0, 120.0, DarkBaseline(roi=10.0, bg=20.0))
        self.assertAlmostEqual(result, (60.0 - 10.0) / (120.0 - 20.0) * 100.0)

    def test_normalize_zero_denominator_is_nan(self) -> None:
        self.assertTrue(np.isnan(normalize_gray(10.0, 0.0)))

    def test_frame_grayness(self) -> None:
        frame = extract_frame_grayness(self.frame, self.roi, None, ts=1000.0, frame_index=3)
        self.assertEqual(frame.frame_index, 3)
        self.assertAlmostEqual(frame.groi, 200.0)
        self.assertAlmostEqual(frame.gbg, 50.0)
        self.assertAlmostEqual(frame.gnorm, 400.0)

    def test_dark_baseline_extraction(self) -> None:
        dark = np.full((100, 100), 7, dtype=np.uint8)
        baseline = extract_dark_baseline([dark, dark, dark], self.roi)
        self.assertAlmostEqual(baseline.roi, 7.0)
        self.assertAlmostEqual(baseline.bg, 7.0)


class TestGtSeries(unittest.TestCase):
    def test_gt_series(self) -> None:
        """gt = (Gnorm,t − Gnorm,b) / (Gnorm,0 − Gnorm,b)（仅定性）。

        归一化端点：背景基线 b → 0，零颗粒物参考 0 → 1。
        """
        series = [10.0, 30.0, 50.0]
        gt = compute_gt_series(series, gnorm_baseline=10.0, gnorm_zero=50.0)
        self.assertAlmostEqual(gt[0], 0.0)
        self.assertAlmostEqual(gt[1], 0.5)
        self.assertAlmostEqual(gt[2], 1.0)

    def test_zero_denominator_returns_nan(self) -> None:
        gt = compute_gt_series([1.0, 2.0], gnorm_baseline=10.0, gnorm_zero=10.0)
        self.assertTrue(all(np.isnan(v) for v in gt))


if __name__ == "__main__":
    unittest.main()
