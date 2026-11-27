"""端到端集成测试：事件总线 → 调度 → 判据 → 存储 → 服务。

验证"模块间相互作用"确实按设计工作：

* 调度器发布批次 → 服务缓冲 + 落盘；
* 判据在跨支路比较后打标记并产生告警；
* 历史检索能读回刚写入的数据；
* 服务门面可完成标定与效率计算。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from daccs.core.events import EventBus
from daccs.core.quality import Thresholds
from daccs.core.scheduler import (
    TOPIC_ALARM,
    TOPIC_SAMPLE_BATCH,
    AcquisitionScheduler,
)
from daccs.core.service import ApplicationService
from daccs.core.types import Channel, DataFlag, SampleRecord
from daccs.device.base import Driver, ReconnectPolicy
from daccs.storage.meta import ExperimentStore
from daccs.storage.reader import HistoryReader
from daccs.storage.writer import CsvAppendWriter


class FakeDriver(Driver):
    """假的设备驱动，按脚本返回记录。"""

    name = "fake"

    def __init__(self, records):
        super().__init__()
        self._records = list(records)
        self.reads = 0

    def open(self) -> None:
        self._connected = True

    def read(self):
        self.reads += 1
        return list(self._records)


class TestEventBus(unittest.TestCase):
    def test_publish_and_subscribe(self) -> None:
        bus = EventBus()
        received = []
        bus.subscribe("demo", received.append)
        bus.publish("demo", 42)
        self.assertEqual(received, [42])

    def test_prefix_wildcard(self) -> None:
        bus = EventBus()
        received = []
        bus.subscribe("sample.*", received.append)
        bus.publish("sample.batch", "x")
        self.assertEqual(received, ["x"])

    def test_subscriber_exception_does_not_break_publisher(self) -> None:
        bus = EventBus()
        seen = []

        def bad(_payload):
            raise RuntimeError("boom")

        bus.subscribe("t", bad)
        bus.subscribe("t", seen.append)
        bus.publish("t", 1)
        self.assertEqual(seen, [1])

    def test_unsubscribe(self) -> None:
        bus = EventBus()
        received = []
        subscription = bus.subscribe("t", received.append)
        subscription.cancel()
        bus.publish("t", 1)
        self.assertEqual(received, [])


class TestReconnectPolicy(unittest.TestCase):
    def test_backoff_caps_at_max(self) -> None:
        """FR-1.4：指数退避，最长 5 s。"""
        policy = ReconnectPolicy(initial=0.5, factor=2.0, max_delay=5.0, jitter=0.0)
        delays = [policy.next_delay() for _ in range(8)]
        self.assertAlmostEqual(delays[0], 0.5)
        self.assertAlmostEqual(delays[1], 1.0)
        self.assertAlmostEqual(delays[2], 2.0)
        self.assertAlmostEqual(delays[3], 4.0)
        self.assertAlmostEqual(delays[4], 5.0)
        self.assertTrue(all(d <= 5.0 for d in delays))


class TestSchedulerIntegration(unittest.TestCase):
    def test_batch_published_and_flags_applied(self) -> None:
        bus = EventBus()
        batches = []
        alarms = []
        bus.subscribe(TOPIC_SAMPLE_BATCH, batches.append)
        bus.subscribe(TOPIC_ALARM, alarms.append)

        driver = FakeDriver(
            [
                SampleRecord(ts=1000.0, ch=Channel.A, pm25=100.0, rh=50.0),
                SampleRecord(ts=1000.0, ch=Channel.B, pm25=120.0, rh=58.0),
            ]
        )
        scheduler = AcquisitionScheduler(bus=bus, drivers=[driver], thresholds=Thresholds())
        records = scheduler.tick()

        self.assertEqual(len(batches), 1)
        self.assertEqual(len(records), 2)
        # RH 差 8%RH > 5% → 标记并告警
        self.assertTrue(any(r.flag & DataFlag.RH_DIVERGENCE for r in records))
        self.assertTrue(any(a.code == "RH_DIVERGENCE" for a in alarms))

    def test_no_cross_branch_false_positive(self) -> None:
        """只有单支路数据时不应误报 RH 分歧。"""
        bus = EventBus()
        alarms = []
        bus.subscribe(TOPIC_ALARM, alarms.append)
        driver = FakeDriver([SampleRecord(ts=1000.0, ch=Channel.A, pm25=10.0, rh=50.0)])
        scheduler = AcquisitionScheduler(bus=bus, drivers=[driver])
        records = scheduler.tick()
        self.assertFalse(records[0].flag & DataFlag.RH_DIVERGENCE)
        self.assertEqual(alarms, [])


class TestServiceIntegration(unittest.TestCase):
    def test_end_to_end_persist_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bus = EventBus()
            driver = FakeDriver(
                [
                    SampleRecord(ts=1000.0, ch=Channel.A, pm25=100.0, rh=50.0),
                    SampleRecord(ts=1000.0, ch=Channel.B, pm25=102.0, rh=51.0),
                ]
            )
            scheduler = AcquisitionScheduler(bus=bus, drivers=[driver])
            writer = CsvAppendWriter(root / "EXP-001" / "samples.csv")
            service = ApplicationService(
                config=_config(),
                bus=bus,
                scheduler=scheduler,
                writer=writer,
                reader=HistoryReader(root),
                meta_store=ExperimentStore(root),
            )

            scheduler.tick()
            writer.flush(force=True)

            snapshot = service.snapshot()
            self.assertIsNotNone(snapshot.a)
            self.assertIsNotNone(snapshot.b)
            self.assertAlmostEqual(snapshot.rh_diff, 1.0)
            self.assertEqual(len(service.recent()), 2)

            records = service.query_history("EXP-001").records
            self.assertEqual(len(records), 2)
            self.assertAlmostEqual(records[0].pm25, 100.0)

            service.close()

    def test_calibration_and_efficiency_via_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bus = EventBus()
            service = ApplicationService(
                config=_config(), bus=bus, reader=HistoryReader(Path(tmp)),
                meta_store=ExperimentStore(Path(tmp)),
            )
            result = service.run_calibration(
                [(10.0, 100.0), (20.0, 200.0), (30.0, 300.0), (40.0, 400.0), (50.0, 500.0)],
                expid="EXP-001",
            )
            self.assertAlmostEqual(result.alpha, 10.0, places=6)
            self.assertTrue(result.passed)
            self.assertEqual(service.current_calibration(), result)

            ratio = service.compute_split_ratio([1.0, 1.0, 1.0], [1.0, 1.0, 1.0])
            self.assertTrue(ratio.passed)

            dp = service.evaluate_plunge_dp(0.2)
            self.assertTrue(dp.passed)
            service.close()


def _config():
    from daccs.config.schema import AppConfig

    config = AppConfig.from_dict({})
    config.acquisition.cfeed = 1000.0
    return config


if __name__ == "__main__":
    unittest.main()
