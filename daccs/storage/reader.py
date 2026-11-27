"""历史数据检索与回放（FR-5.3）。

按实验编号检索采样 CSV，并给出统计摘要。检索层刻意 **不依赖 pandas**，
用标准库 ``csv`` 解析即可在无科学计算环境下运行；需要批量分析时
上层可自行转 DataFrame。
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from ..algorithm.metrics import NumericSummary, summarize
from ..core.types import Channel, DataFlag, SampleRecord

__all__ = ["SampleQuery", "HistoryReader", "parse_ts"]

logger = logging.getLogger(__name__)


def parse_ts(text: str) -> float:
    """把 CSV 中的时间戳字符串解析为毫秒时间戳。

    :raises ValueError: 格式非法
    """
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.timestamp() * 1000.0
        except ValueError:
            continue
    raise ValueError(f"无法解析时间戳：{text!r}")


@dataclass(slots=True)
class SampleQuery:
    """一次检索的条件与结果。"""

    expid: str = ""
    channel: Channel | None = None
    start_ts: float | None = None
    end_ts: float | None = None
    records: list[SampleRecord] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, NumericSummary]:
        """给出各字段的统计摘要（FR-5.3 "曲线 + 统计摘要"）。"""
        return {
            "pm25": summarize(r.pm25 for r in self.records),
            "pm10": summarize(r.pm10 for r in self.records),
            "rh": summarize(r.rh for r in self.records),
            "temp": summarize(r.temp for r in self.records),
            "gnorm": summarize(r.gnorm for r in self.records),
        }


class HistoryReader:
    """历史数据读取器。

    :param root: 数据根目录（每个实验一个子目录，内含 ``samples_*.csv``）
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ 检索

    def sample_files(self, expid: str) -> list[Path]:
        """列出某实验的采样 CSV 文件（按文件名排序，保证回放顺序稳定）。"""
        directory = self.root / expid
        if not directory.exists():
            return []
        return sorted(directory.glob("samples*.csv"))

    def query(self, expid: str, **kwargs) -> SampleQuery:
        """按条件检索采样记录。

        :param expid: 实验编号
        :param channel: 仅返回某支路
        :param start_ts / end_ts: 时间范围（毫秒）
        """
        channel = kwargs.get("channel")
        start_ts = kwargs.get("start_ts")
        end_ts = kwargs.get("end_ts")

        result = SampleQuery(
            expid=expid, channel=channel, start_ts=start_ts, end_ts=end_ts
        )
        for path in self.sample_files(expid):
            result.source_files.append(str(path))
            for record in self._read_file(path, channel, start_ts, end_ts):
                result.records.append(record)
        result.records.sort(key=lambda r: r.ts)
        return result

    def read_all(self, expid: str) -> list[SampleRecord]:
        """读取某实验的全部采样记录。"""
        return self.query(expid).records

    @staticmethod
    def _read_file(
        path: Path,
        channel: Channel | None,
        start_ts: float | None,
        end_ts: float | None,
    ) -> Iterable[SampleRecord]:
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                if header is None:
                    return
                for row in reader:
                    if len(row) < 8:
                        continue
                    try:
                        ts = parse_ts(row[0])
                    except ValueError:
                        continue
                    if start_ts is not None and ts < start_ts:
                        continue
                    if end_ts is not None and ts > end_ts:
                        continue
                    ch = Channel(row[1].strip().upper()) if row[1].strip() in ("A", "B") else Channel.A
                    if channel is not None and ch != channel:
                        continue
                    flags = DataFlag.NONE
                    for name in filter(None, (row[7] or "").split(";")):
                        try:
                            flags |= DataFlag[name.strip()]
                        except KeyError:
                            continue
                    yield SampleRecord(
                        ts=ts,
                        ch=ch,
                        pm25=_num(row[2]),
                        pm10=_num(row[3]),
                        rh=_num(row[4]),
                        temp=_num(row[5]),
                        gnorm=_num(row[6]),
                        flag=flags,
                        wind_speed_ms=_num(row[8]) if len(row) > 8 else None,
                        dp_pa=_num(row[9]) if len(row) > 9 else None,
                    )
        except OSError:
            logger.exception("采样文件读取失败：%s", path)

    # ------------------------------------------------------------------ 统计

    def experiment_summary(self, expid: str) -> dict[str, object]:
        """给出某实验的概览（条数、时间范围、统计摘要）。"""
        query = self.query(expid)
        records = query.records
        summary = query.summary()
        return {
            "expid": expid,
            "count": len(records),
            "start_ts": records[0].ts if records else None,
            "end_ts": records[-1].ts if records else None,
            "files": query.source_files,
            "summary": {k: v.to_dict() for k, v in summary.items()},
        }


def _num(text: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
