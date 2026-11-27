"""数据质量判据（SRS 7.4 / FR-2.2 / FR-6.2）。

这是 **强制** 判据层：所有判据由本模块统一实现，采集、效率计算、报告导出
共用同一套实现，避免"界面判一次、算法判一次"导致口径漂移。

判据表（SRS 7.4）::

    判据            阈值      动作
    传感器互差      > 10%     告警，标记不可用
    GROI 溢出       = 255     告警，提示降亮度
    GROI/Gbg        < 12      告警，提示亮度不足
    RH 差           > 5%RH    告警，该时段 η_A 排除
    分流比          > 1.05    告警，提示 B 侧重配平
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

from .types import AlarmEvent, AlarmLevel, Channel, DataFlag, GrayFrame, SampleRecord

__all__ = [
    "Thresholds",
    "DEFAULT_THRESHOLDS",
    "relative_difference",
    "check_sensor_divergence",
    "check_rh_divergence",
    "check_gray_frame",
    "check_split_ratio",
    "evaluate_sample_pair",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Thresholds:
    """判据阈值集合（FR-10.1：阈值可配置）。"""

    sensor_divergence_pct: float = 10.0
    rh_divergence_pct: float = 5.0
    split_ratio: float = 1.05
    groi_overflow: int = 255
    min_groi_gbg_ratio: float = 12.0
    r2_threshold: float = 0.95
    sds011_rh_limit: float = 70.0
    """SDS011 工作湿度上限（SRS 附录 2：RH > 70% 读数漂移，需提示）"""


#: 默认阈值（SRS 7.4）
DEFAULT_THRESHOLDS = Thresholds()


def relative_difference(a: float | None, b: float | None) -> float | None:
    """相对互差 ``|a − b| / mean(a, b) × 100%``。

    缺测时返回 ``None``。
    """
    if a is None or b is None:
        return None
    mean = (a + b) / 2.0
    if abs(mean) < 1e-12:
        return 0.0
    return abs(a - b) / abs(mean) * 100.0


def check_sensor_divergence(
    a: SampleRecord | None,
    b: SampleRecord | None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> tuple[DataFlag, str]:
    """传感器互差判据（FR-6.2）。

    :return: ``(标记位, 提示文本)``；达标时标记为空串提示
    """
    if a is None or b is None:
        return DataFlag.NONE, ""
    diff = relative_difference(a.pm25, b.pm25)
    if diff is None:
        return DataFlag.NONE, ""
    if diff > thresholds.sensor_divergence_pct:
        return (
            DataFlag.SENSOR_DIVERGENCE,
            f"两路 PM2.5 互差 {diff:.1f}% > {thresholds.sensor_divergence_pct:.0f}%，标记不可用",
        )
    return DataFlag.NONE, ""


def check_rh_divergence(
    a: SampleRecord | None,
    b: SampleRecord | None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> tuple[DataFlag, str]:
    """RH 差判据（FR-2.2 / SRS 7.4）。

    :return: ``(标记位, 提示文本)``
    """
    if a is None or b is None or a.rh is None or b.rh is None:
        return DataFlag.NONE, ""
    diff = abs(a.rh - b.rh)
    if diff > thresholds.rh_divergence_pct:
        return (
            DataFlag.RH_DIVERGENCE,
            f"A/B 两支路 RH 差 {diff:.1f}%RH > {thresholds.rh_divergence_pct:.0f}%RH，"
            "该时段 η_A 不可用",
        )
    return DataFlag.NONE, ""


def check_gray_frame(
    frame: GrayFrame,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> tuple[DataFlag, str]:
    """灰度判据（FR-6.2：GROI 溢出、GROI/Gbg 过低）。

    :return: ``(标记位, 提示文本)``
    """
    flags = DataFlag.NONE
    messages: list[str] = []
    if frame.groi >= thresholds.groi_overflow:
        flags |= DataFlag.GROI_OVERFLOW
        messages.append(f"GROI={frame.groi:.0f} 已溢出 255，提示降低灯条亮度")
    if frame.gbg and frame.groi / frame.gbg < thresholds.min_groi_gbg_ratio:
        flags |= DataFlag.INSUFFICIENT_BRIGHTNESS
        ratio = frame.groi / frame.gbg if frame.gbg else 0.0
        messages.append(f"GROI/Gbg={ratio:.1f} < {thresholds.min_groi_gbg_ratio:.0f}，提示补足亮度")
    return flags, "；".join(messages)


def check_split_ratio(
    ratio: float,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> tuple[DataFlag, str]:
    """分流比判据（SRS 7.4：> 1.05 提示 B 侧重配平）。"""
    if ratio > thresholds.split_ratio:
        return (
            DataFlag.SPLIT_RATIO_EXCEEDED,
            f"分流比 uA/uB={ratio:.3f} > {thresholds.split_ratio}，提示 B 侧重配平",
        )
    return DataFlag.NONE, ""


def evaluate_sample_pair(
    a: SampleRecord | None,
    b: SampleRecord | None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> tuple[DataFlag, list[AlarmEvent]]:
    """对同一时刻的 A/B 两条记录执行全部跨支路判据。

    :return: ``(需要叠加的标记位, 告警事件列表)``
    """
    flags = DataFlag.NONE
    alarms: list[AlarmEvent] = []

    rh_flag, rh_msg = check_rh_divergence(a, b, thresholds)
    if rh_flag:
        flags |= rh_flag
        alarms.append(
            AlarmEvent(
                ts=a.ts if a else (b.ts if b else 0.0),
                level=AlarmLevel.CRITICAL,
                code="RH_DIVERGENCE",
                message=rh_msg,
            )
        )

    div_flag, div_msg = check_sensor_divergence(a, b, thresholds)
    if div_flag:
        flags |= div_flag
        alarms.append(
            AlarmEvent(
                ts=a.ts if a else (b.ts if b else 0.0),
                level=AlarmLevel.WARNING,
                code="SENSOR_DIVERGENCE",
                message=div_msg,
            )
        )

    return flags, alarms


def sds011_rh_warning(
    rh: float | None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> str:
    """SDS011 高湿漂移提示（SRS 附录 2）。"""
    if rh is None:
        return ""
    if rh > thresholds.sds011_rh_limit:
        return f"当前 RH={rh:.0f}% 超过 SDS011 工作上限 {thresholds.sds011_rh_limit:.0f}%RH，读数可能漂移"
    return ""


def iter_alarm_levels(flags: DataFlag) -> Iterable[AlarmLevel]:
    """由标记位推出建议的告警级别（供界面统一颜色）。"""
    if flags & (DataFlag.RH_DIVERGENCE | DataFlag.SENSOR_DIVERGENCE):
        yield AlarmLevel.CRITICAL
    elif flags & (
        DataFlag.GROI_OVERFLOW
        | DataFlag.INSUFFICIENT_BRIGHTNESS
        | DataFlag.SPLIT_RATIO_EXCEEDED
        | DataFlag.DISCONNECTED
    ):
        yield AlarmLevel.WARNING
    else:
        yield AlarmLevel.INFO
