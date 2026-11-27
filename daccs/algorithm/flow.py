"""分流比与压降判据（FR-3.3 / FR-7.3 / FR-7.4 / SRS 7.4）。

* 分流比 ``uA / uB``，判定阈值 1.05（SRS 7.4 表）
* 单元压降 ``Δplung`` 与阈值 0.5 Pa 比较（SRS FR-7.4）
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "SPLIT_RATIO_THRESHOLD",
    "PLUNGE_DP_THRESHOLD",
    "REQUIRED_POINTS",
    "SplitRatioResult",
    "PlungeDpResult",
    "compute_split_ratio",
    "evaluate_plunge_dp",
]

logger = logging.getLogger(__name__)

#: SRS 7.4：分流比 > 1.05 告警，提示 B 侧重配平
SPLIT_RATIO_THRESHOLD = 1.05

#: FR-7.4：单元压降阈值 0.5 Pa
PLUNGE_DP_THRESHOLD = 0.5

#: FR-3.3 / FR-7.3：两支路各 3 点读数
REQUIRED_POINTS = 3


@dataclass(frozen=True, slots=True)
class SplitRatioResult:
    """分流比计算结果。"""

    mean_a: float
    mean_b: float
    ratio: float
    passed: bool
    points_a: tuple[float, ...] = ()
    points_b: tuple[float, ...] = ()
    threshold: float = SPLIT_RATIO_THRESHOLD

    def to_dict(self) -> dict[str, object]:
        return {
            "mean_a": self.mean_a,
            "mean_b": self.mean_b,
            "ratio": self.ratio,
            "passed": self.passed,
            "points_a": list(self.points_a),
            "points_b": list(self.points_b),
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class PlungeDpResult:
    """单元压降判据结果。"""

    dp_pa: float
    passed: bool
    threshold: float = PLUNGE_DP_THRESHOLD
    suggestion: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "dp_pa": self.dp_pa,
            "passed": self.passed,
            "threshold": self.threshold,
            "suggestion": self.suggestion,
        }


def compute_split_ratio(
    velocities_a: Sequence[float],
    velocities_b: Sequence[float],
    threshold: float = SPLIT_RATIO_THRESHOLD,
) -> SplitRatioResult:
    """计算两支路分流比（FR-3.3 / FR-7.3）。

    :param velocities_a: A 支路风速读数（m/s），建议 3 点
    :param velocities_b: B 支路风速读数（m/s），建议 3 点
    :param threshold: 判定阈值，默认 1.05
    :raises ValueError: 点数不足或读数非法
    """
    if len(velocities_a) < REQUIRED_POINTS or len(velocities_b) < REQUIRED_POINTS:
        raise ValueError(
            f"分流比需要两支路各至少 {REQUIRED_POINTS} 点读数"
            f"（A={len(velocities_a)}, B={len(velocities_b)}）"
        )
    if any(v <= 0 for v in velocities_a) or any(v <= 0 for v in velocities_b):
        raise ValueError("风速读数必须为正值")

    mean_a = statistics.fmean(velocities_a)
    mean_b = statistics.fmean(velocities_b)
    ratio = mean_a / mean_b
    return SplitRatioResult(
        mean_a=mean_a,
        mean_b=mean_b,
        ratio=ratio,
        passed=ratio <= threshold,
        points_a=tuple(float(v) for v in velocities_a),
        points_b=tuple(float(v) for v in velocities_b),
        threshold=threshold,
    )


def evaluate_plunge_dp(
    dp_pa: float,
    threshold: float = PLUNGE_DP_THRESHOLD,
) -> PlungeDpResult:
    """单元压降判据（FR-7.4）：与 0.5 Pa 比较并提示是否需要加稳定网。

    :param dp_pa: 微差压计读数 Δplung（Pa）
    :param threshold: 阈值，默认 0.5 Pa
    """
    passed = dp_pa < threshold
    suggestion = "" if passed else "Δplung 超阈值，建议加装稳定网后复测"
    return PlungeDpResult(
        dp_pa=dp_pa, passed=passed, threshold=threshold, suggestion=suggestion
    )
