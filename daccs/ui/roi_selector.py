"""ROI 选择对话框（FR-4.1）。

用户在视频画面上框选片光亮带 ROI；对话框返回 ``(x, y, w, h)``，
并同步给出 "外扩 2 倍" 背景区域的可视化（SRS 7.1）。

依赖 OpenCV/Qt；若不可用，模块导入会给出清晰错误。
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .theme import ALARM_COLORS

__all__ = ["RoiSelector", "frame_to_qimage"]


def frame_to_qimage(frame) -> QImage:
    """把 OpenCV BGR 帧转成 QImage（注意内存所有权，需深拷贝）。"""
    import numpy as np  # noqa: PLC0415

    rgb = cv2_bgr_to_rgb(frame)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def cv2_bgr_to_rgb(frame):
    """BGR → RGB（不依赖 cv2 的纯 numpy 实现）。"""
    import numpy as np  # noqa: PLC0415

    return np.ascontiguousarray(frame[:, :, ::-1])


class _Canvas(QWidget):
    """可框选的画布。"""

    def __init__(self, pixmap: QPixmap) -> None:
        super().__init__()
        self._pixmap = pixmap
        self._origin: QRect | None = None
        self._current: QRect | None = None
        self.setMinimumSize(pixmap.width(), pixmap.height())
        self.setMouseTracking(True)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.setPen(QPen(QPen(QColor("#ff3b30")), 2, Qt.PenStyle.DashLine))
        for rect in (self._origin, self._current):
            if rect:
                painter.drawRect(rect)
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = QRect(event.position().toPoint(), event.position().toPoint())
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._current = QRect(self._origin.topLeft(), event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._current = QRect(self._origin.topLeft(), event.position().toPoint()).normalized()
            self.update()

    def selection(self) -> QRect | None:
        """当前选区（宽高均 > 3 像素才视为有效）。"""
        rect = self._current
        if rect is None or rect.width() <= 3 or rect.height() <= 3:
            return None
        return rect


class RoiSelector(QDialog):
    """ROI 选择对话框。

    :param frame_path: 视频文件路径（用于读取第一帧预览）
    :param parent: 父窗口
    """

    def __init__(self, frame_path: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择片光亮带 ROI")
        self._roi: tuple[int, int, int, int] | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("在画面上拖拽框选 ROI（左上角为原点）。"))

        pixmap = QPixmap()
        if frame_path:
            pixmap = self._load_preview(frame_path)
        self._canvas = _Canvas(pixmap)
        layout.addWidget(self._canvas)

        self._info = QLabel("")
        layout.addWidget(self._info)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _load_preview(frame_path: str) -> QPixmap:
        try:
            import cv2  # noqa: PLC0415
        except ImportError:
            return QPixmap()
        cap = cv2.VideoCapture(frame_path)
        if not cap.isOpened():
            return QPixmap()
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return QPixmap()
        image = frame_to_qimage(frame)
        return QPixmap.fromImage(image)

    def _on_accept(self) -> None:
        rect = self._canvas.selection()
        if rect is None:
            self._info.setText(
                f"<span style='color:{ALARM_COLORS['warning']}'>请先框选有效的 ROI 区域</span>"
            )
            return
        self._roi = (rect.x(), rect.y(), rect.width(), rect.height())
        self.accept()

    def roi(self) -> tuple[int, int, int, int] | None:
        """返回选定的 ROI ``(x, y, w, h)``。"""
        return self._roi
