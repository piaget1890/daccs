"""应用服务门面（UI 层与内核之间的唯一契约）。

**这是"各模块间相互作用"的核心设计**：界面层 **不直接** 调用
``device`` / ``algorithm`` / ``storage`` 中的任何一个实现，而是只依赖
:class:`ApplicationService` 暴露的方法。这样带来：

* UI 可以整体替换（PySide6 → 其他框架）而不动内核；
* 内核可以被命令行/脚本/自动化测试复用；
* 依赖方向始终是 ``ui → core → (device | algorithm | storage)``，无环（NFR-7）。

服务内部通过事件总线与调度器协作，通过配置驱动阈值，通过存储层读写数据。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from ..algorithm import calibration as calib
from ..algorithm import efficiency as eff
from ..algorithm import flow as flow_mod
from ..algorithm import grayscale as gray_mod
from ..algorithm import metrics as metrics_mod
from ..config.schema import AppConfig
from ..core.aligner import align_frames_to_samples
from ..core.clock import now_ms
from ..core.events import EventBus
from ..core.quality import Thresholds
from ..core.scheduler import (
    TOPIC_ALARM,
    TOPIC_SAMPLE_BATCH,
    TOPIC_STATUS,
    AcquisitionScheduler,
)
from ..core.types import (
    AlarmEvent,
    CalibrationResult,
    Channel,
    EfficiencyResult,
    GrayFrame,
    SampleRecord,
)
from ..storage.buffer import RollingBuffer
from ..storage.meta import ExperimentStore
from ..storage.reader import HistoryReader, SampleQuery
from ..storage.report import (
    ReportBundle,
    export_csv_bundle,
    export_docx,
    export_xlsx,
)
from ..storage.writer import CsvAppendWriter, GrayCsvWriter

__all__ = ["ApplicationService", "RealtimeSnapshot"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RealtimeSnapshot:
    """实时快照（FR-6.1：主界面 A/B 双栏显示）。"""

    ts: float = 0.0
    a: SampleRecord | None = None
    b: SampleRecord | None = None
    etaa_preview: float | None = None
    rh_diff: float | None = None
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "a": self.a.to_row() if self.a else None,
            "b": self.b.to_row() if self.b else None,
            "etaa_preview": self.etaa_preview,
            "rh_diff": self.rh_diff,
            "flags": list(self.flags),
        }


class ApplicationService:
    """应用服务：内核对外的唯一门面。

    :param config: 运行配置
    :param bus: 事件总线
    :param scheduler: 采集调度器（可为 ``None``，仅做离线分析时）
    :param writer: 采样 CSV 写入器
    :param gray_writer: 灰度 CSV 写入器
    :param reader: 历史数据读取器
    :param meta_store: 实验元数据仓库
    """

    def __init__(
        self,
        config: AppConfig,
        bus: EventBus,
        scheduler: AcquisitionScheduler | None = None,
        writer: CsvAppendWriter | None = None,
        gray_writer: GrayCsvWriter | None = None,
        reader: HistoryReader | None = None,
        meta_store: ExperimentStore | None = None,
    ) -> None:
        self.config = config
        self.bus = bus
        self.scheduler = scheduler
        self.writer = writer
        self.gray_writer = gray_writer
        self.reader = reader
        self.meta_store = meta_store
        self.buffer = RollingBuffer(maxlen=7200, window_s=60.0)
        self.gray_buffer: list[GrayFrame] = []
        self._lock = threading.RLock()
        self._latest: dict[Channel, SampleRecord] = {}
        self._alarms: list[AlarmEvent] = []
        self._calibration: CalibrationResult | None = None
        self._subscriptions: list = []

        self._subscribe()

    # ------------------------------------------------------------------ 装配

    def _subscribe(self) -> None:
        """订阅总线事件，把数据汇入缓冲区。"""
        self._subscriptions.append(
            self.bus.subscribe(TOPIC_SAMPLE_BATCH, self._on_sample_batch)
        )
        self._subscriptions.append(self.bus.subscribe(TOPIC_ALARM, self._on_alarm))

    def close(self) -> None:
        """解除订阅并落盘。"""
        for subscription in self._subscriptions:
            subscription.cancel()
        self._subscriptions.clear()
        if self.writer:
            self.writer.close()
        if self.gray_writer:
            self.gray_writer.close()

    # ------------------------------------------------------------------ 事件回调

    def _on_sample_batch(self, records: Sequence[SampleRecord]) -> None:
        """采样批次到达：缓冲 + 落盘。"""
        with self._lock:
            for record in records:
                self._latest[record.ch] = record
                self.buffer.append(record)
            if self.writer:
                self.writer.write_records(records)
                self.writer.flush()

    def _on_alarm(self, alarm: AlarmEvent) -> None:
        with self._lock:
            self._alarms.append(alarm)
            if len(self._alarms) > 1000:
                del self._alarms[:-1000]

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> None:
        """启动采集。"""
        if self.scheduler:
            self.scheduler.start()

    def stop(self) -> None:
        """停止采集并落盘。"""
        if self.scheduler:
            self.scheduler.stop()
        if self.writer:
            self.writer.flush(force=True)
        if self.gray_writer:
            self.gray_writer.flush(force=True)

    # ------------------------------------------------------------------ 实时数据

    def snapshot(self) -> RealtimeSnapshot:
        """取当前 A/B 状态快照（FR-6.1）。"""
        with self._lock:
            a = self._latest.get(Channel.A)
            b = self._latest.get(Channel.B)
            rh_diff = None
            if a and b and a.rh is not None and b.rh is not None:
                rh_diff = abs(a.rh - b.rh)
            flags: list[str] = []
            for record in (a, b):
                if record:
                    flags.extend(record.flag.codes)
            preview = None
            if a is not None and a.pm25 is not None:
                feed = self.config.acquisition.cfeed
                if feed and feed > 0:
                    preview = eff.eta_a(feed, a.pm25)
            return RealtimeSnapshot(
                ts=now_ms(),
                a=a,
                b=b,
                etaa_preview=preview,
                rh_diff=rh_diff,
                flags=sorted(set(flags)),
            )

    def recent(self, channel: Channel | None = None, window_s: float = 60.0) -> list[SampleRecord]:
        """取最近窗口的采样（FR-6.3：60 s 滚动曲线）。"""
        items = self.buffer.window()
        if channel is not None:
            items = [i for i in items if i.ch == channel]
        return items

    def alarms(self, limit: int = 100) -> list[AlarmEvent]:
        """最近的告警列表。"""
        with self._lock:
            return list(self._alarms[-limit:])

    def status(self) -> dict[str, object]:
        """运行状态（自检与状态栏）。"""
        status: dict[str, object] = {}
        if self.scheduler:
            status["scheduler"] = self.scheduler.status.to_dict()
        if self.writer:
            status["writer"] = self.writer.status()
        status["buffer"] = len(self.buffer)
        return status

    # ------------------------------------------------------------------ 灰度

    def submit_gray_frames(self, frames: Sequence[GrayFrame]) -> None:
        """写入灰度帧（由视频线程调用）并落盘。"""
        with self._lock:
            self.gray_buffer.extend(frames)
            if len(self.gray_buffer) > 20000:
                del self.gray_buffer[:-20000]
        if self.gray_writer:
            for frame in frames:
                self.gray_writer.write_frame(frame)
            self.gray_writer.flush()

    def align_gray(self, tolerance_ms: float | None = None) -> tuple[list[SampleRecord], object]:
        """把缓冲的灰度帧与采样对齐（SRS 5.3）。"""
        tol = (
            tolerance_ms
            if tolerance_ms is not None
            else self.config.acquisition.align_tolerance_ms
        )
        samples = self.buffer.snapshot()
        with self._lock:
            frames = list(self.gray_buffer)
        return align_frames_to_samples(samples, frames, tol)

    def extract_gray_from_video(
        self,
        target: str | int,
        is_camera: bool = False,
        roi: tuple[int, int, int, int] | None = None,
        dark_baseline: gray_mod.DarkBaseline | None = None,
        limit_frames: int | None = None,
    ) -> list[GrayFrame]:
        """从视频/相机逐帧提取灰度（FR-4）。

        本方法在 **调用方线程** 执行（离线分析），返回帧序列。
        """
        from ..device.video import VideoDriver, VideoSource  # noqa: PLC0415

        roi = roi or self.config.roi.as_tuple
        if not self.config.roi.is_set and roi == (0, 0, 0, 0):
            raise ValueError("未设置 ROI 坐标，无法提取灰度")

        driver = VideoDriver(VideoSource(target, is_camera), self.config.video.fps)
        frames: list[GrayFrame] = []
        try:
            driver.open()
            for index, video_frame in enumerate(driver.iter_frames()):
                if limit_frames is not None and index >= limit_frames:
                    break
                frames.append(
                    gray_mod.extract_frame_grayness(
                        video_frame.gray, roi, dark_baseline, video_frame.ts, index
                    )
                )
        finally:
            driver.close()
        return frames

    # ------------------------------------------------------------------ 标定

    def run_calibration(
        self,
        pairs: Sequence[tuple[float, float]],
        expid: str = "",
    ) -> CalibrationResult:
        """执行灰度—浓度标定拟合（FR-7.1 / FR-7.2）。"""
        threshold = self.config.thresholds.r2_threshold
        result = calib.fit_from_pairs(
            pairs, threshold=threshold, source_expid=expid, created_at=now_ms()
        )
        with self._lock:
            self._calibration = result
        return result

    def current_calibration(self) -> CalibrationResult | None:
        """当前有效的标定结果。"""
        with self._lock:
            return self._calibration

    def persist_calibration(self, result: CalibrationResult, path: str | Path | None = None) -> Path | None:
        """把标定系数写回配置（FR-10.1：标定系数可配置；FR-2.4 约束 4：可回溯）。"""
        if path is None:
            return None
        from ..config.schema import CalibrationConfig, dump_json  # noqa: PLC0415

        new_config = self.config.with_overrides(
            calibration=CalibrationConfig(
                alpha=result.alpha,
                beta=result.beta,
                r2=result.r2,
                threshold=result.threshold,
                source_expid=result.source_expid,
                updated_at=result.created_at,
                valid=True,
            )
        )
        self.config = new_config
        return dump_json(new_config, path)

    # ------------------------------------------------------------------ 效率

    def compute_efficiency(
        self,
        samples: Sequence[SampleRecord] | None = None,
        cfeed: float | Callable[[float], float | None] | None = None,
    ) -> eff.EfficiencySeries:
        """计算 η_A 序列（FR-8.1 / FR-8.3）。"""
        records = list(samples) if samples is not None else self.buffer.snapshot()
        feed = cfeed if cfeed is not None else 0.0
        return eff.compute_efficiency(records, feed, Channel.A)

    # ------------------------------------------------------------------ 分流比 / 压降

    def compute_split_ratio(
        self, velocities_a: Sequence[float], velocities_b: Sequence[float]
    ) -> flow_mod.SplitRatioResult:
        """分流比计算与判定（FR-3.3 / FR-7.3）。"""
        return flow_mod.compute_split_ratio(
            velocities_a, velocities_b, self.config.thresholds.split_ratio
        )

    def evaluate_plunge_dp(self, dp_pa: float) -> flow_mod.PlungeDpResult:
        """单元压降判据（FR-7.4）。"""
        return flow_mod.evaluate_plunge_dp(dp_pa)

    # ------------------------------------------------------------------ 历史数据

    def list_experiments(self) -> list[str]:
        """列出历史实验编号（FR-5.3）。"""
        if not self.meta_store:
            return []
        return self.meta_store.list_experiments()

    def query_history(self, expid: str, **kwargs) -> SampleQuery:
        """按实验编号检索历史数据（FR-5.3）。"""
        if not self.reader:
            return SampleQuery(expid=expid)
        return self.reader.query(expid, **kwargs)

    def replay_summary(self, expid: str) -> dict[str, object]:
        """历史数据回放摘要（FR-5.3：曲线 + 统计摘要）。"""
        if not self.reader:
            return {}
        return self.reader.experiment_summary(expid)

    def save_experiment_meta(self, meta) -> Path | None:
        """保存实验元数据（FR-5.2）。"""
        if not self.meta_store:
            return None
        return self.meta_store.save(meta)

    # ------------------------------------------------------------------ 报告导出

    def export_report(
        self,
        expid: str,
        out_dir: str | Path | None = None,
        cfeed: float | Callable[[float], float | None] | None = None,
    ) -> ReportBundle:
        """一键导出实验报告（FR-9.1 / FR-9.2）。

        :param expid: 实验编号
        :param out_dir: 输出目录，默认取配置的 ``report_dir``
        :param cfeed: 参考浓度（常量或 ``f(ts)``）
        """
        if not self.reader:
            raise RuntimeError("未配置历史数据读取器，无法导出报告")

        base = Path(out_dir) if out_dir else Path(self.config.storage.report_dir)
        base.mkdir(parents=True, exist_ok=True)

        records = self.reader.read_all(expid)
        meta = self.meta_store.load(expid) if self.meta_store else None
        if meta is None:
            from ..core.types import ExperimentMeta  # noqa: PLC0415

            meta = ExperimentMeta(expid=expid, date="")

        series = eff.compute_efficiency(records, cfeed if cfeed is not None else 0.0, Channel.A)
        calibration = self.current_calibration()

        bundle = ReportBundle(expid=expid)
        bundle.docx_path = export_docx(
            base / f"{expid}_report.docx",
            meta,
            records,
            calibration,
            series.results,
            self.config.uncertainty_note,
        )
        bundle.xlsx_path = export_xlsx(
            base / f"{expid}_report.xlsx",
            meta,
            records,
            calibration,
            series.results,
            self.config.uncertainty_note,
        )
        with self._lock:
            gray_rows = [f.to_row() for f in self.gray_buffer]
        bundle.csv_paths = export_csv_bundle(base, records, gray_rows, expid)
        return bundle

    # ------------------------------------------------------------------ 自检

    def self_check(self) -> "SelfCheckReport":
        """启动自检（FR-10.2）：串口枚举、传感器帧握手、视频源可用性、配置合法性。"""
        from .selfcheck import SelfCheckReport, run_self_check  # noqa: PLC0415

        return run_self_check(self.config, self.scheduler)

    def metrics(self, samples: Sequence[SampleRecord]) -> dict[str, metrics_mod.NumericSummary]:
        """统计摘要（FR-5.3）。"""
        return metrics_mod.summarize_series(
            {
                "pm25": [s.pm25 for s in samples],
                "pm10": [s.pm10 for s in samples],
                "rh": [s.rh for s in samples],
                "temp": [s.temp for s in samples],
                "gnorm": [s.gnorm for s in samples],
            }
        )
