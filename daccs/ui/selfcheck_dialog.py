"""启动自检报告对话框（FR-10.2）。

把 :class:`daccs.core.selfcheck.SelfCheckReport` 渲染成清单：
通过项绿色 + "通过"，失败项红色 + 失败原因（颜色 + 文字双提示）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.selfcheck import SelfCheckReport
from .theme import ALARM_COLORS

__all__ = ["SelfCheckDialog"]


class SelfCheckDialog(QDialog):
    """自检结果展示。"""

    def __init__(self, report: SelfCheckReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("启动自检")
        self.setMinimumSize(560, 320)

        layout = QVBoxLayout(self)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["检查项", "结果", "详情"])
        self._tree.setRootIsDecorated(False)
        for item in report.items:
            tree_item = QTreeWidgetItem(
                self._tree,
                [
                    item.name,
                    "通过" if item.passed else "未通过",
                    item.detail,
                ],
            )
            color = ALARM_COLORS["info"] if item.passed else ALARM_COLORS["critical"]
            for column in range(3):
                tree_item.setForeground(column, _brush(color))
        self._tree.resizeColumnToContents(0)
        layout.addWidget(self._tree)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)


def _brush(color: str):
    from PySide6.QtGui import QBrush, QColor  # noqa: PLC0415

    return QBrush(QColor(color))
