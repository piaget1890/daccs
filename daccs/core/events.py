"""线程安全的事件总线（模块解耦的关键装置）。

设计意图
--------
采集、视频、存储、界面四个模块 **互不直接调用**，全部通过本总线交换数据：

* ``device`` / ``algorithm`` 只负责产生"事实"（话题：``sample``、``gray``…）；
* ``core.scheduler`` 负责把事实聚合成批次（话题：``sample.batch``）；
* ``storage`` 订阅批次写盘；
* ``ui`` 订阅批次刷新界面。

这样带来的直接收益：

1. 界面崩溃不会影响采集（FR-10 / NFR-2）；
2. 存储层可以整体替换（例如换成 SQLite）而不触碰采集层；
3. 单元测试可以只订阅某几个话题做断言，无需启动整套系统；
4. 总线不依赖任何 GUI 框架，``core`` 层保持纯 Python（见 NFR-3 可移植性）。

本模块刻意 **不引入 Qt**。界面层在 :mod:`daccs.ui.workers` 中把总线事件
桥接为 Qt 信号，从而满足"GUI 只能在 UI 线程改控件"的约束。
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable, Iterable

__all__ = ["EventBus", "Topic", "Subscription"]

logger = logging.getLogger(__name__)

#: 常用话题常量（字符串常量优于裸字符串，避免拼写漂移）。
Topic = str


class Subscription:
    """订阅句柄：持有它即可取消订阅。"""

    __slots__ = ("_bus", "_topic", "_callback", "_cancelled")

    def __init__(self, bus: "EventBus", topic: str, callback: Callable[[Any], None]) -> None:
        self._bus = bus
        self._topic = topic
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        """取消订阅（幂等）。"""
        if not self._cancelled:
            self._bus.unsubscribe(self._topic, self._callback)
            self._cancelled = True

    def __enter__(self) -> "Subscription":
        return self

    def __exit__(self, *exc: object) -> None:
        self.cancel()


class EventBus:
    """同步、线程安全的多路事件总线。

    回调在 **发布者线程** 中同步执行。采集线程若执行耗时回调会拖慢采集，
    因此约定：耗时工作（写盘、绘图）由订阅方自行把工作丢给自己的队列/线程。
    回调内部抛出的异常会被记录但不会中断发布者。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> Subscription:
        """订阅话题。

        :param topic: 话题名；支持前缀通配，如 ``"sample.*"``
        :param callback: 接收单个载荷的可调用对象
        :return: :class:`Subscription` 句柄
        """
        with self._lock:
            self._subscribers[topic].append(callback)
        return Subscription(self, topic, callback)

    def unsubscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        """取消订阅（幂等）。"""
        with self._lock:
            handlers = self._subscribers.get(topic)
            if handlers and callback in handlers:
                handlers.remove(callback)

    def publish(self, topic: str, payload: Any) -> int:
        """发布事件。

        :return: 实际收到事件的订阅者数量
        """
        with self._lock:
            handlers = list(self._subscribers.get(topic, ()))
            for pattern in list(self._subscribers):
                if pattern.endswith(".*") and pattern[:-2] and topic.startswith(pattern[:-2]):
                    handlers.extend(self._subscribers[pattern])

        for handler in handlers:
            try:
                handler(payload)
            except Exception:  # noqa: BLE001 - 订阅者异常不得影响发布者
                logger.exception("事件订阅者异常 topic=%s handler=%r", topic, handler)
        return len(handlers)

    def subscriber_count(self, topic: str) -> int:
        """某话题（含通配）的订阅者数量，用于自检与测试。"""
        with self._lock:
            count = len(self._subscribers.get(topic, ()))
            for pattern, handlers in self._subscribers.items():
                if pattern.endswith(".*") and pattern[:-2] and topic.startswith(pattern[:-2]):
                    count += len(handlers)
            return count

    def topics(self) -> Iterable[str]:
        """当前已注册的话题名。"""
        with self._lock:
            return tuple(self._subscribers.keys())
