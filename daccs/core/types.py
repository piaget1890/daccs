"""核心数据实体（对应 SRS 5.1 数据实体）。

本模块是整个系统唯一的事实来源（single source of truth）：

* ``device`` 层把原始设备数据解析成这里的实体；
* ``core`` 层负责调度、对齐、判定，并把实体广播给订阅者；
* ``storage`` 层负责把实体落盘/读回；
* ``ui`` 层只读取实体做展示，不自行拼装数据。

约定：

* 所有时间戳统一为 **本机时间的毫秒级 float**（见 :mod:`daccs.core.clock`）；
* 数值缺测一律用 ``None`` 表示，禁止用 0 代替，避免把"缺测"算成"浓度为零"；
* ``flag`` 采用位掩码（:class:`DataFlag`），可叠加多个数据质量标记。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from enum import Flag, IntEnum, StrEnum
from typing import Any, Iterable, Sequence

__all__ = [
    "Channel",
    "DataFlag",
    "SampleRecord",
    "ExperimentMeta",
    "CalibrationResult",
    "EfficiencyResult",
    "GrayFrame",
    "AlarmEvent",
    "AlarmLevel",
]


class Channel(StrEnum):
    """A/B 两支路。"""

    A = "A"
    B = "B"


class AlarmLevel(StrEnum):
    """告警级别，对应 FR-6.2 / NFR-4 的颜色 + 文字双提示。"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class DataFlag(Flag):
    """数据质量标记位（SRS 7.4 数据质量判据）。

    标记只追加、不清除：一条记录一旦被判定为不合格，后续算法必须保留该标记，
    以便 FR-8.3 能够"自动排除并说明"。
    """

    NONE = 0
    #: FR-2.2 RH 差 > 5%RH，该时段 η_A 不可用
    RH_DIVERGENCE = 1 << 0
    #: FR-6.2 两路传感器互差 > 10%
    SENSOR_DIVERGENCE = 1 << 1
    #: FR-6.2 GROI 溢出（== 255），提示降亮度
    GROI_OVERFLOW = 1 << 2
    #: FR-6.2 GROI/Gbg < 12，提示亮度不足
    INSUFFICIENT_BRIGHTNESS = 1 << 3
    #: FR-3.3 分流比 > 1.05，提示 B 侧重配平
    SPLIT_RATIO_EXCEEDED = 1 << 4
    #: FR-1.4 串口断线/重连期间产生的记录
    DISCONNECTED = 1 << 5
    #: 采样时灰度帧未能在 ±0.5 s 内对齐
    GRAY_UNALIGNED = 1 << 6
    #: FR-8.3 效率计算中该区间被判为无效
    EFFICIENCY_EXCLUDED = 1 << 7
    #: 人工在界面上标记为需要复核
    MANUAL_REVIEW = 1 << 8

    @property
    def codes(self) -> list[str]:
        """返回置位标记的可读代号列表（写 CSV 用）。"""
        return [f.name for f in DataFlag if f.value and f in self]


@dataclass(frozen=True, slots=True)
class SampleRecord:
    """一条对齐后的采样记录（SRS 5.1 ``samplerecord``）。

    :param ts: 毫秒时间戳（本机时间基准）
    :param ch: 支路 A/B
    :param pm25: PM2.5 浓度 μg/m³
    :param pm10: PM10 浓度 μg/m³
    :param rh: 相对湿度 %RH
    :param temp: 温度 ℃
    :param gnorm: 归一化灰度（Gnorm，FR-4.3）
    :param flag: 数据质量标记位
    :param wind_speed_ms: 风速 m/s（FR-3.1 在线变送器 / FR-3.2 离线量具录入）
    :param dp_pa: 单元压降 Δplung Pa（FR-3 / FR-7.4）
    """

    ts: float
    ch: Channel
    pm25: float | None = None
    pm10: float | None = None
    rh: float | None = None
    temp: float | None = None
    gnorm: float | None = None
    flag: DataFlag = DataFlag.NONE
    wind_speed_ms: float | None = None
    dp_pa: float | None = None

    @property
    def ts_iso(self) -> str:
        """本机时间可读形式（毫秒精度），用于报告与回放标注。"""
        return format_ts(self.ts)

    @property
    def is_valid(self) -> bool:
        """是否不含任何致命标记（仅 RH 分歧/传感器互差等按判据屏蔽）。"""
        fatal = (
            DataFlag.RH_DIVERGENCE
            | DataFlag.SENSOR_DIVERGENCE
            | DataFlag.GROI_OVERFLOW
            | DataFlag.INSUFFICIENT_BRIGHTNESS
            | DataFlag.DISCONNECTED
        )
        return not (self.flag & fatal)

    def with_flag(self, *flags: DataFlag) -> "SampleRecord":
        """返回叠加了额外标记的新记录（原记录不可变）。"""
        new_flag = self.flag
        for f in flags:
            new_flag |= f
        return replace(self, flag=new_flag)

    def to_row(self) -> list[Any]:
        """转成 CSV 行，字段顺序与 FR-5.1 一致。

        字段：时间戳、通道、PM2.5、PM10、RH、T、Gnorm、标记位，
        并附加 FR-3.2 要求的在线/离线风速与压降列。
        """
        return [
            self.ts_iso,
            self.ch.value,
            _fmt(self.pm25),
            _fmt(self.pm10),
            _fmt(self.rh),
            _fmt(self.temp),
            _fmt(self.gnorm),
            ";".join(self.flag.codes),
            _fmt(self.wind_speed_ms, 4),
            _fmt(self.dp_pa, 4),
        ]


