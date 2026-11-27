"""时间轴对齐（SRS 5.3 / 6.4）。

规则：

* 传感器通道 1 Hz，毫秒时间戳；
* 灰度按视频帧率记录；
* 对齐采用 **最近邻**，容差 ±0.5 s（一个采集周期内），超出容差的帧
  记为 ``GRAY_UNALIGNED``，该条采样不参与 η_A 计算。

对齐器是 **纯函数式** 的：输入两组时间戳，输出匹配关系，便于离线验证。
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass
from typing import Sequence

from .types import Channel, DataFlag, GrayFrame, SampleRecord

__all__ = ["ALIGN_TOLERANCE_MS", "GrayAlignment", "align_frames_to_samples", "nearest_index"]

logger = logging.getLogger(__name__)

#: 对齐容差（SRS 5.3：±0.5 s）
ALIGN_TOLERANCE_MS = 500.0


@dataclass(frozen=True, slots=True)
class GrayAlignment:
    """一次对齐的结果摘要。"""

    matched: int = 0
    unmatched_frames: int = 0
    unmatched_samples: int = 0
    max_error_ms: float = 0.0


def nearest_index(sorted_ts: Sequence[float], target: float) -> tuple[int, float]:
    """在有序时间戳序列中找离 ``target`` 最近的下标。

    :param sorted_ts: 升序时间戳序列
    :param target: 目标时间戳
    :return: ``(下标, 绝对时间差 ms)``；序列为空返回 ``(-1, inf)``
    """
    if not sorted_ts:
        return -1, float("inf")
    pos = bisect.bisect_left(sorted_ts, target)
    if pos == 0:
        return 0, abs(sorted_ts[0] - target)
    if pos == len(sorted_ts):
        last = len(sorted_ts) - 1
        return last, abs(sorted_ts[last] - target)
    before = pos - 1
    after = pos
    d_before = abs(sorted_ts[before] - target)
    d_after = abs(sorted_ts[after] - target)
    return (before, d_before) if d_before <= d_after else (after, d_after)


def align_frames_to_samples(
    samples: Sequence[SampleRecord],
    frames: Sequence[GrayFrame],
    tolerance_ms: float = ALIGN_TOLERANCE_MS,
) -> tuple[list[SampleRecord], GrayAlignment]:
    """把灰度帧按最近邻对齐到采样记录上。

    :param samples: 采样记录（应已按 ts 升序）
    :param frames: 灰度帧（应已按 ts 升序）
    :param tolerance_ms: 对齐容差
    :return: ``(叠加了 Gnorm 与标记位的采样记录列表, 对齐摘要)``

    对齐结果直接写回 ``SampleRecord.gnorm``：一条采样最多匹配一帧
    （最近邻优先分配），避免同一帧被多条采样重复使用。
    """
    if not samples or not frames:
        return list(samples), GrayAlignment(unmatched_frames=len(frames), unmatched_samples=len(samples))

    ordered_samples = sorted(samples, key=lambda s: s.ts)
    ordered_frames = sorted(frames, key=lambda f: f.ts)
    frame_ts = [f.ts for f in ordered_frames]
    sample_ts = [s.ts for s in ordered_samples]

    used_frames: set[int] = set()
    matched = 0
    max_error = 0.0
    out: list[SampleRecord] = []

    for sample in ordered_samples:
        idx, error = nearest_index(frame_ts, sample.ts)
        if idx < 0 or error > tolerance_ms:
            out.append(sample.with_flag(DataFlag.GRAY_UNALIGNED))
            continue
        if idx in used_frames:
            out.append(sample.with_flag(DataFlag.GRAY_UNALIGNED))
            continue
        used_frames.add(idx)
        frame = ordered_frames[idx]
        matched += 1
        max_error = max(max_error, error)
        updated = SampleRecord(
            ts=sample.ts,
            ch=sample.ch,
            pm25=sample.pm25,
            pm10=sample.pm10,
            rh=sample.rh,
            temp=sample.temp,
            gnorm=frame.gnorm,
            flag=sample.flag,
            wind_speed_ms=sample.wind_speed_ms,
            dp_pa=sample.dp_pa,
        )
        out.append(updated)

    summary = GrayAlignment(
        matched=matched,
        unmatched_frames=len(frames) - len(used_frames),
        unmatched_samples=len(ordered_samples) - matched,
        max_error_ms=max_error,
    )
    if summary.unmatched_frames or summary.unmatched_samples:
        logger.debug(
            "灰度对齐：匹配 %d，未匹配帧 %d，未匹配采样 %d，最大误差 %.0fms",
            summary.matched, summary.unmatched_frames,
            summary.unmatched_samples, summary.max_error_ms,
        )
    return out, summary
