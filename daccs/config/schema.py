"""配置模型与校验（FR-10.1 / FR-10.2）。

配置文件为 JSON（UTF-8），涵盖：串口号、波特率、传感器 ID、ROI 坐标、
阈值、标定系数等。

设计原则：

* **有 schema**：配置以 dataclass 表达，缺字段走默认值，多余字段进 ``extra``，
  非法值在加载阶段就报错，避免运行到一半才崩（FR-10.2 配置合法性自检）；
* **只读运行期**：配置对象加载后视为不可变快照，运行期修改走
  :meth:`AppConfig.with_overrides`，避免多线程读到半个配置。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "SerialPortConfig",
    "SensorConfig",
    "VideoConfig",
    "ROIConfig",
    "DarkBaselineConfig",
    "ThresholdConfig",
    "CalibrationConfig",
    "StorageConfig",
    "AcquisitionConfig",
    "GCardConfig",
    "AppConfig",
    "ConfigError",
    "validate",
]


class ConfigError(ValueError):
    """配置非法。"""


@dataclass(slots=True)
class SerialPortConfig:
    """一路串口设备的配置。"""

    port: str = ""
    baudrate: int = 9600
    timeout: float = 0.2
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SerialPortConfig":
        return cls(
            port=str(data.get("port", "")),
            baudrate=int(data.get("baudrate", 9600)),
            timeout=float(data.get("timeout", 0.2)),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "baudrate": self.baudrate,
            "timeout": self.timeout,
            "enabled": self.enabled,
        }


@dataclass(slots=True)
class SensorConfig:
    """一路传感器的配置（SDS011 / SHT31 / AM2302 / RS485 变送器）。"""

    kind: str = "sds011"
    name: str = ""
    channel: str = "A"
    device_id: int = 0
    serial: SerialPortConfig = field(default_factory=SerialPortConfig)
    address: str = ""
    unit_id: int = 1
    function_code: int = 3
    register: int = 0
    scale: float = 1.0
    offset: float = 0.0
    quantity: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SensorConfig":
        return cls(
            kind=str(data.get("kind", "sds011")),
            name=str(data.get("name", "")),
            channel=str(data.get("channel", "A")),
            device_id=int(data.get("device_id", 0)),
            serial=SerialPortConfig.from_dict(data.get("serial", {})),
            address=str(data.get("address", "")),
            unit_id=int(data.get("unit_id", 1)),
            function_code=int(data.get("function_code", 3)),
            register=int(data.get("register", 0)),
            scale=float(data.get("scale", 1.0)),
            offset=float(data.get("offset", 0.0)),
            quantity=str(data.get("quantity", "")),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "channel": self.channel,
            "device_id": self.device_id,
            "serial": self.serial.to_dict(),
            "address": self.address,
            "unit_id": self.unit_id,
            "function_code": self.function_code,
            "register": self.register,
            "scale": self.scale,
            "offset": self.offset,
            "quantity": self.quantity,
            "enabled": self.enabled,
        }


@dataclass(slots=True)
class VideoConfig:
    """视频源配置（FR-4.1）。"""

    target: str = ""
    is_camera: bool = False
    camera_index: int = 0
    fps: float | None = 30.0
    enabled: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VideoConfig":
        fps_raw = data.get("fps", 30.0)
        return cls(
            target=str(data.get("target", "")),
            is_camera=bool(data.get("is_camera", False)),
            camera_index=int(data.get("camera_index", 0)),
            fps=None if fps_raw is None else float(fps_raw),
            enabled=bool(data.get("enabled", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "is_camera": self.is_camera,
            "camera_index": self.camera_index,
            "fps": self.fps,
            "enabled": self.enabled,
        }


@dataclass(slots=True)
class ROIConfig:
    """ROI 与外扩参数（FR-4.1 / SRS 7.1）。"""

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    expand_factor: float = 2.0

    @property
    def is_set(self) -> bool:
        return self.w > 0 and self.h > 0

    @property
    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ROIConfig":
        return cls(
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            w=int(data.get("w", 0)),
            h=int(data.get("h", 0)),
            expand_factor=float(data.get("expand_factor", 2.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "expand_factor": self.expand_factor,
        }


@dataclass(slots=True)
class DarkBaselineConfig:
    """暗电流基线（FR-4.3）。"""

    roi: float = 0.0
    bg: float = 0.0
    frames: int = 10

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DarkBaselineConfig":
        return cls(
            roi=float(data.get("roi", 0.0)),
            bg=float(data.get("bg", 0.0)),
            frames=int(data.get("frames", 10)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"roi": self.roi, "bg": self.bg, "frames": self.frames}


@dataclass(slots=True)
class ThresholdConfig:
    """判据阈值（SRS 7.4 / FR-10.1）。"""

    sensor_divergence_pct: float = 10.0
    rh_divergence_pct: float = 5.0
    split_ratio: float = 1.05
    groi_overflow: int = 255
    min_groi_gbg_ratio: float = 12.0
    r2_threshold: float = 0.95
    sds011_rh_limit: float = 70.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ThresholdConfig":
        return cls(
            sensor_divergence_pct=float(data.get("sensor_divergence_pct", 10.0)),
            rh_divergence_pct=float(data.get("rh_divergence_pct", 5.0)),
            split_ratio=float(data.get("split_ratio", 1.05)),
            groi_overflow=int(data.get("groi_overflow", 255)),
            min_groi_gbg_ratio=float(data.get("min_groi_gbg_ratio", 12.0)),
            r2_threshold=float(data.get("r2_threshold", 0.95)),
            sds011_rh_limit=float(data.get("sds011_rh_limit", 70.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(slots=True)
class CalibrationConfig:
    """标定系数（FR-10.1：标定系数入配置；FR-2.4 约束 4：可回溯）。"""

    alpha: float = 0.0
    beta: float = 0.0
    r2: float = 0.0
    threshold: float = 0.95
    source_expid: str = ""
    updated_at: float = 0.0
    valid: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibrationConfig":
        return cls(
            alpha=float(data.get("alpha", 0.0)),
            beta=float(data.get("beta", 0.0)),
            r2=float(data.get("r2", 0.0)),
            threshold=float(data.get("threshold", 0.95)),
            source_expid=str(data.get("source_expid", "")),
            updated_at=float(data.get("updated_at", 0.0)),
            valid=bool(data.get("valid", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(slots=True)
class StorageConfig:
    """存储路径配置（SRS 9.2 目录结构）。"""

    base_dir: str = "."
    raw_dir: str = "data/raw"
    report_dir: str = "data/report"
    log_dir: str = "logs"
    gray_dir: str = "data/raw"
    flush_interval_s: float = 1.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StorageConfig":
        return cls(
            base_dir=str(data.get("base_dir", ".")),
            raw_dir=str(data.get("raw_dir", "data/raw")),
            report_dir=str(data.get("report_dir", "data/report")),
            log_dir=str(data.get("log_dir", "logs")),
            gray_dir=str(data.get("gray_dir", "data/raw")),
            flush_interval_s=float(data.get("flush_interval_s", 1.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(slots=True)
class AcquisitionConfig:
    """采集节奏（SRS 2.4 约束 1：1 s 周期）。"""

    period_s: float = 1.0
    align_tolerance_ms: float = 500.0
    reconnect_initial_s: float = 0.5
    reconnect_max_s: float = 5.0
    reconnect_factor: float = 2.0
    cfeed: float = 0.0
    """稳流腔参考浓度 Cfeed（μg/m³），用于 η_A 预估值与效率计算。0 表示未配置。"""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AcquisitionConfig":
        return cls(
            period_s=float(data.get("period_s", 1.0)),
            align_tolerance_ms=float(data.get("align_tolerance_ms", 500.0)),
            reconnect_initial_s=float(data.get("reconnect_initial_s", 0.5)),
            reconnect_max_s=float(data.get("reconnect_max_s", 5.0)),
            reconnect_factor=float(data.get("reconnect_factor", 2.0)),
            cfeed=float(data.get("cfeed", 0.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(slots=True)
class GCardConfig:
    """灰卡二次线性校正（FR-4.5，可选开关）。"""

    enabled: bool = False
    reference: float | None = None
    sensitivity: float = 1.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GCardConfig":
        ref = data.get("reference", None)
        return cls(
            enabled=bool(data.get("enabled", False)),
            reference=None if ref is None else float(ref),
            sensitivity=float(data.get("sensitivity", 1.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "reference": self.reference,
            "sensitivity": self.sensitivity,
        }


@dataclass(slots=True)
class AppConfig:
    """系统总配置。"""

    sensors: list[SensorConfig] = field(default_factory=list)
    video: VideoConfig = field(default_factory=VideoConfig)
    roi: ROIConfig = field(default_factory=ROIConfig)
    dark_baseline: DarkBaselineConfig = field(default_factory=DarkBaselineConfig)
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    acquisition: AcquisitionConfig = field(default_factory=AcquisitionConfig)
    gcard: GCardConfig = field(default_factory=GCardConfig)
    uncertainty_note: str = (
        "传感器壁面采样 ±10%~15%；灰度—浓度非线性，本结果不替代标准方法结论。"
    )
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AppConfig":
        known = {
            "sensors", "video", "roi", "dark_baseline", "thresholds",
            "calibration", "storage", "acquisition", "gcard", "uncertainty_note",
        }
        return cls(
            sensors=[SensorConfig.from_dict(s) for s in data.get("sensors", [])],
            video=VideoConfig.from_dict(data.get("video", {})),
            roi=ROIConfig.from_dict(data.get("roi", {})),
            dark_baseline=DarkBaselineConfig.from_dict(data.get("dark_baseline", {})),
            thresholds=ThresholdConfig.from_dict(data.get("thresholds", {})),
            calibration=CalibrationConfig.from_dict(data.get("calibration", {})),
            storage=StorageConfig.from_dict(data.get("storage", {})),
            acquisition=AcquisitionConfig.from_dict(data.get("acquisition", {})),
            gcard=GCardConfig.from_dict(data.get("gcard", {})),
            uncertainty_note=str(data.get("uncertainty_note", AppConfig.uncertainty_note)),
            extra={k: v for k, v in data.items() if k not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "sensors": [s.to_dict() for s in self.sensors],
            "video": self.video.to_dict(),
            "roi": self.roi.to_dict(),
            "dark_baseline": self.dark_baseline.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "calibration": self.calibration.to_dict(),
            "storage": self.storage.to_dict(),
            "acquisition": self.acquisition.to_dict(),
            "gcard": self.gcard.to_dict(),
            "uncertainty_note": self.uncertainty_note,
        }
        data.update(self.extra)
        return data

    def with_overrides(self, **overrides: Any) -> "AppConfig":
        """返回叠加了部分覆盖值的 **新** 配置（保持原对象不可变）。"""
        base = self.to_dict()
        for key, value in overrides.items():
            if isinstance(value, Mapping) and isinstance(base.get(key), Mapping):
                merged = dict(base[key])
                merged.update(value)
                base[key] = merged
            else:
                base[key] = value
        return AppConfig.from_dict(base)

    def sensor_by_name(self, name: str) -> SensorConfig | None:
        for sensor in self.sensors:
            if sensor.name == name:
                return sensor
        return None


def validate(config: AppConfig) -> list[str]:
    """校验配置合法性（FR-10.2 自检）。

    :return: 问题列表，空列表表示通过
    """
    problems: list[str] = []

    if not config.sensors:
        problems.append("未配置任何传感器")
    seen_names: set[str] = set()
    for sensor in config.sensors:
        if not sensor.name:
            problems.append("存在未命名的传感器配置")
        if sensor.name in seen_names:
            problems.append(f"传感器名称重复：{sensor.name}")
        seen_names.add(sensor.name)
        if sensor.channel not in ("A", "B"):
            problems.append(f"{sensor.name}: 通道必须是 A 或 B")
        if sensor.kind == "sds011" and sensor.enabled and not sensor.serial.port:
            problems.append(f"{sensor.name}: SDS011 串口号为空")
        if sensor.kind == "sds011" and sensor.serial.baudrate != 9600:
            problems.append(f"{sensor.name}: SDS011 波特率应为 9600")
        if sensor.kind == "rs485" and sensor.enabled and not sensor.serial.port:
            problems.append(f"{sensor.name}: RS485 串口号为空")
        if sensor.kind == "rs485" and sensor.function_code not in (0x03, 0x04):
            problems.append(f"{sensor.name}: Modbus 功能码必须为 0x03/0x04")

    if config.roi.is_set:
        if config.roi.expand_factor < 1.0:
            problems.append("ROI 外扩倍数不得小于 1.0")
    elif config.video.enabled:
        problems.append("已启用视频但未设置 ROI 坐标")

    if config.thresholds.rh_divergence_pct <= 0:
        problems.append("RH 差阈值必须为正")
    if config.thresholds.split_ratio <= 0:
        problems.append("分流比阈值必须为正")
    if config.acquisition.period_s <= 0:
        problems.append("采集周期必须为正")
    if not config.uncertainty_note.strip():
        problems.append("不确定度声明不可为空（SRS 2.4 约束 5）")

    return problems


def dump_json(config: AppConfig, path: str | Path, indent: int = 2) -> Path:
    """把配置写回 JSON 文件（UTF-8）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=indent), encoding="utf-8"
    )
    return target
