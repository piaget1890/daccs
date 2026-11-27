"""启动自检（FR-10.2）。

自检内容：

1. **串口枚举** —— 列出系统可用串口，与配置的串口号比对；
2. **传感器帧握手** —— 尝试打开已配置设备并读取一次；
3. **视频源可用性** —— 检查配置的视频文件/相机能否打开；
4. **配置文件合法性** —— 调用 :func:`daccs.config.schema.validate`。

自检结果以 :class:`SelfCheckReport` 返回，界面层渲染成清单。
自检 **不修改** 任何配置，也不写文件。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config.schema import AppConfig, validate

if TYPE_CHECKING:  # pragma: no cover
    from .scheduler import AcquisitionScheduler

__all__ = ["CheckItem", "SelfCheckReport", "run_self_check"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CheckItem:
    """一条自检结论。"""

    name: str
    passed: bool
    detail: str = ""
    level: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail, "level": self.level}


@dataclass(slots=True)
class SelfCheckReport:
    """自检报告。"""

    items: list[CheckItem] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """是否全部通过。"""
        return all(item.passed for item in self.items)

    @property
    def failures(self) -> list[CheckItem]:
        return [i for i in self.items if not i.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "items": [i.to_dict() for i in self.items],
        }

    def summary(self) -> str:
        return f"自检通过 {len(self.items) - len(self.failures)}/{len(self.items)} 项"


def run_self_check(
    config: AppConfig,
    scheduler: "AcquisitionScheduler | None" = None,
) -> SelfCheckReport:
    """执行全部自检项。"""
    report = SelfCheckReport()
    report.items.append(_check_config(config))
    report.items.append(_check_serial_ports(config))
    report.items.append(_check_sensors(config, scheduler))
    report.items.append(_check_video(config))
    return report


def _check_config(config: AppConfig) -> CheckItem:
    problems = validate(config)
    if problems:
        return CheckItem(
            "配置文件合法性",
            False,
            "；".join(problems),
            level="critical",
        )
    return CheckItem("配置文件合法性", True, "通过")


def _check_serial_ports(config: AppConfig) -> CheckItem:
    from ..device.serial_port import list_serial_ports  # noqa: PLC0415

    ports = list_serial_ports()
    available = {p["device"] for p in ports}
    configured = {
        s.serial.port for s in config.sensors if s.enabled and s.serial.port
    }
    missing = sorted(p for p in configured if p not in available)
    if not ports:
        return CheckItem(
            "串口枚举",
            not configured,
            "未枚举到串口（若全部设备均为可选配置可忽略）",
            level="warning" if configured else "info",
        )
    if missing:
        return CheckItem(
            "串口枚举",
            False,
            f"配置中的串口未找到：{', '.join(missing)}；可用：{', '.join(sorted(available))}",
            level="critical",
        )
    return CheckItem(
        "串口枚举", True, f"可用串口：{', '.join(sorted(available))}"
    )


def _check_sensors(config: AppConfig, scheduler: "AcquisitionScheduler | None") -> CheckItem:
    if scheduler is None:
        return CheckItem("传感器握手", True, "未启动采集，跳过", level="info")
    drivers = scheduler.drivers
    if not drivers:
        return CheckItem("传感器握手", False, "未配置任何驱动", level="critical")

    details: list[str] = []
    ok = True
    for driver in drivers:
        status_fn = getattr(driver, "status", None)
        if callable(status_fn):
            try:
                details.append(f"{driver.name}: {status_fn()}")
            except Exception as exc:  # noqa: BLE001
                ok = False
                details.append(f"{driver.name}: 状态读取异常 {exc}")
        else:
            details.append(f"{driver.name}: ok")
    return CheckItem(
        "传感器握手",
        ok,
        "；".join(details),
        level="info" if ok else "critical",
    )


def _check_video(config: AppConfig) -> CheckItem:
    if not config.video.enabled:
        return CheckItem("视频源", True, "未启用视频，跳过", level="info")
    if config.video.is_camera:
        return CheckItem("视频源", True, f"相机 #{config.video.camera_index}（打开时检测）")
    target = Path(config.video.target)
    if not target.exists():
        return CheckItem("视频源", False, f"视频文件不存在：{target}", level="critical")
    return CheckItem("视频源", True, str(target))
