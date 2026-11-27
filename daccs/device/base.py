"""设备驱动基类与断线重连策略（FR-1.4）。

:class:`Driver` 抽象了三类设备的共性：

* ``open()`` —— 建立物理链路；
* ``read()`` —— 读取一次，返回 :mod:`daccs.core.types` 中的标准实体（可为空）；
* ``close()`` —— 释放资源。

具体差异（串口 / I2C / 单总线 / 视频）由子类实现。

重连策略（FR-1.4：指数退避，最长 5 s 间隔）集中在 :class:`ReconnectPolicy`，
避免每个驱动各写一遍退避逻辑。
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..core.clock import monotonic
from ..core.types import SampleRecord

__all__ = ["Driver", "DriverError", "ReconnectPolicy", "SerialTransport", "ReconnectEvent"]

logger = logging.getLogger(__name__)


class DriverError(RuntimeError):
    """驱动层异常（串口不存在、协议错误、连接中断…）。"""


@dataclass(frozen=True, slots=True)
class ReconnectEvent:
    """一次重连事件，供日志与界面展示（FR-1.4 "重连后恢复采集并记录事件"）。"""

    attempt: int
    delay_s: float
    reason: str


@runtime_checkable
class SerialTransport(Protocol):
    """串口传输抽象。

    抽象出来是为了让 :mod:`daccs.device.sds011` 不直接依赖 ``pyserial``，
    单测时可注入假传输；同时隔离了 Windows/Linux 串口差异（NFR-3）。
    """

    def read(self, size: int) -> bytes:
        """读取至多 ``size`` 字节；无数据返回 ``b""``。"""

    def write(self, data: bytes) -> int:
        """写入字节，返回实际写入长度。"""

    def close(self) -> None:
        """关闭链路。"""


@dataclass(slots=True)
class ReconnectPolicy:
    """指数退避重连策略（FR-1.4）。

    间隔序列：``initial * factor^(n-1)``，上限 ``max_delay``，并带 ±20% 抖动
    以避免两路串口同时重连造成的冲击。

    :param initial: 首次重连等待秒数
    :param factor: 退避倍数
    :param max_delay: 最大等待秒数（FR-1.4 规定 5 s）
    :param max_attempts: 最大重试次数，``0`` 表示无限重试
    :param jitter: 抖动比例（0 表示不加抖动，便于测试）
    """

    initial: float = 0.5
    factor: float = 2.0
    max_delay: float = 5.0
    max_attempts: int = 0
    jitter: float = 0.2
    _attempts: int = field(default=0, init=False)

    def next_delay(self) -> float:
        """返回本次重连的等待秒数，并推进退避计数。"""
        delay = min(self.max_delay, self.initial * (self.factor ** max(0, self._attempts)))
        self._attempts += 1
        if self.jitter:
            delay *= 1.0 + random.uniform(-self.jitter, self.jitter)
        return max(0.0, delay)

    def reset(self) -> None:
        """链路恢复后重置退避计数。"""
        self._attempts = 0

    @property
    def attempts(self) -> int:
        return self._attempts

    def exhausted(self) -> bool:
        """是否已达最大重试次数。"""
        return self.max_attempts > 0 and self._attempts >= self.max_attempts


class Driver(ABC):
    """所有设备驱动的抽象基类。"""

    #: 驱动名称，用于日志与自检报告（FR-10.2）
    name: str = "driver"

    def __init__(self) -> None:
        self._connected = False
        self.policy = ReconnectPolicy()
        self.reconnect_events: list[ReconnectEvent] = []

    @property
    def connected(self) -> bool:
        """当前链路是否可用。"""
        return self._connected

    @abstractmethod
    def open(self) -> None:
        """建立链路。失败时抛出 :class:`DriverError`。"""

    @abstractmethod
    def read(self) -> list[SampleRecord]:
        """读取一次并返回本周期产生的记录（可能为空列表）。"""

    def close(self) -> None:
        """释放链路，默认无需处理。"""
        self._connected = False

    def reconnect(self, reason: str = "") -> ReconnectEvent | None:
        """按退避策略重连一次。

        :return: 重连事件；若已达最大重试次数返回 ``None``
        """
        if self.policy.exhausted():
            logger.warning("%s 重连次数已达上限 %d", self.name, self.policy.max_attempts)
            return None
        delay = self.policy.next_delay()
        event = ReconnectEvent(attempt=self.policy.attempts, delay_s=delay, reason=reason)
        self.reconnect_events.append(event)
        logger.warning("%s 断线，第 %d 次重连，等待 %.2fs：%s",
                       self.name, event.attempt, delay, reason)
        try:
            self.close()
            self.open()
        except DriverError as exc:
            logger.error("%s 重连失败：%s", self.name, exc)
            return event
        self.policy.reset()
        self._connected = True
        return event

    def __enter__(self) -> "Driver":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
