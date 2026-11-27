"""标定与判据向导（FR-7.1 ~ FR-7.4）。

* :class:`CalibrationWizard` —— 灰度—浓度标定向导（FR-7.1 / FR-7.2）
* :class:`SplitRatioWizard` —— 分流比标定记录（FR-7.3）
* :class:`PlungeDpWizard` —— 单元压降标定记录（FR-7.4）

三个向导都遵循同一交互范式：**表格录入 → 计算 → 结果展示 → 归档**，
并统一通过 :class:`daccs.core.service.ApplicationService` 调用内核，
向导本身不含任何计算公式。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..core.service import ApplicationService
from ..core.types import CalibrationResult
from .theme import ALARM_COLORS

__all__ = ["CalibrationWizard", "SplitRatioWizard", "PlungeDpWizard"]

#: FR-7.1 规定的 5 个标准浓度点
STANDARD_CONCENTRATIONS = (100.0, 200.0, 300.0, 500.0, 800.0)


class CalibrationWizard(QDialog):
    """灰度—浓度标定向导。

    :param service: 应用服务门面
    :param parent: 父窗口
    """

    def __init__(self, service: ApplicationService, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._result: CalibrationResult | None = None
        self.setWindowTitle("灰度—浓度标定向导")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        tip = QLabel(
            "录入 ≥ 5 个 (Gnorm, 浓度) 点，系统以最小二乘拟合 C = α·Gnorm + β。\n"
            "标准浓度点：100 / 200 / 300 / 500 / 800 μg/m³。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self._table = QTableWidget(5, 2)
        self._table.setHorizontalHeaderLabels(["Gnorm", "浓度 (μg/m³)"])
        self._table.horizontalHeader().setStretchLastSection(True)
        for row, conc in enumerate(STANDARD_CONCENTRATIONS):
            self._table.setItem(row, 1, QTableWidgetItem(f"{conc:g}"))
            self._table.setItem(row, 0, QTableWidgetItem(""))
        layout.addWidget(self._table)

        self._expid = QLineEdit()
        self._expid.setPlaceholderText("例如 EXP-20261127-01")
        layout.addWidget(QLabel("数据来源实验编号（可回溯，SRS 2.4 约束 4）："))
        layout.addWidget(self._expid)

        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        layout.addWidget(self._result_label)

        buttons = QHBoxLayout()
        self._fit_btn = QPushButton("执行拟合")
        self._fit_btn.clicked.connect(self._on_fit)
        buttons.addWidget(self._fit_btn)

        self._save_btn = QPushButton("保存标定系数")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)
        buttons.addWidget(self._save_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    # ------------------------------------------------------------------ 行为

    def _collect(self) -> list[tuple[float, float]]:
        pairs: list[tuple[float, float]] = []
        for row in range(self._table.rowCount()):
            g_item = self._table.item(row, 0)
            c_item = self._table.item(row, 1)
            if not g_item or not c_item:
                continue
            try:
                g = float(g_item.text().strip())
                c = float(c_item.text().strip())
            except ValueError:
                continue
            pairs.append((g, c))
        return pairs

    def _on_fit(self) -> None:
        pairs = self._collect()
        try:
            result = self._service.run_calibration(pairs, expid=self._expid.text().strip())
        except ValueError as exc:
            QMessageBox.warning(self, "标定失败", str(exc))
            return
        self._result = result
        verdict = "通过" if result.passed else "未通过（R² 低于阈值，需复测）"
        color = ALARM_COLORS["info"] if result.passed else ALARM_COLORS["critical"]
        self._result_label.setText(
            f"<b style='color:{color}'>α = {result.alpha:.6g}，β = {result.beta:.6g}，"
            f"R² = {result.r2:.6f}（阈值 {result.threshold}）—— {verdict}</b><br>"
            f"残差：{', '.join(f'{r:.4g}' for r in result.residuals)}"
        )
        self._save_btn.setEnabled(result.passed)

    def _on_save(self) -> None:
        if self._result is None:
            return
        from ..config.loader import default_config_path

        self._service.persist_calibration(self._result, default_config_path())
        QMessageBox.information(self, "已保存", "标定系数已写入配置文件。")
        self.accept()

    def result(self) -> CalibrationResult | None:
        """本次向导得到的标定结果。"""
        return self._result


class SplitRatioWizard(QDialog):
    """分流比标定向导（FR-7.3 / FR-3.3）。"""

    def __init__(self, service: ApplicationService, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("分流比标定")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("录入两支路各 3 点风速读数（m/s），输出 uA/uB 并判定是否 ≤ 1.05。"))

        form = QFormLayout()
        self._a_inputs = [QLineEdit() for _ in range(3)]
        self._b_inputs = [QLineEdit() for _ in range(3)]
        for i in range(3):
            self._a_inputs[i].setPlaceholderText("m/s")
            self._b_inputs[i].setPlaceholderText("m/s")
        for i in range(3):
            form.addRow(f"A 支路 第{i + 1}点：", self._a_inputs[i])
        for i in range(3):
            form.addRow(f"B 支路 第{i + 1}点：", self._b_inputs[i])
        layout.addLayout(form)

        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        layout.addWidget(self._result_label)

        btn = QPushButton("计算分流比")
        btn.clicked.connect(self._on_compute)
        layout.addWidget(btn)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _on_compute(self) -> None:
        try:
            a = [float(i.text()) for i in self._a_inputs]
            b = [float(i.text()) for i in self._b_inputs]
        except ValueError:
            QMessageBox.warning(self, "输入有误", "请填写 3 点有效风速读数。")
            return
        try:
            result = self._service.compute_split_ratio(a, b)
        except ValueError as exc:
            QMessageBox.warning(self, "计算失败", str(exc))
            return
        color = ALARM_COLORS["info"] if result.passed else ALARM_COLORS["critical"]
        self._result_label.setText(
            f"<span style='color:{color}'>平均 uA = {result.mean_a:.4f} m/s，"
            f"平均 uB = {result.mean_b:.4f} m/s，uA/uB = <b>{result.ratio:.4f}</b>"
            f"（阈值 {result.threshold}）—— {'通过' if result.passed else '超阈值，提示 B 侧重配平'}</span>"
        )


class PlungeDpWizard(QDialog):
    """单元压降标定向导（FR-7.4）。"""

    def __init__(self, service: ApplicationService, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("单元压降标定")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("录入微差压计读数 Δplung（Pa），与阈值 0.5 Pa 比较。"))

        form = QFormLayout()
        self._dp = QLineEdit()
        self._dp.setPlaceholderText("Pa")
        form.addRow("Δplung (Pa)：", self._dp)
        layout.addLayout(form)

        self._result_label = QLabel("")
        layout.addWidget(self._result_label)

        btn = QPushButton("判定")
        btn.clicked.connect(self._on_evaluate)
        layout.addWidget(btn)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def _on_evaluate(self) -> None:
        try:
            dp = float(self._dp.text())
        except ValueError:
            QMessageBox.warning(self, "输入有误", "请填写有效的压降读数。")
            return
        result = self._service.evaluate_plunge_dp(dp)
        color = ALARM_COLORS["info"] if result.passed else ALARM_COLORS["critical"]
        text = f"Δplung = {result.dp_pa:.4g} Pa（阈值 {result.threshold} Pa）—— "
        text += "合格" if result.passed else f"不合格。{result.suggestion}"
        self._result_label.setText(f"<span style='color:{color}'>{text}</span>")
