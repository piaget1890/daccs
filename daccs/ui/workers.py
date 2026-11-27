"""后台线程与事件总线 → Qt 信号桥接。

线程模型（SRS NFR-1/NFR-2、FR-6）::

    ┌──────────────────┐  1 Hz   ┌──────────────────┐
    │ AcquisitionThread│ ──────> │  EventBus        │
    │  (采集 + 判据)     │         │  (线程安全)       │
    └──────────────────┘         └────────┬─────────┘
                                           │ publish
                                           ▼
                                   ┌──────────────────┐
                                   │ BusBridge (QObject)│
                                   │  把回调转成 Qt 信号  │
                                   └────────┬─────────┘
                              queued 连接     │  自动切回 GUI 线程
                                           ▼
                                   ┌──────────────────┐
                                   │ MainWindow       │
                                   │  刷新 A/B 栏、曲线 │
                                   └──────────────────┘

关键点：

* 采集、存储全部在 **工作线程**，GUI 线程只做渲染；
* 工作线程 → GUI 线程的数据传递一律走 Qt **信号**，不直接碰控件；
* 事件总线的回调发生在发布者线程，:class:`BusBridge` 用
  ``Qt.ConnectionType.QueuedConnection`` 把数据切到 GUI 线程。
"""

from __future__ import annotations

import logging
from typing import Sequence

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..core.events import EventBus
from ..core.scheduler import TOPIC_ALARM, TOPIC_SAMPLE_BATCH, TOPIC_STATUS
from ..core.types import AlarmEvent, SampleRecord

__all__ = ["BusBridge", "AcquisitionWorker", "VideoWorker"]

logger = logging.getLogger(__name__)


class BusBridge(QObject):
    """把事件总线上的事件转成 Qt 信号。"""

    samples_ready = Signal(list)      # list[SampleRecord]
    alarm_raised = Signal(object)     # AlarmEvent
    status_changed = Signal(object)   # dict

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self._bus = bus
        self._subscriptions = [
            bus.subscribe(TOPIC_SAMPLE_BATCH, self._on_samples),
            bus.subscribe(TOPIC_ALARM, self._on_alarm),
            bus.subscribe(TOPIC_STATUS, self._on_status),
        ]

    @Slot(list)
    def _on_samples(self, records: Sequence[SampleRecord]) -> None:
        # 该回调运行在发布者线程；emit 是线程安全的，接收端由 queued 连接切回 GUI 线程
        self.samples_ready.emit(list(records))

    @Slot(object)
    def _on_alarm(self, alarm: AlarmEvent) -> None:
        self.alarm_raised.emit(alarm)

    @Slot(object)
    def _on_status(self, status: object) -> None:
        self.status_changed.emit(status)

    def dispose(self) -> None:
        """解除订阅。"""
        for subscription in self._subscriptions:
            subscription.cancel()
        self._subscriptions.clear()


class AcquisitionWorker(QThread):
    """采集工作线程。

    :param service: 应用服务门面（提供 ``start`` / ``stop``）
    """

    finished_ok = Signal()

    def __init__(self, service) -> None:
        super().__init__(name="acquisition-worker")
        self._service = service
        self._running = False

    def run(self) -> None:  # pragma: no cover - 需要真实设备
        self._running = True
        try:
            self._service.start()
            while self._running:
                self.msleep(200)
        except Exception:
            logger.exception("采集线程异常退出")
        finally:
            self._service.stop()
            self.finished_ok.emit()

    def stop(self) -> None:
        """请求线程停止。"""
        self._running = False
        self.wait(5000)


class VideoWorker(QThread):
    """视频灰度提取工作线程（FR-4）。

    :param service: 应用服务门面
    :param target: 视频文件路径或相机序号
    :param is_camera: 是否为相机
    """

    frames_ready = Signal(list)   # list[GrayFrame]
    finished_ok = Signal()

    def __init__(self, service, target: str | int, is_camera: bool = False) -> None:
        super().__init__(name="video-worker")
        self._service = service
        self._target = target
        self._is_camera = is_camera
        self._running = False

    def run(self) -> None:  # pragma: no cover - 需要真实视频源
        self._running = True
        try:
            frames = self._service.extract_gray_from_video(self._target, self._is_camera)
            self._service.submit_gray_frames(frames)
            self.frames_ready.emit(frames)
        except Exception:
            logger.exception("视频线程异常退出")
        finally:
            self.finished_ok.emit()

    def stop(self) -> None:
        self._running = False
        self.wait(5000)
