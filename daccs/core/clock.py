"""统一时钟源。

SRS 2.4 约束 2：所有记录以本机时间为基准，采样点带毫秒时间戳。
SRS 5.3：灰度帧按视频帧率记录，通过最近邻与传感器时间戳对齐。

因此系统内 **只有本模块** 允许调用 ``time.time()``；其余模块一律通过
:func:`now_ms` 取时间，方便测试时替换时钟。
"""

from __future__ import annotations

import time
from typing import Callable

__all__ = ["now_ms", "monotonic", "set_time_source", "reset_time_source"]

_time_source: Callable[[], float] = time.time


def now_ms() -> float:
    """当前本机时间（毫秒，float）。"""
    return _time_source() * 1000.0


def monotonic() -> float:
    """单调时钟（秒），用于重连退避等与墙钟无关的计时。"""
    return time.monotonic()


def set_time_source(source: Callable[[], float] | None) -> None:
    """注入时间源（测试用）。``None`` 表示恢复默认墙钟。

    :param source: 返回"秒"级 epoch 浮点的可调用对象
    """
    global _time_source
    _time_source = time.time if source is None else source


def reset_time_source() -> None:
    """恢复默认墙钟。"""
    set_time_source(None)
