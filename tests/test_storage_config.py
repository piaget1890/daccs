"""存储层与配置层单元测试（FR-5 / FR-9 / FR-10）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from daccs.config.loader import load_config, save_config
from daccs.config.schema import AppConfig, ConfigError, validate
from daccs.core.types import Channel, DataFlag, ExperimentMeta, SampleRecord
from daccs.storage.buffer import RollingBuffer
from daccs.storage.meta import ExperimentStore
from daccs.storage.reader import HistoryReader
from daccs.storage.report import export_csv_bundle, export_docx, export_xlsx
from daccs.storage.writer import SAMPLE_CSV_HEADER, CsvAppendWriter


def make_record(ts: float, ch: Channel = Channel.A, pm25: float = 12.0) -> SampleRecord:
    return SampleRecord(
        ts=ts, ch=ch, pm25=pm25, pm10=pm25 * 1.5, rh=55.0, temp=25.0, gnorm=42.0
    )


class TestCsvAppendWriter(unittest.TestCase):
    def test_append_only_and_roundtrip(self) -> None:
        """SRS 2.4 约束 3：原始数据只追加不覆盖。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "samples.csv"
            writer = CsvAppendWriter(path)
            writer.write_record(make_record(1000.0))
            writer.flush(force=True)
            writer.write_record(make_record(2000.0))
            writer.flush(force=True)
            writer.close()

            text = path.read_text(encoding="utf-8-sig")
            self.assertIn(",".join(SAMPLE_CSV_HEADER), text)
            self.assertEqual(len(text.strip().splitlines()), 3)  # 表头 + 2 行

            # 再次追加不会覆盖已有内容
            writer2 = CsvAppendWriter(path)
            writer2.write_record(make_record(3000.0))
            writer2.flush(force=True)
            writer2.close()
            self.assertEqual(len(path.read_text(encoding="utf-8-sig").strip().splitlines()), 4)

    def test_bom_for_excel(self) -> None:
        """SRS 6.4：CSV 使用 UTF-8 BOM。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "samples.csv"
            writer = CsvAppendWriter(path)
            writer.write_record(make_record(1000.0))
            writer.flush(force=True)
            writer.close()
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_flag_codes_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "samples.csv"
            writer = CsvAppendWriter(path)
            record = SampleRecord(ts=1000.0, ch=Channel.A, pm25=1.0,
                                  flag=DataFlag.RH_DIVERGENCE)
            writer.write_record(record)
            writer.flush(force=True)
            writer.close()
            self.assertIn("RH_DIVERGENCE", path.read_text(encoding="utf-8-sig"))


class TestHistoryReader(unittest.TestCase):
    def test_query_and_summary(self) -> None:
        """FR-5.3：按实验编号检索与统计摘要。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exp_dir = root / "EXP-001"
            exp_dir.mkdir()
            writer = CsvAppendWriter(exp_dir / "samples.csv")
            for i in range(5):
                writer.write_record(make_record(1000.0 + i * 1000.0, pm25=10.0 * (i + 1)))
            writer.flush(force=True)
            writer.close()

            reader = HistoryReader(root)
            query = reader.query("EXP-001")
            self.assertEqual(len(query.records), 5)
            self.assertTrue(all(r.ch == Channel.A for r in query.records))

            summary = reader.experiment_summary("EXP-001")
            self.assertEqual(summary["count"], 5)
            pm25 = summary["summary"]["pm25"]
            self.assertEqual(pm25["count"], 5)
            self.assertAlmostEqual(pm25["min"], 10.0)
            self.assertAlmostEqual(pm25["max"], 50.0)

    def test_missing_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reader = HistoryReader(Path(tmp))
            self.assertEqual(reader.read_all("NOPE"), [])


class TestExperimentStore(unittest.TestCase):
    def test_save_and_load(self) -> None:
        """FR-5.2：实验元数据录入与归档。"""
        with tempfile.TemporaryDirectory() as tmp:
            store = ExperimentStore(Path(tmp))
            meta = ExperimentMeta(
                expid="EXP-001",
                date="2026-11-27",
                smokesource="香烟",
                valve="3/4",
                ledlevel="5",
                operator="张工",
            )
            store.save(meta)
            loaded = store.load("EXP-001")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.operator, "张工")
            self.assertEqual(store.list_experiments(), ["EXP-001"])


