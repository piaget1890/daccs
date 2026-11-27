"""统计摘要（FR-5.3 历史数据回放时的统计面板）。

全部为纯函数，不依赖 pandas，便于单元测试与在无 pandas 环境下复用。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Iterable, Sequence

__all__ = ["NumericSummary", "summarize", "summarize_series"]


@dataclass(frozen=True, slots=True)
class NumericSummary:
    """一组数值的统计摘要。"""

    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    stdev: float | None = None
    min_index: int | None = None
    max_index: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.mean,
            "median": self.median,
            "stdev": self.stdev,
            "min_index": self.min_index,
            "max_index": self.max_index,
        }


def summarize(values: Iterable[float | None]) -> NumericSummary:
    """计算数值序列摘要（自动跳过缺测）。"""
    clean: list[float] = []
    for v in values:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(fv):
            continue
        clean.append(fv)

    if not clean:
        return NumericSummary()

    min_index = min(range(len(clean)), key=lambda i: clean[i])
    max_index = max(range(len(clean)), key=lambda i: clean[i])
    return NumericSummary(
        count=len(clean),
        minimum=clean[min_index],
        maximum=clean[max_index],
        mean=statistics.fmean(clean),
        median=statistics.median(clean),
        stdev=statistics.stdev(clean) if len(clean) > 1 else 0.0,
        min_index=min_index,
        max_index=max_index,
    )


def summarize_series(series: dict[str, Sequence[float | None]]) -> dict[str, NumericSummary]:
    """对多个字段批量求摘要。"""
    return {name: summarize(values) for name, values in series.items()}