@dataclass(frozen=True, slots=True)
class GrayFrame:
    """视频灰度提取的一帧结果（FR-4.2 / FR-4.3）。

    :param ts: 帧时间戳（毫秒）
    :param groi: ROI 内 95 百分位灰度
    :param gbg: ROI 外扩 2 倍区域 95 百分位灰度
    :param gnorm: 归一化灰度 = GROI/Gbg×100（已扣暗电流基线）
    :param frame_index: 帧序号
    :param gcard_value: 画面内灰卡读数（FR-4.5 二次线性校正，可为 None）
    """

    ts: float
    groi: float
    gbg: float
    gnorm: float
    frame_index: int = 0
    gcard_value: float | None = None

    def to_row(self) -> list[Any]:
        """转成 CSV 行（FR-4.4 逐帧 Gnorm 时间序列）。"""
        return [
            self.ts_iso,
            self.frame_index,
            _fmt(self.groi, 3),
            _fmt(self.gbg, 3),
            _fmt(self.gnorm, 4),
            _fmt(self.gcard_value, 3),
        ]

    @property
    def ts_iso(self) -> str:
        return format_ts(self.ts)


@dataclass(slots=True)
class ExperimentMeta:
    """实验元数据（FR-5.2 / SRS 5.1 ``experimentmeta``）。"""

    expid: str
    date: str
    smokesource: str = ""
    valve: str = ""
    ledlevel: str = ""
    operator: str = ""
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expid": self.expid,
            "date": self.date,
            "smokesource": self.smokesource,
            "valve": self.valve,
            "ledlevel": self.ledlevel,
            "operator": self.operator,
            "note": self.note,
            **self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentMeta":
        known = {"expid", "date", "smokesource", "valve", "ledlevel", "operator", "note"}
        return cls(
            expid=str(data.get("expid", "")),
            date=str(data.get("date", "")),
            smokesource=str(data.get("smokesource", "")),
            valve=str(data.get("valve", "")),
            ledlevel=str(data.get("ledlevel", "")),
            operator=str(data.get("operator", "")),
            note=str(data.get("note", "")),
            extra={k: v for k, v in data.items() if k not in known},
        )


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """灰度—浓度标定拟合结果（FR-7.2 / SRS 5.1 ``calibration``）。

    模型：``C = α·Gnorm + β``
    """

    alpha: float
    beta: float
    r2: float
    residuals: tuple[float, ...] = ()
    gnorm: tuple[float, ...] = ()
    concpoints: tuple[float, ...] = ()
    threshold: float = 0.95
    source_expid: str = ""
    created_at: float = 0.0

    @property
    def passed(self) -> bool:
        """R² 是否达到阈值（FR-7.2 低于阈值告警）。"""
        return self.r2 >= self.threshold

    def predict(self, gnorm: float) -> float:
        """用标定曲线预测浓度。"""
        return self.alpha * gnorm + self.beta

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha,
            "beta": self.beta,
            "r2": self.r2,
            "residuals": list(self.residuals),
            "gnorm": list(self.gnorm),
            "concpoints": list(self.concpoints),
            "threshold": self.threshold,
            "source_expid": self.source_expid,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class EfficiencyResult:
    """单程效率计算结果（SRS 5.1 ``efficiencyresult``）。"""

    ts: float
    cfeed: float | None
    ca_out: float | None
    etaa: float | None
    valid: bool = True
    flag: DataFlag = DataFlag.NONE
    reason: str = ""

    @property
    def ts_iso(self) -> str:
        return format_ts(self.ts)


@dataclass(frozen=True, slots=True)
class AlarmEvent:
    """告警事件（FR-6.2 / FR-6.2 颜色+文字双提示）。"""

    ts: float
    level: AlarmLevel
    code: str
    message: str
    ch: Channel | None = None

    @property
    def ts_iso(self) -> str:
        return format_ts(self.ts)


def _fmt(value: float | None, digits: int = 3) -> str:
    """统一的浮点格式化；``None`` 输出空串（Excel 友好）。"""
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return f"{value:.{digits}f}"


def format_ts(ts: float) -> str:
    """毫秒时间戳 -> ``YYYY-MM-DD HH:MM:SS.mmm`` 本机时间字符串。"""
    import datetime as _dt

    dt = _dt.datetime.fromtimestamp(ts / 1000.0)
    return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def to_records(rows: Iterable[SampleRecord]) -> Sequence[SampleRecord]:
    """便捷函数：物化迭代器，便于测试断言。"""
    return list(rows)
