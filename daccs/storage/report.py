"""报告导出（FR-9）。

* :func:`export_docx` —— 生成实验报告 DOCX（FR-9.1）
* :func:`export_xlsx` —— 生成实验报告 XLSX（FR-9.1）
* :func:`export_csv_bundle` —— 导出原始 CSV 与灰度时间序列 CSV（FR-9.2）

报告 **强制** 包含不确定度声明（SRS 2.4 约束 5 / 附录 3）：
"传感器壁面采样 ±10%~15%、灰度—浓度非线性"，不得以软件计算结果冒充
标准方法结论。若调用方未传入声明文本，导出函数会直接报错而不是静默省略。
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ..core.types import CalibrationResult, EfficiencyResult, ExperimentMeta, SampleRecord

__all__ = [
    "ReportBundle",
    "export_docx",
    "export_xlsx",
    "export_csv_bundle",
    "UNCERTAINTY_TEXT",
]

logger = logging.getLogger(__name__)

#: 强制附带的不确定度声明（SRS 2.4 约束 5）
UNCERTAINTY_TEXT = (
    "不确定度声明：传感器壁面采样存在 ±10%~15% 偏差；灰度—浓度关系并非严格线性，"
    "本报告数据由软件计算生成，仅供装置调试与趋势分析，不构成标准方法结论。"
)


@dataclass(slots=True)
class ReportBundle:
    """一次导出产生的文件清单。"""

    expid: str
    docx_path: Path | None = None
    xlsx_path: Path | None = None
    csv_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "expid": self.expid,
            "docx": str(self.docx_path) if self.docx_path else "",
            "xlsx": str(self.xlsx_path) if self.xlsx_path else "",
            "csv": [str(p) for p in self.csv_paths],
            "warnings": list(self.warnings),
        }


def export_docx(
    path: str | Path,
    meta: ExperimentMeta,
    samples: Sequence[SampleRecord],
    calibration: CalibrationResult | None,
    efficiency: Sequence[EfficiencyResult],
    uncertainty_note: str = UNCERTAINTY_TEXT,
    extra_sections: Sequence[tuple[str, Sequence[str]]] = (),
) -> Path:
    """导出 DOCX 报告（FR-9.1）。

    :param path: 输出文件路径（``.docx``）
    :param meta: 实验元数据
    :param samples: 采样记录（用于关键参数与统计摘要）
    :param calibration: 标定结果，可为 ``None``
    :param efficiency: 效率结果序列
    :param uncertainty_note: 不确定度声明；为空会抛错
    """
    from docx import Document  # noqa: PLC0415 - 延迟导入

    if not uncertainty_note.strip():
        raise ValueError("报告必须包含不确定度声明（SRS 2.4 约束 5）")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()
    doc.add_heading("数据采集与计算校准系统 实验报告", level=0)

    doc.add_heading("1. 实验元数据", level=1)
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for key, value in meta.to_dict().items():
        cells = table.add_row().cells
        cells[0].text = str(key)
        cells[1].text = str(value)

    doc.add_heading("2. 关键参数", level=1)
    stats = _sample_stats(samples)
    table2 = doc.add_table(rows=0, cols=4)
    table2.style = "Table Grid"
    for name, value in stats.items():
        cells = table2.add_row().cells
        cells[0].text = name
        cells[1].text = value
        cells[2].text = ""
        cells[3].text = ""

    doc.add_heading("3. 标定曲线与 R²", level=1)
    if calibration is None:
        doc.add_paragraph("本次实验未提供灰度—浓度标定结果。")
    else:
        doc.add_paragraph(
            f"拟合模型：C = α·Gnorm + β，α = {calibration.alpha:.6g}，"
            f"β = {calibration.beta:.6g}，R² = {calibration.r2:.6f}"
        )
        doc.add_paragraph(
            f"来源实验：{calibration.source_expid or '未标注'}；"
            f"判定阈值 R² ≥ {calibration.threshold}，"
            f"结论：{'通过' if calibration.passed else '未通过，需复测'}"
        )
        table3 = doc.add_table(rows=1, cols=4)
        table3.style = "Table Grid"
        for idx, head in enumerate(("序号", "Gnorm", "浓度(ug/m3)", "残差")):
            table3.rows[0].cells[idx].text = head
        for i, (g, c) in enumerate(zip(calibration.gnorm, calibration.concpoints), start=1):
            residual = calibration.residuals[i - 1] if i - 1 < len(calibration.residuals) else float("nan")
            cells = table3.add_row().cells
            cells[0].text = str(i)
            cells[1].text = f"{g:.6g}"
            cells[2].text = f"{c:.6g}"
            cells[3].text = f"{residual:.6g}"

    doc.add_heading("4. 单程效率 η_A", level=1)
    valid = [e for e in efficiency if e.valid and e.etaa is not None]
    if efficiency:
        doc.add_paragraph(
            f"有效区间 {len(valid)} / 总计 {len(efficiency)}"
            f"（有效率 {len(valid) / len(efficiency) * 100:.1f}%）；"
            f"η_A 均值 = {_mean([e.etaa for e in valid]):.4f}"
            if valid
            else f"全部区间均被数据质量判据排除，无有效 η_A 结果。"
        )
        table4 = doc.add_table(rows=1, cols=5)
        table4.style = "Table Grid"
        for idx, head in enumerate(("时间戳", "Cfeed", "CA,out", "η_A", "状态")):
            table4.rows[0].cells[idx].text = head
        for e in efficiency[:2000]:
            cells = table4.add_row().cells
            cells[0].text = e.ts_iso
            cells[1].text = "" if e.cfeed is None else f"{e.cfeed:.4g}"
            cells[2].text = "" if e.ca_out is None else f"{e.ca_out:.4g}"
            cells[3].text = "" if e.etaa is None else f"{e.etaa:.4f}"
            cells[4].text = "有效" if e.valid else (e.reason or "无效")
    else:
        doc.add_paragraph("本次实验无效率计算结果。")

    for title, lines in extra_sections:
        doc.add_heading(title, level=1)
        for line in lines:
            doc.add_paragraph(line)

    doc.add_heading("附：不确定度声明", level=1)
    doc.add_paragraph(uncertainty_note)

    doc.save(str(target))
    logger.info("DOCX 报告已导出：%s", target)
    return target


def export_xlsx(
    path: str | Path,
    meta: ExperimentMeta,
    samples: Sequence[SampleRecord],
    calibration: CalibrationResult | None,
    efficiency: Sequence[EfficiencyResult],
    uncertainty_note: str = UNCERTAINTY_TEXT,
) -> Path:
    """导出 XLSX 报告（FR-9.1），含多个工作表。"""
    from openpyxl import Workbook  # noqa: PLC0415
    from openpyxl.styles import Font  # noqa: PLC0415

    if not uncertainty_note.strip():
        raise ValueError("报告必须包含不确定度声明（SRS 2.4 约束 5）")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()

    ws = wb.active
    ws.title = "实验元数据"
    for key, value in meta.to_dict().items():
        ws.append([key, value])
    ws["A1"].font = Font(bold=True)

    ws2 = wb.create_sheet("采样数据")
    ws2.append(["时间戳", "通道", "PM2.5", "PM10", "RH", "T", "Gnorm", "标记位"])
    for record in samples:
        ws2.append(
            [
                record.ts_iso,
                record.ch.value,
                record.pm25,
                record.pm10,
                record.rh,
                record.temp,
                record.gnorm,
                ";".join(record.flag.codes),
            ]
        )

    ws3 = wb.create_sheet("标定")
    ws3.append(["α", "β", "R²", "阈值", "来源实验", "判定"])
    if calibration is not None:
        ws3.append(
            [
                calibration.alpha,
                calibration.beta,
                calibration.r2,
                calibration.threshold,
                calibration.source_expid,
                "通过" if calibration.passed else "未通过",
            ]
        )
    else:
        ws3.append(["无标定结果"])

    ws3b = wb.create_sheet("标定点")
    ws3b.append(["序号", "Gnorm", "浓度(ug/m3)", "残差"])
    if calibration is not None:
        for i, (g, c) in enumerate(zip(calibration.gnorm, calibration.concpoints), start=1):
            residual = calibration.residuals[i - 1] if i - 1 < len(calibration.residuals) else None
            ws3b.append([i, g, c, residual])

    ws4 = wb.create_sheet("效率结果")
    ws4.append(["时间戳", "Cfeed", "CA,out", "η_A", "有效", "说明"])
    for e in efficiency:
        ws4.append([e.ts_iso, e.cfeed, e.ca_out, e.etaa, "是" if e.valid else "否", e.reason])

    ws5 = wb.create_sheet("统计摘要")
    ws5.append(["指标", "最小", "最大", "均值", "中位数", "标准差", "样本数"])
    for name, stats in _stats_dict(samples).items():
        ws5.append(
            [
                name,
                stats.minimum,
                stats.maximum,
                stats.mean,
                stats.median,
                stats.stdev,
                stats.count,
            ]
        )

    ws6 = wb.create_sheet("不确定度声明")
    ws6["A1"] = uncertainty_note
    ws6["A1"].font = Font(bold=True)

    wb.save(str(target))
    logger.info("XLSX 报告已导出：%s", target)
    return target


def export_csv_bundle(
    out_dir: str | Path,
    samples: Sequence[SampleRecord],
    gray_rows: Sequence[Sequence[str]] = (),
    expid: str = "",
) -> list[Path]:
    """导出原始 CSV 与灰度时间序列 CSV（FR-9.2）。

    :param out_dir: 输出目录
    :param samples: 采样记录
    :param gray_rows: 灰度时间序列行
    :param expid: 实验编号（用于文件命名）
    """
    from .writer import GRAY_CSV_HEADER, SAMPLE_CSV_HEADER, _csv_escape

    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    prefix = f"{expid}_" if expid else ""
    written: list[Path] = []

    raw_path = target / f"{prefix}samples.csv"
    with open(raw_path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(",".join(SAMPLE_CSV_HEADER) + "\n")
        for record in samples:
            fh.write(",".join(_csv_escape(str(c)) for c in record.to_row()) + "\n")
    written.append(raw_path)

    if gray_rows:
        gray_path = target / f"{prefix}gray.csv"
        with open(gray_path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(",".join(GRAY_CSV_HEADER) + "\n")
            for row in gray_rows:
                fh.write(",".join(_csv_escape(str(c)) for c in row) + "\n")
        written.append(gray_path)

    logger.info("CSV 数据已导出：%s", target)
    return written


def _sample_stats(samples: Sequence[SampleRecord]) -> dict[str, str]:
    stats = _stats_dict(samples)
    out: dict[str, str] = {}
    for name, s in stats.items():
        out[f"{name} 均值"] = "" if s.mean is None else f"{s.mean:.4g}"
        out[f"{name} 最大"] = "" if s.maximum is None else f"{s.maximum:.4g}"
        out[f"{name} 样本数"] = str(s.count)
    out["记录总数"] = str(len(samples))
    return out


def _stats_dict(samples: Sequence[SampleRecord]):
    from ..algorithm.metrics import summarize

    return {
        "PM2.5": summarize(r.pm25 for r in samples),
        "PM10": summarize(r.pm10 for r in samples),
        "RH": summarize(r.rh for r in samples),
        "T": summarize(r.temp for r in samples),
        "Gnorm": summarize(r.gnorm for r in samples),
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def copy_tree(src: str | Path, dst: str | Path) -> Path:
    """复制目录（导出报告时把原始 CSV 一并打包）。"""
    source = Path(src)
    target = Path(dst)
    if source.exists():
        shutil.copytree(source, target, dirs_exist_ok=True)
    return target
