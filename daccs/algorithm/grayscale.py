"""灰度提取与归一化算法（FR-4 / SRS 7.1）。

计算口径（SRS 7.1，与《空气净化器颗粒物测定标准核验与手工测试装置方案》
5.6.1 一致）：

1. ``GROI``  = ROI 内灰度的 95 百分位
2. ``Gbg``   = ROI **外扩 2 倍** 区域（扣除 ROI 自身）灰度的 95 百分位
3. ``Gnorm`` = ``GROI / Gbg × 100``（扣暗电流基线后）
4. ``gt``    = ``(Gnorm,t − Gnorm,b) / (Gnorm,0 − Gnorm,b)``，仅定性展示，
   **不参与 η_A 计算**

暗电流基线的处理（FR-4.3：用户提供"盖镜头 10 帧均值"）::

    Gnorm = (GROI − b_roi) / (Gbg − b_bg) × 100

即基线同时从分子与分母中扣除，避免背景底噪被算进比值。若调用方未提供
基线（``None``），退化为 SRS 7.1 的原始口径 ``GROI / Gbg × 100``。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from ..core.types import GrayFrame

__all__ = [
    "ROI",
    "DarkBaseline",
    "percentile_95",
    "expand_roi",
    "extract_groi",
    "extract_gbg",
    "normalize_gray",
    "extract_frame_grayness",
    "extract_dark_baseline",
    "apply_gcard_correction",
    "compute_gt_series",
]

logger = logging.getLogger(__name__)

#: ROI 矩形，坐标顺序为 ``(x, y, w, h)``，以图像左上角为原点。
ROI = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class DarkBaseline:
    """暗电流基线（FR-4.3）。

    :param roi: ROI 区域盖镜头 10 帧均值
    :param bg: ROI 外扩区域盖镜头 10 帧均值
    """

    roi: float = 0.0
    bg: float = 0.0


def percentile_95(values: Iterable[float] | np.ndarray) -> float:
    """95 百分位（SRS 7.1）。

    :param values: 灰度样本
    :return: 0–255 区间内的百分位值；空输入返回 ``nan``
    """
    arr = np.asarray(list(values) if not isinstance(values, np.ndarray) else values, dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.percentile(arr, 95))


def expand_roi(roi: ROI, shape: tuple[int, int], factor: float = 2.0) -> tuple[slice, slice]:
    """把 ROI 按 ``factor`` 倍外扩（以 ROI 中心为基准），并裁剪到图像范围内。

    :param roi: ``(x, y, w, h)``
    :param shape: 图像 ``(height, width)``
    :param factor: 外扩倍数，SRS 7.1 规定为 2.0
    :return: ``(row_slice, col_slice)``
    """
    x, y, w, h = roi
    cx = x + w / 2.0
    cy = y + h / 2.0
    new_w = w * factor
    new_h = h * factor
    x0 = int(round(cx - new_w / 2.0))
    y0 = int(round(cy - new_h / 2.0))
    x1 = int(round(cx + new_w / 2.0))
    y1 = int(round(cy + new_h / 2.0))
    height, width = shape
    x0 = max(0, min(x0, width))
    x1 = max(0, min(x1, width))
    y0 = max(0, min(y0, height))
    y1 = max(0, min(y1, height))
    return slice(y0, y1), slice(x0, x1)


def extract_groi(gray: np.ndarray, roi: ROI) -> float:
    """ROI 内 95 百分位灰度（FR-4.2）。"""
    x, y, w, h = roi
    patch = gray[y : y + h, x : x + w]
    return percentile_95(patch)


def extract_gbg(gray: np.ndarray, roi: ROI, factor: float = 2.0) -> float:
    """ROI 外扩 2 倍区域的 95 百分位灰度（FR-4.2）。

    .. note::
       **计算时排除 ROI 自身**（取外扩环带），这是保证指标不退化的必要条件。

       ROI 在外扩 2 倍的方框中恒占 1/4 面积（线性 2 倍 → 面积 4 倍），
       若把 ROI 一起算进 95 百分位，取到的必然是 ROI 自身的亮带值，
       ``Gnorm = GROI / Gbg × 100`` 将恒等于 100，失去归一化意义。

       因此本实现取"外扩 2 倍区域 **减去 ROI**"作为背景参考区，
       95 百分位落在周边背景上，符合 Gbg 作为背景基准的物理含义。

    :param gray: 灰度二维数组
    :param roi: ROI 矩形 ``(x, y, w, h)``
    :param factor: 外扩倍数，SRS 7.1 规定为 2.0
    """
    rows, cols = expand_roi(roi, gray.shape[:2], factor)
    patch = gray[rows, cols]
    if patch.size == 0:
        return float("nan")

    # 构造掩膜，剔除 ROI 自身
    x, y, w, h = roi
    mask = np.ones(patch.shape, dtype=bool)
    r0 = max(0, y - rows.start)
    r1 = min(patch.shape[0], y + h - rows.start)
    c0 = max(0, x - cols.start)
    c1 = min(patch.shape[1], x + w - cols.start)
    if r1 > r0 and c1 > c0:
        mask[r0:r1, c0:c1] = False

    values = patch[mask]
    if values.size == 0:
        # ROI 覆盖了整个外扩区域（画面过小）——退化为直接取 ROI
        return percentile_95(patch)
    return percentile_95(values)


def normalize_gray(
    groi: float,
    gbg: float,
    baseline: DarkBaseline | None = None,
) -> float:
    """归一化灰度 ``Gnorm``（FR-4.3 / SRS 7.1）。

    :param groi: GROI
    :param gbg: Gbg
    :param baseline: 暗电流基线；``None`` 表示不扣基线
    :return: Gnorm；分母非法时返回 ``nan``
    """
    if not np.isfinite(groi) or not np.isfinite(gbg):
        return float("nan")
    if baseline is None:
        denominator = gbg
        numerator = groi
    else:
        numerator = groi - baseline.roi
        denominator = gbg - baseline.bg
    if denominator is None or abs(denominator) < 1e-9:
        return float("nan")
    return float(numerator / denominator * 100.0)


def extract_frame_grayness(
    frame: np.ndarray,
    roi: ROI,
    baseline: DarkBaseline | None = None,
    ts: float = 0.0,
    frame_index: int = 0,
    gcard_value: float | None = None,
) -> GrayFrame:
    """从单帧图像提取灰度特征（FR-4.1 ~ FR-4.3）。

    :param frame: 灰度二维数组（OpenCV ``cvtColor(BGR2GRAY)`` 的结果）
    :param roi: ROI 矩形 ``(x, y, w, h)``
    :param baseline: 暗电流基线
    :param ts: 帧时间戳（毫秒）
    :param frame_index: 帧序号
    :param gcard_value: 画面内灰卡读数（FR-4.5）
    """
    if frame.ndim != 2:
        raise ValueError("extract_frame_grayness 需要二维灰度图")
    groi = extract_groi(frame, roi)
    gbg = extract_gbg(frame, roi)
    gnorm = normalize_gray(groi, gbg, baseline)
    return GrayFrame(
        ts=ts,
        groi=groi,
        gbg=gbg,
        gnorm=gnorm,
        frame_index=frame_index,
        gcard_value=gcard_value,
    )


def extract_dark_baseline(frames: Sequence[np.ndarray], roi: ROI) -> DarkBaseline:
    """由"盖镜头"帧序列计算暗电流基线（FR-4.3）。

    SRS 要求"盖镜头 10 帧均值"，因此调用方应传入 10 帧。

    :param frames: 盖镜头期间的灰度帧
    :param roi: ROI 矩形
    """
    if not frames:
        return DarkBaseline(0.0, 0.0)
    rois = [extract_groi(f, roi) for f in frames]
    bgs = [extract_gbg(f, roi) for f in frames]
    return DarkBaseline(float(np.mean(rois)), float(np.mean(bgs)))


def apply_gcard_correction(
    gnorm: float,
    gcard_value: float | None,
    gcard_reference: float | None,
) -> float:
    """灰卡二次线性校正（FR-4.5，可选开关）。

    以灰卡读数为自变量做一次线性拉伸，使实测灰卡值对齐到参考值：

    ``gnorm' = gnorm + (gcard_reference − gcard_value) × k``

    其中 ``k`` 为灵敏度系数（默认 1.0，可由配置给出）。当缺少任一灰卡
    读数时原样返回。

    :param gnorm: 原始归一化灰度
    :param gcard_value: 画面内实测灰卡读数
    :param gcard_reference: 灰卡参考读数
    """
    if gcard_value is None or gcard_reference is None:
        return gnorm
    return float(gnorm + (gcard_reference - gcard_value))


def compute_gt_series(
    gnorm_series: Sequence[float],
    gnorm_baseline: float,
    gnorm_zero: float,
) -> list[float]:
    """定性相对灰度序列 ``gt``（SRS 7.1 第 3 条）。

    ``gt = (Gnorm,t − Gnorm,b) / (Gnorm,0 − Gnorm,b)``

    :param gnorm_series: 逐帧 Gnorm 序列
    :param gnorm_baseline: 暗电流基线对应的 Gnorm（b）
    :param gnorm_zero: 零颗粒物对应的 Gnorm（0）
    :return: gt 序列；分母为 0 时全部返回 ``nan``
    """
    denominator = gnorm_zero - gnorm_baseline
    if abs(denominator) < 1e-9:
        return [float("nan")] * len(gnorm_series)
    return [float((g - gnorm_baseline) / denominator) for g in gnorm_series]
