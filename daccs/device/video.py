"""视频 / 相机输入与灰度提取驱动（FR-4）。

* 输入：手机录像文件（MP4）或 USB 相机（UVC）
* 依赖：OpenCV（:mod:`cv2`）—— 本模块对 OpenCV 做 **延迟导入**，
  这样在没有装 opencv 的环境（单元测试、CI）也能 import 整个框架；
* 帧率：按视频帧率逐帧处理（SRS 5.3），时间戳由本机时钟打点。

灰度算法本身在 :mod:`daccs.algorithm.grayscale` 中，本驱动只负责
"取帧 + 转灰度 + 给出时间戳"，从而使设备层与算法层职责分离。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterator

from ..core.clock import now_ms
from ..core.types import GrayFrame
from .base import Driver, DriverError

__all__ = ["VideoSource", "VideoDriver", "VideoFrame"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VideoFrame:
    """一帧视频图像（已转灰度）。"""

    index: int
    ts: float
    gray: "object"  # numpy.ndarray，避免在类型标注上硬依赖 numpy


class VideoSource:
    """视频源描述：文件路径或相机序号。"""

    def __init__(self, target: str | int, is_camera: bool = False) -> None:
        self.target = target
        self.is_camera = is_camera

    @property
    def describe(self) -> str:
        return f"相机#{self.target}" if self.is_camera else f"文件 {self.target}"


class VideoDriver(Driver):
    """视频驱动。

    :param source: 视频源
    :param fps: 期望帧率上限；``None`` 表示使用视频自带帧率
    """

    name = "video"

    def __init__(self, source: VideoSource, fps: float | None = None) -> None:
        super().__init__()
        self.source = source
        self.fps = fps
        self._capture = None
        self.frame_index = 0

    def open(self) -> None:
        try:
            import cv2  # noqa: PLC0415 - 延迟导入，隔离可选依赖
        except ImportError as exc:  # pragma: no cover - 环境缺依赖
            raise DriverError("未安装 opencv，无法读取视频/相机") from exc

        if self.source.is_camera:
            cap = cv2.VideoCapture(self.source.target)
        else:
            cap = cv2.VideoCapture(self.source.target)
        if not cap.isOpened():
            raise DriverError(f"无法打开视频源：{self.source.describe}")
        self._capture = cap
        self._connected = True
        logger.info("视频源已打开：%s", self.source.describe)

    def iter_frames(self) -> Iterator[VideoFrame]:
        """逐帧迭代灰度图（生成器）。"""
        if self._capture is None:
            raise DriverError("视频源未打开")
        import cv2  # noqa: PLC0415

        while self._connected:
            ok, frame = self._capture.read()
            if not ok:
                logger.info("视频读取结束：%s", self.source.describe)
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            yield VideoFrame(index=self.frame_index, ts=now_ms(), gray=gray)
            self.frame_index += 1

    def read(self) -> list[GrayFrame]:
        """读取一帧（返回空列表表示本轮无新帧）。

        注意：完整提取请使用 :meth:`iter_frames`，逐帧提取不应按 1 Hz 采样。
        """
        raise DriverError("视频应通过 iter_frames() 逐帧处理")

    def close(self) -> None:
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:  # noqa: BLE001
                logger.debug("视频释放异常", exc_info=True)
        self._capture = None
        self._connected = False

    def status(self) -> dict[str, object]:
        return {
            "source": self.source.describe,
            "connected": self.connected,
            "frames": self.frame_index,
        }
