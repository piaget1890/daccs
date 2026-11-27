"""核心层：调度、事件总线、时间对齐、质量判据与应用服务。

核心层是系统的 **中枢**，它知道 device / algorithm / storage / config 各层，
但 **不认识界面**（不 import PySide6）。界面层通过
:class:`~daccs.core.service.ApplicationService` 与核心层交互。

模块清单：

* :mod:`.types` —— 数据实体（唯一事实来源）
* :mod:`.clock` —— 统一时钟源
* :mod:`.events` —— 线程安全事件总线（模块解耦装置）
* :mod:`.aligner` —— 灰度—采样时间轴对齐（SRS 5.3）
* :mod:`.quality` —— 数据质量判据（SRS 7.4）
* :mod:`.scheduler` —— 1 Hz 采集调度器（FR-1 / FR-2）
* :mod:`.selfcheck` —— 启动自检（FR-10.2）
* :mod:`.service` —— 应用服务门面（UI 唯一契约）

**本包采用惰性导入**：``daccs.core.__init__`` 不急切导入 ``service`` /
``scheduler``，因为它们会反向依赖 ``daccs.device``，而 ``daccs.device.base``
又需要 ``daccs.core.clock``——急切导入会形成循环依赖。惰性导入把这条链
打断在包边界上，保证任意导入顺序都能成功。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    # 常量与轻量类型（可直接导入）
    "now_ms",
    "EventBus",
    "Thresholds",
    "DEFAULT_THRESHOLDS",
    "AlarmEvent",
    "AlarmLevel",
    "CalibrationResult",
    "Channel",
    "DataFlag",
    "EfficiencyResult",
    "ExperimentMeta",
    "GrayFrame",
    "SampleRecord",
    # 需要反向依赖 device/storage 的重型模块（惰性）
    "ApplicationService",
    "RealtimeSnapshot",
    "AcquisitionScheduler",
]

_LAZY: dict[str, str] = {
    "now_ms": "clock",
    "EventBus": "events",
    "Thresholds": "quality",
    "DEFAULT_THRESHOLDS": "quality",
    "ApplicationService": "service",
    "RealtimeSnapshot": "service",
    "AcquisitionScheduler": "scheduler",
    "AlarmEvent": "types",
    "AlarmLevel": "types",
    "CalibrationResult": "types",
    "Channel": "types",
    "DataFlag": "types",
    "EfficiencyResult": "types",
    "ExperimentMeta": "types",
    "GrayFrame": "types",
    "SampleRecord": "types",
}


def __getattr__(name: str) -> Any:
    """按需导入子模块属性（PEP 562）。"""
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib  # noqa: PLC0415

    module = importlib.import_module(f"{__name__}.{module_name}")
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))
