"""实时滚动曲线控件（FR-6.3：60 s 滚动曲线）。

用 QPainter 自绘，避免引入 pyqtgraph/matplotlib 的额外打包体积，
也便于精确控制"60 s 窗口 + 采样点稀疏"的表现。

曲线数据来自 :class:`daccs.core.service.ApplicationService` 的
``recent()`` 返回值 —— 界面 **不自己** 保存原始数据，避免与
存储层产生两份真相。
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core.types import Channel, SampleRecord
from .theme import COLOR_MUTED, COLOR_TEXT, FONT_FAMILY, MIN_FONT_POINT

__all__ = ["RealtimeChart"]

SERIES = (
    ("pm25", "PM2.5 (μg/m³)", "#2f6feb"),
    ("pm10", "PM10 (μg/m³)", "#20a0a0"),
    ("rh", "RH (%RH)", "#b7791f"),
    ("gnorm", "Gnorm", "#7a4fd3"),
)


class RealtimeChart(QWidget):
    """多通道 60 s 滚动曲线。"""

    def __init__(self, window_s: float = 60.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window_s = window_s
        self._records: list[SampleRecord] = []
        self._channel = Channel.A
        self._series = "pm25"
        self.setMinimumHeight(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        header = QHBoxLayout()
        header.addWidget(QLabel("显示量："))
        self._series_box = QComboBox()
        for key, label, _color in SERIES:
            self._series_box.addItem(label, key)
        header.addWidget(self._series_box)

        header.addWidget(QLabel("支路："))
        self._channel_box = QComboBox()
        self._channel_box.addItem("A 支路", Channel.A.value)
        self._channel_box.addItem("B 支路", Channel.B.value)
        header.addWidget(self._channel_box)
        header.addStretch(1)
        layout.addLayout(header)

        self._canvas = QWidget(self)
        self._canvas.setMinimumHeight(180)
        layout.addWidget(self._canvas)
        self._canvas.installEventFilter(self)

        self._series_box.currentIndexChanged.connect(self._on_series_changed)
        self._channel_box.currentIndexChanged.connect(self._on_channel_changed)

    # ------------------------------------------------------------------ 数据

    def set_records(self, records: Sequence[SampleRecord]) -> None:
        """更新曲线数据（由主窗口在收到批次时调用）。"""
        self._records = list(records)
        self._canvas.update()

    def _on_series_changed(self, _index: int) -> None:
        key = self._series_box.currentData()
        self._series = key
        self._canvas.update()

    def _on_channel_changed(self, _index: int) -> None:
        self._channel = Channel(self._channel_box.currentData())
        self._canvas.update()

    # ------------------------------------------------------------------ 绘制

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 命名
        if obj is self._canvas and event.type() == event.Type.Paint:
            self._paint(self._canvas)
            return True
        return super().eventFilter(obj, event)

    def _paint(self, widget: QWidget) -> None:
        painter = QPainter(widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(widget.rect()).adjusted(40, 10, -10, -24)

        painter.fillRect(widget.rect(), QColor("#ffffff"))
        self._draw_grid(painter, rect)

        values = [
            getattr(r, self._series)
            for r in self._records
            if r.ch == self._channel and getattr(r, self._series) is not None
        ]
        if len(values) < 2:
            painter.setPen(QColor(COLOR_MUTED))
            painter.drawText(
                widget.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "暂无数据（等待采集或切换显示量）",
            )
            painter.end()
            return

        times = [r.ts for r in self._records if r.ch == self._channel]
        t_max = max(times)
        t_min = t_max - self._window_s * 1000.0
        v_min, v_max = min(values), max(values)
        if abs(v_max - v_min) < 1e-9:
            v_min -= 1.0
            v_max += 1.0

        color = next(c for _k, _l, c in SERIES if _k == self._series)
        painter.setPen(QPen(QColor(color), 1.8))
        path_points: list[QPointF] = []
        for record, value in zip(
            [r for r in self._records if r.ch == self._channel], values
        ):
            x = rect.left() + (record.ts - t_min) / max(1.0, (t_max - t_min)) * rect.width()
            y = rect.bottom() - (value - v_min) / (v_max - v_min) * rect.height()
            path_points.append(QPointF(x, y))
        painter.drawPolyline(path_points)

        painter.setPen(QColor(COLOR_TEXT))
        painter.drawText(QRectF(0, rect.top() - 2, 38, 16), Qt.AlignmentFlag.AlignRight, f"{v_max:.2f}")
        painter.drawText(
            QRectF(0, rect.bottom() - 14, 38, 16), Qt.AlignmentFlag.AlignRight, f"{v_min:.2f}"
        )
        painter.setPen(QColor(COLOR_MUTED))
        painter.setFont(painter.font())
        painter.drawText(
            QRectF(rect.left(), rect.bottom() + 4, rect.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            f"最近 {self._window_s:.0f} 秒",
        )
        painter.end()
        _ = FONT_FAMILY, MIN_FONT_POINT

    @staticmethod
    def _draw_grid(painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor("#e6e8eb"), 1))
        for i in range(1, 4):
            y = rect.top() + rect.height() * i / 4
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
