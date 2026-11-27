# 数据采集与计算校准系统（daccs）

双通道演示装置 V3.2 的测量与计算中枢：把 **A/B 两支路的浓度、温湿度、灰度** 三条数据流
对齐到统一时间轴，完成标定与效率计算，输出可复核的数据文件与报告。

> 依据《数据采集与计算校准系统 软件需求说明书（SRS）》V3.2-SRS-001 实现。
> 本仓库交付 **软件基本框架 + 可运行的核心算法层**，界面层为 PySide6 骨架。

---

## 快速开始

```bash
# Python 3.11（见 SRS §8.2）
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 跑测试（80 个单元测试，无需额外测试框架）
python -m unittest discover -s tests -t . -v

# 一次性跑：单元测试 + 分层依赖检查
bash scripts/run_checks.sh

# 启动界面（需要 PySide6；采集需要真实硬件）
python -m daccs
```

## 框架一览

```
daccs/
├── app.py          装配根（唯一知道所有具体实现的地方）
├── core/           核心层：调度、事件总线、时间对齐、质量判据、应用服务门面
├── device/         设备层：SDS011 / SHT31 / AM2302 / Modbus RTU / 视频
├── algorithm/      算法层：灰度归一化、标定拟合、η_A、分流比、统计（纯函数）
├── storage/        存储层：CSV 只追加写、历史检索、实验元数据、报告导出
├── ui/             界面层：PySide6（唯一依赖 GUI 框架的层）
└── config/         配置层：JSON 配置模型、校验与加载
```

**详细架构、依赖矩阵、模块间相互作用时序图、线程模型见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。**
**需求到代码的追溯关系见 [`docs/TRACEABILITY.md`](docs/TRACEABILITY.md)。**

### 分层依赖规则

```
ui ──▶ core ──▶ device / algorithm / config
                └▶ storage（经事件总线间接接入）
```

- 核心层 **不 import PySide6**，界面层 **不直接 import 算法/存储实现**；
- 界面只调用 `core.service.ApplicationService` 这一个门面；
- 跨模块数据流统一走 `core.events.EventBus`，模块之间不互相直接调用。

## 核心能力（已实现并有单测）

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| SDS011 帧解析 | `device/sds011.py` | 8 字节帧、0xAA 0xC0 对齐、校验和、坏帧丢弃计数 |
| 温湿度解析 | `device/sht31.py` | SHT31 I2C 0x44/0x45、AM2302 单总线 |
| Modbus RTU | `device/modbus_rs485.py` | 0x03/0x04、CRC16、量程换算 |
| 灰度归一化 | `algorithm/grayscale.py` | GROI / Gbg / Gnorm、暗电流基线、gt、灰卡校正 |
| 标定拟合 | `algorithm/calibration.py` | 最小二乘 `C = α·Gnorm + β`，输出 α/β/R²/残差 |
| 效率计算 | `algorithm/efficiency.py` | `η_A = 1 − CA,out/Cfeed`，无效区间自动排除并说明 |
| 分流比 / 压降 | `algorithm/flow.py` | uA/uB ≤ 1.05、Δplung < 0.5 Pa |
| 数据质量判据 | `core/quality.py` | 互差 >10%、RH 差 >5%、GROI 溢出、GROI/Gbg<12、分流比 |
| 时间轴对齐 | `core/aligner.py` | 最近邻，容差 ±0.5 s |
| 断线重连 | `device/base.py` | 指数退避，最长 5 s |
| 只追加存储 | `storage/writer.py` | UTF-8 BOM、缓冲落盘、绝不覆盖原始数据 |
| 报告导出 | `storage/report.py` | DOCX + XLSX + CSV 三件套，强制附不确定度声明 |

## 配置

`daccs/config/default.json`（UTF-8 JSON）：

```jsonc
{
  "sensors": [ { "kind": "sds011", "channel": "A", "serial": { "port": "COM3", "baudrate": 9600 } } ],
  "video":    { "target": "", "is_camera": false, "fps": 30.0 },
  "roi":      { "x": 0, "y": 0, "w": 0, "h": 0, "expand_factor": 2.0 },
  "thresholds": { "sensor_divergence_pct": 10.0, "rh_divergence_pct": 5.0, "split_ratio": 1.05 },
  "calibration": { "alpha": 0.0, "beta": 0.0, "r2": 0.0, "threshold": 0.95 },
  "acquisition": { "period_s": 1.0, "cfeed": 0.0 }
}
```

查找顺序：命令行参数 → 环境变量 `DACCS_CONFIG` → 可执行文件同级 `config/default.json` → 包内默认。

## 打包（SRS §9）

```bash
pip install pyinstaller
pyinstaller packaging/app.spec --noconfirm
```

产物：`dist/app/app.exe`（`--onefile`）。安装包建议用 Inno Setup 封装，并随包附带
CH340 驱动（`drivers/CH341SER.EXE`）。详见 `packaging/app.spec` 与 SRS §9。

## 已知边界

- 界面层为骨架：控件与信号已按 FR-6/FR-7 搭好，但未在真实硬件上做过联调；
- SHT31 / AM2302 依赖 `smbus2` / `w1thermsensor`，需在目标机安装；
- TC-7（拔插串口）、TC-8（干净 Windows 虚拟机）需要实机验证；
- `.github/workflows/ci.yml` 因 GitHub App 权限范围限制未能写入仓库，
  等价检查已以 `scripts/check_layering.sh` 提供，可自行接入 CI。

## 许可

内部项目，版权归项目方所有。
