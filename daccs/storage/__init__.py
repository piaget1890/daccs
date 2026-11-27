"""存储层：原始数据落盘与历史检索（FR-5）。

约束（SRS 2.4 约束 3 / NFR-5）：

* **原始数据只追加不覆盖**：写入器只用 ``a`` 模式打开文件，永不 ``w``/``r+``；
* **缓冲落盘防丢失**（NFR-6）：写操作先入内存队列，按 ``flush_interval_s``
  定时 flush，异常退出前强制 flush；
* **CSV 使用 UTF-8 BOM**，保证 Excel 直接双击可开（SRS 6.4）。

三个文件：

* :mod:`.writer` —— 采样 CSV 与灰度 CSV 的追加写入；
* :mod:`.reader` —— 按实验编号检索与回放（FR-5.3）；
* :mod:`.buffer` —— 60 s 滚动窗口环形缓冲（FR-6.3）。
"""

from __future__ import annotations

from .buffer import RollingBuffer
from .meta import ExperimentStore
from .reader import HistoryReader, SampleQuery
from .writer import CsvAppendWriter, GrayCsvWriter, SAMPLE_CSV_HEADER

__all__ = [
    "RollingBuffer",
    "ExperimentStore",
    "HistoryReader",
    "SampleQuery",
    "CsvAppendWriter",
    "GrayCsvWriter",
    "SAMPLE_CSV_HEADER",
]
