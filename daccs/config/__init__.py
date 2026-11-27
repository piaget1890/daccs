"""配置层：JSON 配置的模型、校验与加载（FR-10）。

本层 **不依赖** 其他内部模块，是整个依赖图的叶子之一，
保证任何模块都可以安全地读取配置而不产生循环依赖。
"""

from __future__ import annotations

from .loader import default_config_path, load_config, read_json, save_config
from .schema import (
    AcquisitionConfig,
    AppConfig,
    CalibrationConfig,
    ConfigError,
    DarkBaselineConfig,
    GCardConfig,
    ROIConfig,
    SensorConfig,
    SerialPortConfig,
    StorageConfig,
    ThresholdConfig,
    VideoConfig,
    validate,
)

__all__ = [
    "AcquisitionConfig",
    "AppConfig",
    "CalibrationConfig",
    "ConfigError",
    "DarkBaselineConfig",
    "GCardConfig",
    "ROIConfig",
    "SensorConfig",
    "SerialPortConfig",
    "StorageConfig",
    "ThresholdConfig",
    "VideoConfig",
    "default_config_path",
    "load_config",
    "read_json",
    "save_config",
    "validate",
]
