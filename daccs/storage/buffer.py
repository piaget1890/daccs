"""内存滚动缓冲（FR-6.3：60 s 滚动曲线）。

用 ``collections.deque`` 实现定长环形窗口：

* 采集线程写入（高频）；
* GUI 线程读取快照（低频）—— 读取返回 **拷贝**，避免跨线程迭代中被修改。
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Iterable, Iterator

from ..core.types import SampleRecord

__all__ = ["RollingBuffer"]


class RollingBuffer:
    """定长滚动缓冲。

    :param maxlen: 最大保留条数
    :param window_s: 时间窗口长度（秒），用于按时间裁剪
    """

    def __init__(self, maxlen: int = 3600, window_s: float = 60.0) -> None:
        self.maxlen = maxlen
        self.window_s = window_s
        self._items: deque[SampleRecord] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, record: SampleRecord) -> None:
        """追加一条记录。"""
        with self._lock:
            self._items.append(record)

    def extend(self, records: Iterable[SampleRecord]) -> None:
        """批量追加。"""
        with self._lock:
            self._items.extend(records)

    def snapshot(self) -> list[SampleRecord]:
        """返回当前内容的拷贝（线程安全）。"""
        with self._lock:
            return list(self._items)

    def window(self, now_ms: float | None = None) -> list[SampleRecord]:
        """返回最近 ``window_s`` 秒内的记录。

        :param now_ms: 基准时间戳；``None`` 表示使用最新一条记录的时间
        """
        with self._lock:
            items = list(self._items)
        if not items:
            return []
        if now_ms is None:
            now_ms = items[-1].ts
        cutoff = now_ms - self.window_s * 1000.0
        return [item for item in items if item.ts >= cutoff]

    def clear(self) -> None:
        """清空缓冲。"""
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __iter__(self) -> Iterator[SampleRecord]:
        return iter(self.snapshot())