class TestRollingBuffer(unittest.TestCase):
    def test_window_filtering(self) -> None:
        """FR-6.3：滚动窗口只保留窗口内的记录。"""
        buffer = RollingBuffer(maxlen=100, window_s=3.0)
        for i in range(10):
            buffer.append(make_record(1000.0 * i))
        self.assertEqual(len(buffer), 10)
        window = buffer.window(now_ms=9 * 1000.0)
        self.assertEqual(len(window), 4)  # 6s、7s、8s、9s
        self.assertTrue(all(r.ts >= 6 * 1000.0 for r in window))

    def test_maxlen_bounds_memory(self) -> None:
        buffer = RollingBuffer(maxlen=5, window_s=60.0)
        for i in range(20):
            buffer.append(make_record(1000.0 * i))
        self.assertEqual(len(buffer), 5)


class TestConfig(unittest.TestCase):
    def test_default_config_is_valid(self) -> None:
        config = AppConfig.from_dict({})
        problems = validate(config)
        # 默认配置没有传感器，会提示；其余不应报错
        self.assertTrue(all("传感器" in p for p in problems), problems)

    def test_bundled_default_loads(self) -> None:
        config = load_config(strict=False)
        self.assertGreaterEqual(len(config.sensors), 4)
        self.assertEqual(config.thresholds.rh_divergence_pct, 5.0)
        self.assertEqual(config.thresholds.split_ratio, 1.05)

    def test_save_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            config = load_config(strict=False)
            save_config(config, path)
            reloaded = load_config(path, strict=False)
            self.assertEqual(len(reloaded.sensors), len(config.sensors))

    def test_invalid_roi_expand_factor(self) -> None:
        config = AppConfig.from_dict({"roi": {"x": 0, "y": 0, "w": 10, "h": 10, "expand_factor": 0.5}})
        self.assertTrue(any("外扩" in p for p in validate(config)))

    def test_missing_uncertainty_note_is_problem(self) -> None:
        """SRS 2.4 约束 5：不确定度声明强制。"""
        config = AppConfig.from_dict({"uncertainty_note": "  "})
        self.assertTrue(any("不确定度" in p for p in validate(config)))


class TestReportExport(unittest.TestCase):
    def test_export_all_three_artifacts(self) -> None:
        """FR-9.1 / FR-9.2 / TC-6：DOCX + XLSX + CSV 三件。"""
        from daccs.algorithm.calibration import fit_from_pairs
        from daccs.algorithm.efficiency import compute_efficiency

        with tempfile.TemporaryDirectory() as tmp:
            samples = [make_record(1000.0 * i, pm25=10.0 * (i + 1)) for i in range(5)]
            meta = ExperimentMeta(expid="EXP-001", date="2026-11-27")
            calibration = fit_from_pairs(
                [(10.0, 100.0), (20.0, 200.0), (30.0, 300.0), (40.0, 400.0), (50.0, 500.0)],
                source_expid="EXP-001",
            )
            series = compute_efficiency(samples, cfeed=1000.0)

            docx_path = export_docx(
                Path(tmp) / "r.docx", meta, samples, calibration, series.results
            )
            xlsx_path = export_xlsx(
                Path(tmp) / "r.xlsx", meta, samples, calibration, series.results
            )
            csv_paths = export_csv_bundle(Path(tmp), samples, [], "EXP-001")

            self.assertTrue(docx_path.exists())
            self.assertTrue(xlsx_path.exists())
            self.assertTrue(csv_paths and csv_paths[0].exists())
            self.assertGreater(docx_path.stat().st_size, 1000)
            self.assertGreater(xlsx_path.stat().st_size, 1000)

    def test_missing_uncertainty_note_is_rejected(self) -> None:
        """报告必须携带不确定度声明。"""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                export_docx(
                    Path(tmp) / "r.docx",
                    ExperimentMeta(expid="E", date=""),
                    [],
                    None,
                    [],
                    uncertainty_note="",
                )


if __name__ == "__main__":
    unittest.main()
