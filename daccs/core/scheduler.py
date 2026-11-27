"""采集调度器（FR-1 / FR-2 / SRS 2.4 约束 1）。

职责：

1. 以 **1 Hz** 固定节拍驱动所有设备驱动读取（SDS011 ×2、温湿度 ×2、可选 RS485）；
2. 把各驱动返回的记录按通道合并为一批（``sample.batch``）；
3. 捕获单路驱动的异常，按 :class:`~daccs.device.base.ReconnectPolicy`
   执行断线重连并广播 ``DISCONNECTED`` 标记（FR-1.4）；
4. 触发跨支路质量判据（RH 差、传感器互差），打标记并产出告警事件。

调度器 **不认识界面、也不直接写文件**：它只把批次发布到事件总线，
由 :mod:`daccs.storage` 与 :mod:`daccs.ui` 各自订阅。这是"模块间相互作用"
的核心解耦点。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from ..device.base import Driver, DriverError
from .clock import now_ms
from .events import EventBus
from .quality import DEFAULT_THRESHOLDS, Thresholds, evaluate_sample_pair, sds011_rh_warning
from .types import AlarmEvent, AlarmLevel, Channel, DataFlag, SampleRecord

__all__ = ["AcquisitionScheduler", "SchedulerStatus", "TOPIC_SAMPLE_BATCH", "TOPIC_ALARM"]

logger = logging.getLogger(__name__)

#: 采样批次话题
TOPIC_SAMPLE_BATCH = "sample.batch"
#: 告警话题
TOPIC_ALARM = "alarm"
#: 运行状态话题
TOPIC_STATUS = "status"


@dataclass(slots=True)
class SchedulerStatus:
    """调度器运行状态（供自检与界面状态栏）。"""

    running: bool = False
    ticks: int = 0
    errors: int = 0
    last_error: str = ""
    last_tick_ts: float = 0.0
    cycle_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "running": self.running,
            "ticks": self.ticks,
            "errors": self.errors,
            "last_error": self.last_error,
            "last_tick_ts": self.last_tick_ts,
            "cycle_ms": self.cycle_ms,
        }


@dataclass
class AcquisitionScheduler:
    """1 Hz 采集调度器。

    :param bus: 事件总线
    :param drivers: 参与调度的设备驱动列表
    :param period_s: 采集周期秒数（SRS 2.4 约束 1：固定 1 s）
    :param thresholds: 判据阈值
    """

    bus: EventBus
    drivers: list[Driver] = field(default_factory=list)
    period_s: float = 1.0
    thresholds: Thresholds = DEFAULT_THRESHOLDS
    status: SchedulerStatus = field(default_factory=SchedulerStatus)
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> None:
        """打开全部驱动并启动调度线程。"""
        if self._thread is not None:
            return
        self._stop_event.clear()
        for driver in self.drivers:
            try:
                driver.open()
            except DriverError as exc:
                logger.error("%s 打开失败：%s", driver.name, exc)
                self.status.errors += 1
                self.status.last_error = f"{driver.name}: {exc}"
        self.status.running = True
        self._thread = threading.Thread(target=self._loop, name="acquisition", daemon=True)
        self._thread.start()
        logger.info("采集调度器已启动，周期 %.1fs，共 %d 个驱动", self.period_s, len(self.drivers))

    def stop(self, timeout: float = 3.0) -> None:
        """停止调度线程并关闭全部驱动。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        for driver in self.drivers:
            driver.close()
        self.status.running = False
        logger.info("采集调度器已停止")

    def __enter__(self) -> "AcquisitionScheduler":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # ------------------------------------------------------------------ 调度循环

    def _loop(self) -> None:
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - 调度线程必须活着
                logger.exception("采集周期异常")
                self.status.errors += 1
            next_tick += self.period_s
            delay = next_tick - time.monotonic()
            if delay < 0:
                # 落后太多则重新对齐，不追赶积压周期
                next_tick = time.monotonic()
                delay = 0.0
            self._stop_event.wait(delay)
            self.status.cycle_ms = (time.monotonic() - cycle_start) * 1000.0

    def tick(self) -> list[SampleRecord]:
        """执行一个采集周期并发布批次（也可在测试中直接调用）。

        :return: 本周期产生的采样记录
        """
        self.status.ticks += 1
        self.status.last_tick_ts = now_ms()

        records: list[SampleRecord] = []
        for driver in self.drivers:
            try:
                records.extend(driver.read())
            except DriverError as exc:
                self.status.errors += 1
                self.status.last_error = f"{driver.name}: {exc}"
                logger.warning("%s 读取失败，尝试重连：%s", driver.name, exc)
                event = driver.reconnect(str(exc))
                if event is not None:
                    records.append(
                        SampleRecord(
                            ts=now_ms(),
                            ch=Channel.A,
                            flag=DataFlag.DISCONNECTED,
                        )
                    )

        processed = self.apply_quality(records)
        self.bus.publish(TOPIC_SAMPLE_BATCH, processed)
        return processed

    # ------------------------------------------------------------------ 质量判据

    def apply_quality(self, records: Sequence[SampleRecord]) -> list[SampleRecord]:
        """执行跨支路判据并广播告警（FR-2.2 / FR-6.2）。

        :param records: 本周期原始记录
        :return: 叠加了标记位的记录
        """
        by_channel: dict[Channel, list[SampleRecord]] = {}
        for record in records:
            by_channel.setdefault(record.ch, []).append(record)

        alarms: list[AlarmEvent] = []
        updated: list[SampleRecord] = []

        for record in records:
            flags = DataFlag.NONE
            counterpart = self._counterpart(record, by_channel)
            pair_flags, pair_alarms = evaluate_sample_pair(
                record if record.ch == Channel.A else counterpart,
                record if record.ch == Channel.B else counterpart,
                self.thresholds,
            )
            flags |= pair_flags
            alarms.extend(pair_alarms)

            hint = sds011_rh_warning(record.rh, self.thresholds)
            if hint:
                alarms.append(
                    AlarmEvent(
                        ts=record.ts,
                        level=AlarmLevel.WARNING,
                        code="SDS011_RH_LIMIT",
                        message=hint,
                        ch=record.ch,
                    )
                )

            updated.append(record.with_flag(flags) if flags else record)

        # 去重告警：同一周期同一代码只报一次
        seen: set[tuple[str, str]] = set()
        for alarm in alarms:
            key = (alarm.code, alarm.ch.value if alarm.ch else "")
            if key in seen:
                continue
            seen.add(key)
            self.bus.publish(TOPIC_ALARM, alarm)

        return updated

    @staticmethod
    def _counterpart(
        record: SampleRecord,
        by_channel: dict[Channel, list[SampleRecord]],
    ) -> SampleRecord | None:
        """取同一时刻另一支路的记录（时间戳最接近者）。"""
        candidates = by_channel.get(
            Channel.B if record.ch == Channel.A else Channel.A, []
        )
        if not candidates:
            return None
        return min(candidates, key=lambda c: abs(c.ts - record.ts))
