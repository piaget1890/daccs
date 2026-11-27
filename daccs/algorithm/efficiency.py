"""效率计算与累计处理量（FR-8 / SRS 7.2）。

* 单程效率：``η_A = 1 − C_A,out / C_feed``（FR-8.1）
* 累计处理量：``V(t) = Σ u_i · Δt_i``（FR-8.2 的 η–累计处理量曲线）
* 数据质量判据联动：不达标区间自动置 ``valid=False`` 并记录原因（FR-8.3）

``C_feed``（稳流腔参考浓度）可以来自：

* 配置中的常量（``float``）；
* 随时间变化的实测值（可调用对象 ``f(ts) -> float``）。

界面层不直接调用本模块，而是通过 :class:`daccs.core.service.ApplicationService`
调用，从而保持 UI → core → algorithm 的单向依赖（NFR-7 分层要求）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from ..core.types import Channel, DataFlag, EfficiencyResult, SampleRecord

__all__ = [
    "eta_a",
    "compute_efficiency",
    "cumulative_volume",
    "EfficiencySeries",
    "InvalidInterval",
]

logger = logging.getLogger(__name__)

#: 使效率结果失效的判据（FR-2.2 / FR-6.2 / SRS 7.4）
INVALIDATING_FLAGS = (
    DataFlag.RH_DIVERGENCE,
    DataFlag.SENSOR_DIVERGENCE,
    DataFlag.GROI_OVERFLOW,
    DataFlag.INSUFFICIENT_BRIGHTNESS,
    DataFlag.DISCONNECTED,
    DataFlag.GRAY_UNALIGNED,
)

_FLAG_REASONS: dict[DataFlag, str] = {
    DataFlag.RH_DIVERGENCE: "RH 差 > 5%RH，该时段不用于 η_A（FR-2.2）",
    DataFlag.SENSOR_DIVERGENCE: "两路传感器互差 > 10%（FR-6.2）",
    DataFlag.GROI_OVERFLOW: "GROI 溢出 255，提示降亮度（FR-6.2）",
    DataFlag.INSUFFICIENT_BRIGHTNESS: "GROI/Gbg < 12，提示亮度不足（FR-6.2）",
    DataFlag.DISCONNECTED: "采集链路断线/重连期间（FR-1.4）",
    DataFlag.GRAY_UNALIGNED: "灰度帧未能在 ±0.5 s 内对齐（SRS 5.3）",
}


@dataclass(frozen=True, slots=True)
class InvalidInterval:
    """被排除的区间及其原因（FR-8.3 "不达标区间自动排除并说明"）。"""

    start_ts: float
    end_ts: float
    reason: str
    flag: DataFlag

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.end_ts - self.start_ts) / 1000.0)


@dataclass(slots=True)
class EfficiencySeries:
    """效率计算的整体结果。"""

    results: list[EfficiencyResult]
    invalid_intervals: list[InvalidInterval]
    valid_ratio: float

    def valid_values(self) -> list[float]:
        """仅取有效 η_A。"""
        return [r.etaa for r in self.results if r.valid and r.etaa is not None]


def eta_a(cfeed: float | None, ca_out: float | None) -> float | None:
    """单程效率 ``η_A = 1 − C_A,out / C_feed``。

    :param cfeed: 稳流腔参考浓度 μg/m³
    :param ca_out: A 支路出口浓度 μg/m³
    :return: η_A；输入非法或 ``C_feed <= 0`` 时返回 ``None``
    """
    if cfeed is None or ca_out is None:
        return None
    if cfeed <= 0:
        logger.warning("C_feed 非正（%s），η_A 无效", cfeed)
        return None
    return 1.0 - float(ca_out) / float(cfeed)


def _resolve_cfeed(cfeed: float | Callable[[float], float | None], ts: float) -> float | None:
    if callable(cfeed):
        return cfeed(ts)
    return cfeed


def compute_efficiency(
    samples: Iterable[SampleRecord],
    cfeed: float | Callable[[float], float | None],
    channel: Channel = Channel.A,
    rh_divergence: dict[float, bool] | None = None,
) -> EfficiencySeries:
    """由 A 支路采样序列计算 η_A 时间序列。

    :param samples: 采样记录（可含 A/B 两路，按 ``channel`` 过滤）
    :param cfeed: 参考浓度，常量或 ``f(ts)`` 可调用对象
    :param channel: 计算用支路（η_A 取 A 支路出口浓度）
    :param rh_divergence: 额外传入的 RH 分歧时间戳集合（键为 ms 时间戳），
        用于把 B 支路的 RH 差判据施加到 A 支路记录上
    :return: :class:`EfficiencySeries`
    """
    ordered = sorted(
        (s for s in samples if s.ch == channel), key=lambda s: s.ts
    )

    results: list[EfficiencyResult] = []
    intervals: list[InvalidInterval] = []
    _current: tuple[float, str, DataFlag] | None = None

    def _close_interval() -> None:
        nonlocal _current
        if _current is not None:
            start, reason, flag = _current
            intervals.append(InvalidInterval(start, results[-1].ts, reason, flag))
            _current = None

    for sample in ordered:
        flag = sample.flag
        reason = ""
        for invalid_flag, text in _FLAG_REASONS.items():
            if flag & invalid_flag:
                reason = text
                break
        if reason == "" and rh_divergence and rh_divergence.get(sample.ts):
            flag = flag | DataFlag.RH_DIVERGENCE
            reason = _FLAG_REASONS[DataFlag.RH_DIVERGENCE]

        valid = reason == ""
        if not valid:
            if _current is None:
                _current = (sample.ts, reason, flag)
        else:
            _close_interval()

        feed = _resolve_cfeed(cfeed, sample.ts)
        out = sample.pm25
        value = eta_a(feed, out) if valid else None
        results.append(
            EfficiencyResult(
                ts=sample.ts,
                cfeed=feed,
                ca_out=out,
                etaa=value,
                valid=valid,
                flag=flag,
                reason=reason,
            )
        )

    _close_interval()
    total = len(results)
    valid_ratio = (sum(1 for r in results if r.valid) / total) if total else 0.0
    return EfficiencySeries(
        results=results, invalid_intervals=intervals, valid_ratio=valid_ratio
    )


def cumulative_volume(
    timestamps_ms: Sequence[float],
    flow_m3h: Sequence[float],
) -> list[float]:
    """累计处理量曲线（FR-8.2）。

    ``V(t_i) = V(t_{i-1}) + u_{i-1} · (t_i − t_{i-1}) / 3600``，``u`` 单位 m³/h，
    输出单位 m³。

    :param timestamps_ms: 递增的毫秒时间戳
    :param flow_m3h: 与时间戳一一对应的体积流量 m³/h
    """
    if len(timestamps_ms) != len(flow_m3h):
        raise ValueError("时间戳与流速序列长度不一致")
    volumes: list[float] = []
    acc = 0.0
    for i in range(len(timestamps_ms)):
        if i == 0:
            volumes.append(0.0)
            continue
        dt_s = max(0.0, (timestamps_ms[i] - timestamps_ms[i - 1]) / 1000.0)
        acc += max(0.0, float(flow_m3h[i - 1])) * dt_s / 3600.0
        volumes.append(acc)
    return volumes
