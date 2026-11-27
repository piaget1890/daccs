"""灰度—浓度标定拟合（FR-7 / SRS 7.3）。

模型：``C = α·Gnorm + β``，最小二乘一元线性拟合。

* 至少需要 5 个浓度点（FR-7.1 规定 100/200/300/500/800 μg/m³ 五点）；
* 输出 ``α``、``β``、``R²``、逐点残差（FR-7.2）；
* ``R²`` 低于阈值（默认 0.95）时判定不通过，由界面层告警。

本模块只依赖 ``numpy``：``numpy.linalg.lstsq`` 已足以完成一元最小二乘，
``scipy`` 非必需依赖，降低打包体积与兼容性风险。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..core.types import CalibrationResult

__all__ = [
    "CalibrationPoint",
    "MIN_POINTS",
    "DEFAULT_R2_THRESHOLD",
    "fit_linear",
    "fit_from_pairs",
    "predicted_curve",
]

logger = logging.getLogger(__name__)

#: FR-7.1 要求的最小浓度点数
MIN_POINTS = 5

#: SRS 7.3 默认 R² 阈值
DEFAULT_R2_THRESHOLD = 0.95


@dataclass(frozen=True, slots=True)
class CalibrationPoint:
    """一个标定点。"""

    gnorm: float
    conc: float


def fit_from_pairs(
    pairs: Sequence[tuple[float, float]],
    threshold: float = DEFAULT_R2_THRESHOLD,
    source_expid: str = "",
    created_at: float = 0.0,
) -> CalibrationResult:
    """由 ``(Gnorm, 浓度)`` 点对拟合标定曲线。

    :param pairs: 点对序列，至少 :data:`MIN_POINTS` 个
    :param threshold: R² 阈值
    :param source_expid: 数据来源实验编号（FR-2.4 约束 4：标定值可回溯）
    :param created_at: 标定生成时刻（毫秒时间戳）
    :raises ValueError: 点数不足或输入非法
    """
    if len(pairs) < MIN_POINTS:
        raise ValueError(f"标定至少需要 {MIN_POINTS} 个浓度点，当前 {len(pairs)} 个")
    gnorm = np.asarray([p[0] for p in pairs], dtype=float)
    conc = np.asarray([p[1] for p in pairs], dtype=float)
    if not np.all(np.isfinite(gnorm)) or not np.all(np.isfinite(conc)):
        raise ValueError("标定点含有非有限数值")
    if np.allclose(gnorm, gnorm[0]):
        raise ValueError("Gnorm 全部相同，无法拟合")

    result = fit_linear(gnorm, conc, threshold=threshold,
                        source_expid=source_expid, created_at=created_at)
    return result


def fit_linear(
    gnorm: np.ndarray,
    conc: np.ndarray,
    threshold: float = DEFAULT_R2_THRESHOLD,
    source_expid: str = "",
    created_at: float = 0.0,
) -> CalibrationResult:
    """对已分离的数组做一元最小二乘拟合。

    ``α = Σ(x−x̄)(y−ȳ) / Σ(x−x̄)²``，``β = ȳ − α·x̄``
    ``R² = 1 − Σ残差² / Σ(y−ȳ)²``
    """
    slope, intercept = np.polyfit(gnorm, conc, 1)
    alpha = float(slope)
    beta = float(intercept)

    predicted = alpha * gnorm + beta
    residuals = conc - predicted
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((conc - conc.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")

    return CalibrationResult(
        alpha=alpha,
        beta=beta,
        r2=float(r2),
        residuals=tuple(float(r) for r in residuals),
        gnorm=tuple(float(v) for v in gnorm),
        concpoints=tuple(float(v) for v in conc),
        threshold=threshold,
        source_expid=source_expid,
        created_at=created_at,
    )


def predicted_curve(result: CalibrationResult, gnorm_values: Sequence[float]) -> list[float]:
    """按标定曲线给出预测浓度序列（用于绘图与 §7.3 复核）。"""
    return [result.predict(float(g)) for g in gnorm_values]
