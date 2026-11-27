"""告警显示控件（FR-6.2 / NFR-4：颜色 + 文字双提示）。

每个告警同时给出 **颜色** 和 **文字标签**（"提示/警告/严重"），
保证在色觉障碍或黑白打印场景下仍可辨识。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..core.types import AlarmEvent, AlarmLevel
from .theme import ALARM_BACKGROUNDS, ALARM_COLORS, ALARM_LABELS, FONT_FAMILY, MIN_FONT_POINT

__all__ = ["AlarmBanner", "AlarmPanel"]


class AlarmBanner(QFrame):
    """单条告警显示条。"""

    def __init__(self, alarm: AlarmEvent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        level = str(alarm.level)
        self.setObjectName("alarmBanner")
        self.setStyleSheet(
            f"QFrame#alarmBanner {{"
            f"background-color: {ALARM_BACKGROUNDS.get(level, '#eef0f2')};"
            f"border-left: 4px solid {ALARM_COLORS.get(level, '#888')};"
            f"border-radius: 3px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        tag = QLabel(f"[{ALARM_LABELS.get(level, level)}]")
        tag.setStyleSheet(
            f"color: {ALARM_COLORS.get(level, '#888')}; font-weight: bold;"
            f"font-family: {FONT_FAMILY}; font-size: {MIN_FONT_POINT}pt;"
        )
        layout.addWidget(tag)

        text = QLabel(alarm.message)
        text.setWordWrap(True)
        text.setStyleSheet(
            f"color: #1f2329; font-family: {FONT_FAMILY}; font-size: {MIN_FONT_POINT}pt;"
        )
        layout.addWidget(text, 1)

        stamp = QLabel(alarm.ts_iso)
        stamp.setStyleSheet(f"color: #8a9099; font-family: {FONT_FAMILY};")
        layout.addWidget(stamp)


class AlarmPanel(QWidget):
    """告警列表面板：保留最近 N 条。"""

    def __init__(self, max_items: int = 50, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_items = max_items
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._layout = layout

    def add_alarm(self, alarm: AlarmEvent) -> None:
        """追加一条告警（超出上限时移除最旧的）。"""
        banner = AlarmBanner(alarm, self)
        self._layout.addWidget(banner)
        while self._layout.count() > self._max_items:
            oldest = self._layout.takeAt(0)
            widget = oldest.widget()
            if widget is not None:
                widget.deleteLater()

    def clear(self) -> None:
        """清空告警列表。"""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
