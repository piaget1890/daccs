"""主窗口（FR-6）。

布局::

    ┌─────────────────────────────────────────────────────────┐
    │ 工具栏：开始/停止 │ 自检 │ 标定 │ 分流比 │ 压降 │ 导出   │
    ├───────────────┬───────────────┬─────────────────────────┤
    │ A 支路面板      │ B 支路面板      │ 告警列表面板             │
    │ 浓度/RH/T/灰度  │ 浓度/RH/T/灰度  │ （颜色 + 文字双提示）      │
    ├───────────────┴───────────────┴─────────────────────────┤
    │ 60 s 滚动曲线                                               │
    ├─────────────────────────────────────────────────────────┤
    │ 状态栏：运行状态 / 最新时间戳 / RH 差 / η_A 预估值           │
    └─────────────────────────────────────────────────────────┘

界面 **不持有** 任何业务逻辑：所有取数与计算都通过
:class:`daccs.core.service.ApplicationService`，数据更新全部由
:class:`daccs.ui.workers.BusBridge` 的信号驱动。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.service import ApplicationService
from ..core.types import AlarmEvent, Channel, SampleRecord
from .alarm import AlarmPanel
from .realtime_chart import RealtimeChart
from .selfcheck_dialog import SelfCheckDialog
from .theme import ALARM_COLORS, COLOR_MUTED, COLOR_TEXT, FONT_FAMILY, MIN_FONT_POINT
from .wizards import CalibrationWizard, PlungeDpWizard, SplitRatioWizard
from .workers import BusBridge

__all__ = ["MainWindow"]


class _ChannelPanel(QGroupBox):
    """单个支路的面板（FR-6.1：A/B 两栏）。"""

    def __init__(self, channel: Channel, parent: QWidget | None = None) -> None:
        super().__init__(f"{channel.value} 支路", parent)
        form = QFormLayout(self)
        self._pm25 = QLabel("—")
        self._pm10 = QLabel("—")
        self._rh = QLabel("—")
        self._temp = QLabel("—")
        self._gnorm = QLabel("—")
        self._flag = QLabel("—")
        for label in (self._pm25, self._pm10, self._rh, self._temp, self._gnorm):
            label.setStyleSheet(f"font-family: {FONT_FAMILY}; font-size: {MIN_FONT_POINT + 2}pt;")
        form.addRow("PM2.5 (μg/m³)：", self._pm25)
        form.addRow("PM10 (μg/m³)：", self._pm10)
        form.addRow("RH (%RH)：", self._rh)
        form.addRow("温度 (℃)：", self._temp)
        form.addRow("Gnorm：", self._gnorm)
        form.addRow("质量标记：", self._flag)

    def update(self, record: SampleRecord | None) -> None:
        """刷新面板内容。"""
        if record is None:
            for label in (self._pm25, self._pm10, self._rh, self._temp, self._gnorm):
                label.setText("—")
            self._flag.setText("—")
            return
        self._pm25.setText("—" if record.pm25 is None else f"{record.pm25:.1f}")
        self._pm10.setText("—" if record.pm10 is None else f"{record.pm10:.1f}")
        self._rh.setText("—" if record.rh is None else f"{record.rh:.1f}")
        self._temp.setText("—" if record.temp is None else f"{record.temp:.1f}")
        self._gnorm.setText("—" if record.gnorm is None else f"{record.gnorm:.2f}")
        codes = record.flag.codes
        self._flag.setText("、".join(codes) if codes else "正常")
        self._flag.setStyleSheet(
            f"color: {ALARM_COLORS['critical'] if codes else COLOR_MUTED};"
        )


class MainWindow(QMainWindow):
    """系统主窗口。"""

    def __init__(self, service: ApplicationService) -> None:
        super().__init__()
        self._service = service
        self.setWindowTitle("数据采集与计算校准系统")
        self.resize(1180, 760)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_toolbar())

        panels = QHBoxLayout()
        self._panel_a = _ChannelPanel(Channel.A)
        self._panel_b = _ChannelPanel(Channel.B)
        panels.addWidget(self._panel_a)
        panels.addWidget(self._panel_b)

        self._alarms = AlarmPanel()
        alarm_box = QGroupBox("告警")
        alarm_layout = QVBoxLayout(alarm_box)
        alarm_layout.addWidget(self._alarms)
        panels.addWidget(alarm_box, 1)
        root.addLayout(panels)

        self._chart = RealtimeChart(window_s=60.0)
        root.addWidget(self._chart)

        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet(f"color: {COLOR_MUTED};")
        self.statusBar().addWidget(self._status_label)

        self._bridge = BusBridge(service.bus)
        self._bridge.samples_ready.connect(self._on_samples)
        self._bridge.alarm_raised.connect(self._on_alarm)

    # ------------------------------------------------------------------ 工具栏

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        self._start_btn = QPushButton("开始采集")
        self._start_btn.clicked.connect(self._on_start)
        bar.addWidget(self._start_btn)

        self._stop_btn = QPushButton("停止采集")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        bar.addWidget(self._stop_btn)

        self._check_btn = QPushButton("启动自检")
        self._check_btn.clicked.connect(self._on_selfcheck)
        bar.addWidget(self._check_btn)

        self._calib_btn = QPushButton("标定向导")
        self._calib_btn.clicked.connect(self._on_calibration)
        bar.addWidget(self._calib_btn)

        self._ratio_btn = QPushButton("分流比标定")
        self._ratio_btn.clicked.connect(self._on_split_ratio)
        bar.addWidget(self._ratio_btn)

        self._dp_btn = QPushButton("压降标定")
        self._dp_btn.clicked.connect(self._on_plunge)
        bar.addWidget(self._dp_btn)

        self._export_btn = QPushButton("导出报告")
        self._export_btn.clicked.connect(self._on_export)
        bar.addWidget(self._export_btn)

        bar.addStretch(1)
        return bar

    # ------------------------------------------------------------------ 槽函数

    @Slot(list)
    def _on_samples(self, records: list) -> None:
        """收到采样批次：刷新面板与曲线（运行在 GUI 线程）。"""
        snapshot = self._service.snapshot()
        self._panel_a.update(snapshot.a)
        self._panel_b.update(snapshot.b)
        self._chart.set_records(self._service.recent())

        parts = [
            f"最近更新 {snapshot.ts_iso}",
            f"RH 差：{'—' if snapshot.rh_diff is None else f'{snapshot.rh_diff:.2f} %RH'}",
        ]
        if snapshot.etaa_preview is not None:
            parts.append(f"η_A 预估值：{snapshot.etaa_preview:.4f}")
        if snapshot.flags:
            parts.append("标记：" + "、".join(snapshot.flags))
        self._status_label.setText("　|　".join(parts))

    @Slot(object)
    def _on_alarm(self, alarm: AlarmEvent) -> None:
        """收到告警事件。"""
        self._alarms.add_alarm(alarm)

    # ------------------------------------------------------------------ 动作

    def _on_start(self) -> None:
        self._service.start()
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

    def _on_stop(self) -> None:
        self._service.stop()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _on_selfcheck(self) -> None:
        report = self._service.self_check()
        SelfCheckDialog(report, self).exec()

    def _on_calibration(self) -> None:
        CalibrationWizard(self._service, self).exec()

    def _on_split_ratio(self) -> None:
        SplitRatioWizard(self._service, self).exec()

    def _on_plunge(self) -> None:
        PlungeDpWizard(self._service, self).exec()

    def _on_export(self) -> None:
        expid = self._service.config.extra.get("current_expid", "")
        if not expid:
            QMessageBox.information(
                self, "导出报告", "请先在实验元数据中录入实验编号。"
            )
            return
        try:
            bundle = self._service.export_report(expid)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(
            self, "导出完成", f"已导出：\n{bundle.docx_path}\n{bundle.xlsx_path}"
        )

    # ------------------------------------------------------------------ 生命周期

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._service.stop()
        self._bridge.dispose()
        super().closeEvent(event)
