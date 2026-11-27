# 需求追溯矩阵（SRS → 模块 → 测试）

> 用于验收核对：每条 FR / NFR 都有明确的代码落点与验证手段。
> 依据 SRS 第 10 章「验收标准」与第 11 章「交付清单与里程碑」。

## 1. 功能需求（FR）

| 需求 | 说明 | 实现位置 | 验证 |
| --- | --- | --- | --- |
| FR-1.1 | 打开并识别两路 SDS011 串口，自动按 0xAA 0xC0 帧头对齐 | `device/sds011.py:parse_frames`、`device/serial_port.py` | `tests/test_sds011.py` |
| FR-1.2 | 解析 8 字节帧、校验和、坏帧丢弃并计数 | `device/sds011.py:parse_frame/SDS011Driver.checksum_errors` | `test_sds011.py::TestParseFrame/TestParseFrames` |
| FR-1.3 | 实时显示两路 PM2.5/PM10 与 60 s 趋势曲线 | `ui/main_window.py:_ChannelPanel`、`ui/realtime_chart.py` | 人工（TC-1） |
| FR-1.4 | 断线自动重连（指数退避，最长 5 s），记录事件 | `device/base.py:ReconnectPolicy/Driver.reconnect` | `test_integration.py::TestReconnectPolicy` |
| FR-2.1 | 读取两支路温湿度，1 Hz | `device/sht31.py`、`core/scheduler.py` | 人工（TC-2） |
| FR-2.2 | 实时计算 RH 差；>5%RH 告警并标记不可用于 η_A | `core/quality.py:check_rh_divergence`、`core/scheduler.py:apply_quality` | `test_efficiency.py::test_rh_divergence_threshold`、`test_integration.py::test_batch_published_and_flags_applied` |
| FR-2.3 | 35±1℃ 恒温罩场景 RH 差复测记录 | `storage/meta.py` + `storage/reader.py`（按实验编号归档） | 人工 |
| FR-3.1 | RS485 读取风速与微差压变送器（Modbus RTU） | `device/modbus_rs485.py` | 人工 |
| FR-3.2 | 手动录入离线量具读数，与在线值同表归档 | `core/types.py:SampleRecord.wind_speed_ms/dp_pa`、`storage/writer.py`（CSV 同表） | `test_storage_config.py::TestCsvAppendWriter` |
| FR-3.3 | 分流比计算：各 3 点流速 → 平均流速与 uA/uB，判定 ≤1.05 | `algorithm/flow.py:compute_split_ratio` | `test_flow_align.py::TestSplitRatio` |
| FR-4.1 | 读取 MP4 / UVC，逐帧提取指定 ROI | `device/video.py`、`ui/roi_selector.py` | 人工（TC-3） |
| FR-4.2 | ROI 内 95 百分位 GROI 与外扩 2 倍区域 95 百分位 Gbg | `algorithm/grayscale.py:extract_groi/extract_gbg` | `test_grayscale.py::TestRoiExtraction` |
| FR-4.3 | 扣暗电流基线，输出 Gnorm = GROI/Gbg×100 | `algorithm/grayscale.py:normalize_gray/DarkBaseline` | `test_grayscale.py::test_normalize_with_dark_baseline` |
| FR-4.4 | 输出逐帧 Gnorm 时间序列 CSV 与可选曲线图 | `storage/writer.py:GrayCsvWriter`、`algorithm/metrics.py` | `test_storage_config.py::TestCsvAppendWriter` |
| FR-4.5 | 灰卡读数二次线性校正（可选开关） | `algorithm/grayscale.py:apply_gcard_correction`、`config/schema.py:GCardConfig` | 人工 |
| FR-5.1 | 采样写入 CSV（追加式），字段含时间戳/通道/PM2.5/PM10/RH/T/Gnorm/标记位 | `storage/writer.py:SAMPLE_CSV_HEADER/CsvAppendWriter` | `test_storage_config.py::TestCsvAppendWriter`（含只追加、BOM、标记位） |
| FR-5.2 | 实验元数据录入 | `core/types.py:ExperimentMeta`、`storage/meta.py` | `test_storage_config.py::TestExperimentStore` |
| FR-5.3 | 历史数据按实验编号检索与回放（曲线 + 统计摘要） | `storage/reader.py:HistoryReader`、`algorithm/metrics.py` | `test_storage_config.py::TestHistoryReader` |
| FR-6.1 | 主界面 A/B 两栏显示浓度、RH、灰度与 η_A 预估值 | `ui/main_window.py`、`core/service.py:snapshot` | 人工 |
| FR-6.2 | 异常告警：互差 >10%、GROI 溢出、GROI/Gbg<12、RH 差 >5%、断线 | `core/quality.py`、`ui/alarm.py` | `test_efficiency.py::TestQualityCriteria` |
| FR-6.3 | 60 s 滚动曲线 | `storage/buffer.py:RollingBuffer`、`ui/realtime_chart.py` | `test_storage_config.py::TestRollingBuffer` |
| FR-7.1 | 标定向导：≥5 点，最小二乘 C = α·Gnorm + β | `ui/wizards.py:CalibrationWizard`、`algorithm/calibration.py:fit_from_pairs` | `test_calibration.py::TestFitFromPairs` |
| FR-7.2 | 输出 α、β、R²、残差与曲线图；R² 低于阈值告警 | `algorithm/calibration.py:CalibrationResult.passed` | `test_calibration.py::test_low_r2_triggers_alarm_state` |
| FR-7.3 | 分流比标定记录：3 点读数 → uA/uB 与判定 | `ui/wizards.py:SplitRatioWizard` | `test_flow_align.py::TestSplitRatio` |
| FR-7.4 | 压降标定记录：Δplung 与 0.5 Pa 比较并提示加稳定网 | `algorithm/flow.py:evaluate_plunge_dp` | `test_flow_align.py::TestPlungeDp` |
| FR-8.1 | 计算单程效率 η_A = 1 − CA,out / Cfeed | `algorithm/efficiency.py:eta_a` | `test_efficiency.py::TestEtaA` |
| FR-8.2 | 导出 η_A 时间序列与 η–累计处理量曲线数据 | `algorithm/efficiency.py:compute_efficiency/cumulative_volume` | `test_efficiency.py::TestCumulativeVolume` |
| FR-8.3 | 计算过程强制标注；不达标区间自动排除并说明 | `algorithm/efficiency.py:INVALIDATING_FLAGS/_FLAG_REASONS` | `test_efficiency.py::test_invalid_interval_is_excluded_with_reason` |
| FR-9.1 | 一键导出 DOCX 与 XLSX，含元数据/参数/标定/R²/η_A/不确定度声明 | `storage/report.py:export_docx/export_xlsx` | `test_storage_config.py::TestReportExport` |
| FR-9.2 | 导出原始 CSV 与灰度时间序列 CSV | `storage/report.py:export_csv_bundle` | 同上 |
| FR-10.1 | JSON 配置：串口号/波特率/传感器 ID/ROI/阈值/标定系数 | `config/schema.py`、`config/default.json` | `test_storage_config.py::TestConfig` |
| FR-10.2 | 启动自检：串口枚举、帧握手、视频源、配置合法性 | `core/selfcheck.py`、`ui/selfcheck_dialog.py` | 人工（`service.self_check()`） |

