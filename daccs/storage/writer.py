"""采样 CSV 追加写入器（FR-5.1 / SRS 6.4）。

字段顺序固定（与 FR-5.1 一致）::

    时间戳, 通道, PM2.5, PM10, RH, T, Gnorm, 标记位, 风速, 压降

**只追加**：文件以 ``a`` 模式打开，若文件不存在才写表头。
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Iterable, Sequence

from ..core.types import GrayFrame, SampleRecord

__all__ = ["SAMPLE_CSV_HEADER", "GRAY_CSV_HEADER", "CsvAppendWriter", "GrayCsvWriter"]

logger = logging.getLogger(__name__)

#: 采样 CSV 表头
SAMPLE_CSV_HEADER: Sequence[str] = (
    "时间戳",
    "通道",
    "PM2.5(ug/m3)",
    "PM10(ug/m3)",
    "RH(%RH)",
    "T(C)",
    "Gnorm",
    "标记位",
    "风速(m/s)",
    "压降(Pa)",
)

#: 灰度 CSV 表头（FR-4.4）
GRAY_CSV_HEADER: Sequence[str] = (
    "时间戳",
    "帧序号",
    "GROI",
    "Gbg",
    "Gnorm",
    "灰卡读数",
)


class CsvAppendWriter:
    """带缓冲落盘的 CSV 追加写入器。

    :param path: 目标 CSV 路径
    :param header: 表头（文件为空时写入）
    :param flush_interval_s: 自动 flush 间隔（NFR-6）
    :param encoding: 默认 ``utf-8-sig``（带 BOM，Excel 可直接打开）
    """

    def __init__(
        self,
        path: str | Path,
        header: Sequence[str] = SAMPLE_CSV_HEADER,
        flush_interval_s: float = 1.0,
        encoding: str = "utf-8-sig",
    ) -> None:
        self.path = Path(path)
        self.header = tuple(header)
        self.flush_interval_s = flush_interval_s
        self.encoding = encoding
        self._queue: Queue[list[str]] = Queue()
        # RLock：close() 会持锁调用 flush()，flush() 再次取锁，必须可重入
        self._lock = threading.RLock()
        self._fh = None
        self._last_flush = 0.0
        self.rows_written = 0

    # ------------------------------------------------------------------ 生命周期

    def _ensure_open(self):
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            exists = self.path.exists() and self.path.stat().st_size > 0
            self._fh = open(self.path, "a", encoding=self.encoding, newline="")
            if not exists:
                self._fh.write(",".join(self.header) + "\n")
                self._fh.flush()
        return self._fh

    def open(self) -> "CsvAppendWriter":
        """显式打开文件（自检用）。"""
        with self._lock:
            self._ensure_open()
        return self

    def close(self) -> None:
        """flush 并关闭文件。"""
        with self._lock:
            self.flush(force=True)
            if self._fh is not None:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "CsvAppendWriter":
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ 写入

    def write_record(self, record: SampleRecord) -> None:
        """写入一条采样记录（入队，立即返回）。"""
        self._queue.put(record.to_row())

    def write_records(self, records: Iterable[SampleRecord]) -> None:
        """批量写入采样记录。"""
        for record in records:
            self.write_record(record)

    def write_rows(self, rows: Iterable[Sequence[str]]) -> None:
        """写入已格式化的行。"""
        for row in rows:
            self._queue.put(list(row))

    def flush(self, force: bool = False) -> int:
        """把队列内容写入文件。

        :param force: 为 ``True`` 时无视刷新间隔，立即落盘
        :return: 本次写入的行数
        """
        now = time.monotonic()
        if not force and (now - self._last_flush) < self.flush_interval_s:
            return 0
        written = 0
        with self._lock:
            fh = self._ensure_open()
            while True:
                try:
                    row = self._queue.get_nowait()
                except Empty:
                    break
                fh.write(",".join(_csv_escape(str(cell)) for cell in row) + "\n")
                written += 1
            if written:
                fh.flush()
                self.rows_written += written
            self._last_flush = now
        return written

    def pending(self) -> int:
        """队列中待落盘的行数。"""
        return self._queue.qsize()

    def status(self) -> dict[str, object]:
        """自检用状态（FR-10.2）。"""
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "rows_written": self.rows_written,
            "pending": self.pending(),
        }


class GrayCsvWriter(CsvAppendWriter):
    """逐帧 Gnorm 时间序列写入器（FR-4.4）。"""

    def __init__(self, path: str | Path, flush_interval_s: float = 1.0) -> None:
        super().__init__(path, header=GRAY_CSV_HEADER, flush_interval_s=flush_interval_s)

    def write_frame(self, frame: GrayFrame) -> None:
        """写入一帧灰度结果。"""
        self.write_rows([frame.to_row()])


def _csv_escape(value: str) -> str:
    """CSV 字段转义：含逗号/引号/换行时加引号。"""
    if any(ch in value for ch in (",", '"', "\n", "\r")):
        return '"' + value.replace('"', '""') + '"'
    return value
