"""应用装配根（Composition Root）。

这是 **唯一** 知道所有具体实现的地方：它按配置把 device / core /
algorithm / storage / config 各层组装成一个可运行的对象图，然后把
:class:`~daccs.core.service.ApplicationService` 交给界面。

好处：

* 各层实现可以自由替换（换数据库、换 GUI 框架），只要满足接口；
* 单元测试可以只装配需要的部分；
* 依赖关系集中在一处，架构文档与代码保持一致。

装配图::

    config ──> device drivers ──┐
                                 ▼
    config ──> AcquisitionScheduler ──> EventBus ──> ApplicationService
                                 │            ▲              │
                                 ▼            │              ├──> storage.writer
                            (sample.batch)   │              ├──> storage.reader
                                              │              └──> storage.meta
                              ui.BusBridge <──┘
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config.loader import load_config
from .config.schema import AppConfig, SensorConfig
from .core.events import EventBus
from .core.quality import Thresholds
from .core.scheduler import AcquisitionScheduler
from .core.service import ApplicationService
from .core.types import Channel
from .storage.meta import ExperimentStore
from .storage.reader import HistoryReader
from .storage.writer import CsvAppendWriter, GrayCsvWriter

__all__ = ["Application", "build_application"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Application:
    """装配结果。"""

    config: AppConfig
    bus: EventBus
    scheduler: AcquisitionScheduler
    service: ApplicationService
    writer: CsvAppendWriter
    gray_writer: GrayCsvWriter
    reader: HistoryReader
    meta_store: ExperimentStore


def build_drivers(config: AppConfig) -> list:
    """按配置实例化设备驱动（FR-1 / FR-2 / FR-3）。

    不可用的驱动会被跳过并记录日志，不影响其余驱动启动。
    """
    from .device.modbus_rs485 import ModbusDevice, ModbusDriver
    from .device.sds011 import SDS011Driver
    from .device.serial_port import PySerialTransport
    from .device.sht31 import SHT31Driver

    drivers: list = []
    for sensor in config.sensors:
        if not sensor.enabled:
            continue
        try:
            driver = _build_one(sensor, PySerialTransport, ModbusDevice, ModbusDriver, SHT31Driver, SDS011Driver)
        except Exception as exc:  # noqa: BLE001
            logger.warning("跳过无法配置的传感器 %s：%s", sensor.name, exc)
            continue
        if driver is not None:
            drivers.append(driver)
    return drivers


def _build_one(sensor: SensorConfig, *classes):
    py_serial, modbus_device_cls, modbus_driver_cls, sht31_cls, sds011_cls = classes

    if sensor.kind == "sds011":
        transport = py_serial(sensor.serial.port, sensor.serial.baudrate, sensor.serial.timeout)
        return sds011_cls(transport, Channel(sensor.channel))

    if sensor.kind == "sht31":
        address = int(sensor.address, 16) if sensor.address else 0x44
        transport = _build_i2c_transport()

        def read_fn(addr: int, _transport=transport, _address=address) -> bytes:
            _transport.write(_address, bytes((0x2C, 0x06)))
            return _transport.read(_address, 6)

        return sht31_cls(read_fn, Channel(sensor.channel), address)

    if sensor.kind == "rs485":
        transport = py_serial(sensor.serial.port, sensor.serial.baudrate, sensor.serial.timeout)
        device = modbus_device_cls(
            name=sensor.name,
            unit_id=sensor.unit_id,
            function_code=sensor.function_code,
            address=sensor.register,
            scale=sensor.scale,
            offset=sensor.offset,
            unit=sensor.quantity,
            kind="wind" if "wind" in sensor.quantity else ("dp" if "dp" in sensor.quantity else "raw"),
        )
        return modbus_driver_cls(transport, device, Channel(sensor.channel))

    logger.warning("未知传感器类型：%s", sensor.kind)
    return None


def _build_i2c_transport():
    """构造 I2C 传输对象；不可用时返回带错误提示的桩对象。"""
    from .device.i2c import SmbusTransport  # noqa: PLC0415

    try:
        import smbus2  # noqa: F401,PLC0415 - 探测可选依赖
    except ImportError:
        logger.warning("未安装 smbus2，SHT31 将无法采集（请在目标机安装）")

    return SmbusTransport()


def build_application(
    config: AppConfig | None = None,
    config_path: str | Path | None = None,
    expid: str = "",
) -> Application:
    """装配整个应用。

    :param config: 直接给定配置；``None`` 时从磁盘加载
    :param config_path: 配置文件路径
    :param expid: 当前实验编号（决定数据子目录）
    """
    config = config or load_config(config_path, strict=False)

    base = Path(config.storage.base_dir)
    raw_root = base / config.storage.raw_dir
    exp_dir = raw_root / expid if expid else raw_root
    exp_dir.mkdir(parents=True, exist_ok=True)

    bus = EventBus()
    thresholds = Thresholds(
        sensor_divergence_pct=config.thresholds.sensor_divergence_pct,
        rh_divergence_pct=config.thresholds.rh_divergence_pct,
        split_ratio=config.thresholds.split_ratio,
        groi_overflow=config.thresholds.groi_overflow,
        min_groi_gbg_ratio=config.thresholds.min_groi_gbg_ratio,
        r2_threshold=config.thresholds.r2_threshold,
        sds011_rh_limit=config.thresholds.sds011_rh_limit,
    )

    scheduler = AcquisitionScheduler(
        bus=bus,
        drivers=build_drivers(config),
        period_s=config.acquisition.period_s,
        thresholds=thresholds,
    )
    for driver in scheduler.drivers:
        driver.policy.initial = config.acquisition.reconnect_initial_s
        driver.policy.max_delay = config.acquisition.reconnect_max_s
        driver.policy.factor = config.acquisition.reconnect_factor

    writer = CsvAppendWriter(
        exp_dir / "samples.csv", flush_interval_s=config.storage.flush_interval_s
    )
    gray_writer = GrayCsvWriter(
        base / config.storage.gray_dir / "gray.csv",
        flush_interval_s=config.storage.flush_interval_s,
    )
    reader = HistoryReader(raw_root)
    meta_store = ExperimentStore(raw_root)

    service = ApplicationService(
        config=config,
        bus=bus,
        scheduler=scheduler,
        writer=writer,
        gray_writer=gray_writer,
        reader=reader,
        meta_store=meta_store,
    )
    logger.info("应用装配完成，实验编号=%s", expid or "(未指定)")
    return Application(
        config=config,
        bus=bus,
        scheduler=scheduler,
        service=service,
        writer=writer,
        gray_writer=gray_writer,
        reader=reader,
        meta_store=meta_store,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """GUI 入口（``python -m daccs``）。

    启动流程：装配 → 自检 → 交由界面层引导。

    注意：PySide6 的导入位于 :mod:`daccs.ui.entry`，
    本模块保持零 GUI 依赖，便于静态检查分层规则。
    """
    import sys  # noqa: PLC0415

    from .logging_setup import setup_logging  # noqa: PLC0415

    argv = list(argv if argv is not None else sys.argv[1:])
    config_path = argv[0] if argv else None

    setup_logging()
    application = build_application(config_path=config_path)

    report = application.service.self_check()
    logger.info(report.summary())
    for item in report.items:
        logger.info("  [%s] %s — %s", "通过" if item.passed else "未通过", item.name, item.detail)

    try:
        from .ui.entry import run  # noqa: PLC0415
    except ImportError as exc:
        logger.error("无法加载界面（缺少 PySide6？）：%s", exc)
        application.service.stop()
        return 2

    try:
        return run(application.service)
    finally:
        application.service.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