## 2. 非功能需求（NFR）

| 需求 | 类别 | 实现位置 | 验证 |
| --- | --- | --- | --- |
| NFR-1 性能 | 性能 | 1 Hz 调度（`core/scheduler.py`）；灰度逐帧（`device/video.py`）；CSV 缓冲落盘（`storage/writer.py`） | 人工压测 |
| NFR-2 可靠性 | 可靠性 | `ReconnectPolicy`（指数退避 ≤5 s）；坏帧丢弃计数；CSV 只追加可恢复 | `test_integration.py::TestReconnectPolicy`、`test_sds011.py::test_bad_checksum_counted_and_skipped` |
| NFR-3 可移植性 | 可移植性 | 核心层零 GUI 依赖；串口/I2C 封装在 `device/serial_port.py`、`device/i2c.py` | `grep -rn PySide6 daccs \| grep -v daccs/ui/` 无输出 |
| NFR-4 易用性 | 易用性 | `ui/theme.py`（字号 ≥12、中文字体）；`ui/wizards.py`（向导）；`ui/alarm.py`（颜色+文字） | 人工 |
| NFR-5 安全性 | 安全性 | 原始数据只追加；无任何网络调用；配置不含敏感字段 | `grep -rn "requests\|urllib\|socket" daccs/` 仅 `socket` 出现在注释性位置时需复核 |
| NFR-6 数据完整性 | 数据完整性 | 毫秒时间戳（`core/clock.py`）；对齐容差 ±0.5 s（`core/aligner.py`）；缓冲落盘 | `test_flow_align.py::TestAligner` |
| NFR-7 可维护性 | 可维护性 | 6 层分层；纯函数解析/算法均有单测 | 本文档 §2 依赖矩阵 + 80 个单元测试 |

## 3. 验收用例对照（SRS 第 10 章）

| 用例 | 验收判据 | 对应测试 | 状态 |
| --- | --- | --- | --- |
| TC-1 | 帧解析正确，校验错误帧被丢弃计数 | `tests/test_sds011.py` | ✅ 自动化覆盖 |
| TC-2 | RH 读数 ±2%RH，RH 差 >5% 触发告警 | `tests/test_efficiency.py`（差值判据） | ⚠️ 判据自动化，±2%RH 需实机 |
| TC-3 | Gnorm 序列与参考算法偏差 <1% | `tests/test_grayscale.py` | ⚠️ 公式自动化，偏差需实机比对 |
| TC-4 | 拟合输出 α/β/R²，R²<0.95 触发告警 | `tests/test_calibration.py` | ✅ 自动化覆盖 |
| TC-5 | η_A 计算正确，无效区间被排除并说明 | `tests/test_efficiency.py` | ✅ 自动化覆盖 |
| TC-6 | 导出 DOCX+XLSX+CSV 三件，内容可复核 | `tests/test_storage_config.py::TestReportExport` | ✅ 自动化覆盖 |
| TC-7 | 运行中拔插串口自动重连，数据无丢失 | — | ❌ 需实机验证（`ReconnectPolicy` 逻辑已单测） |
| TC-8 | 干净 Windows 虚拟机双击启动，免 Python 环境 | — | ❌ 需 Windows 打包环境验证 |

## 4. 里程碑映射（SRS 第 11 章）

| 里程碑 | 交付物 | 本仓库落点 | 状态 |
| --- | --- | --- | --- |
| M1 需求确认 | SRS + 评审记录 | `docs/TRACEABILITY.md`（本文档） | ✅ |
| M2 采集内核 | 串口/视频采集 + 解析 + 存储 | `device/`、`storage/`、`core/scheduler.py` | ✅ 框架完成，串口解析已单测 |
| M3 计算与界面 | 标定 + 效率 + 实时显示 | `algorithm/`、`ui/`、`core/service.py` | ✅ 计算层完成，界面为骨架 |
| M4 报告导出 | DOCX/XLSX/CSV | `storage/report.py` | ✅ 完成并单测 |
| M5 打包交付 | EXE/MSI + 驱动 + README | `packaging/app.spec`、`requirements.txt`、`README.md` | ⚠️ spec 已给，需 Windows 实机打包 |
