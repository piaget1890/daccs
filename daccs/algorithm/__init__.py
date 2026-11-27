"""算法层：灰度归一化、标定拟合、效率计算、分流比与统计。

本层是 **纯计算** 模块：不读设备、不写文件、不依赖 GUI，
只依赖 ``numpy``。所有函数都可用固定输入验证，便于单元测试（NFR-7）。
"""

from __future__ import annotations

from .calibration import (
    DEFAULT_R2_THRESHOLD,
    MIN_POINTS,
    CalibrationPoint,
    fit_from_pairs,
    fit_linear,
)
from .efficiency import (
    EfficiencySeries,
    InvalidInterval,
    cumulative_volume,
    compute_efficiency,
    eta_a,
)
from .flow import (
    PLUNGE_DP_THRESHOLD,
    SPLIT_RATIO_THRESHOLD,
    PlungeDpResult,
    SplitRatioResult,
    compute_split_ratio,
    evaluate_plunge_dp,
)
from .grayscale import (
    DarkBaseline,
    ROI,
    apply_gcard_correction,
    compute_gt_series,
    expand_roi,
    extract_dark_baseline,
    extract_frame_grayness,
    extract_gbg,
    extract_groi,
    normalize_gray,
    percentile_95,
)
from .metrics import NumericSummary, summarize, summarize_series

__all__ = [
    "CalibrationPoint",
    "MIN_POINTS",
    "DEFAULT_R2_THRESHOLD",
    "fit_from_pairs",
    "fit_linear",
    "EfficiencySeries",
    "InvalidInterval",
    "cumulative_volume",
    "compute_efficiency",
    "eta_a",
    "PLUNGE_DP_THRESHOLD",
    "SPLIT_RATIO_THRESHOLD",
    "PlungeDpResult",
    "SplitRatioResult",
    "compute_split_ratio",
    "evaluate_plunge_dp",
    "DarkBaseline",
    "ROI",
    "apply_gcard_correction",
    "compute_gt_series",
    "expand_roi",
    "extract_dark_baseline",
    "extract_frame_grayness",
    "extract_gbg",
    "extract_groi",
    "normalize_gray",
    "percentile_95",
    "NumericSummary",
    "summarize",
    "summarize_series",
]
