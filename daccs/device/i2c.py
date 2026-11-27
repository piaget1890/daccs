"""I2C / 单总线传输实现（选配依赖）。

* :class:`SmbusTransport` —— 基于 ``smbus2`` 的 I2C 传输（SHT31）
* :class:`OneWireTransport` —— 基于 ``w1thermsensor`` / ``pyow`` 的单总线（AM2302）

两者都是 **可选依赖**，仅在真正访问硬件时导入；没有安装时驱动会给出
明确的提示，而不是静默失败。
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from .base import DriverError

__all__ = ["I2CTransport", "OneWireTransport", "SmbusTransport"]

logger = logging.getLogger(__name__)


@runtime_checkable
class I2CTransport(Protocol):
    """I2C 传输抽象。"""

    def write(self, addr: int, data: bytes) -> None:
        """写入寄存器/命令。"""

    def read(self, addr: int, length: int) -> bytes:
        """读取 ``length`` 字节。"""


@runtime_checkable
class OneWireTransport(Protocol):
    """单总线传输抽象。"""

    def read_frame(self) -> bytes:
        """读取一帧完整数据。"""


class SmbusTransport:
    """基于 ``smbus2`` 的 I2C 传输。

    :param bus_num: I2C 总线号（树莓派常见为 1）
    """

    def __init__(self, bus_num: int = 1) -> None:
        self.bus_num = bus_num
        self._bus = None

    def _ensure_open(self):
        if self._bus is None:
            try:
                from smbus2 import SMBus  # noqa: PLC0415 - 可选依赖
            except ImportError as exc:  # pragma: no cover
                raise DriverError("未安装 smbus2，无法使用 I2C 温湿度传感器") from exc
            self._bus = SMBus(self.bus_num)
        return self._bus

    def write(self, addr: int, data: bytes) -> None:
        bus = self._ensure_open()
        try:
            bus.write_i2c_block_data(addr, data[0], list(data[1:]))
        except Exception as exc:  # noqa: BLE001
            raise DriverError(f"I2C 写入失败：{exc}") from exc

    def read(self, addr: int, length: int) -> bytes:
        bus = self._ensure_open()
        try:
            return bytes(bus.read_i2c_block_data(addr, length))
        except Exception as exc:  # noqa: BLE001
            raise DriverError(f"I2C 读取失败：{exc}") from exc

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:  # noqa: BLE001
                logger.debug("I2C 关闭异常", exc_info=True)
            self._bus = None


class OneWireTransport:
    """单总线传输（AM2302）。

    :param device_path: 传感器设备路径，如 ``/sys/bus/w1/devices/28-xxxx/w1_slave``
    """

    def __init__(self, device_path: str) -> None:
        self.device_path = device_path

    def read_frame(self) -> bytes:
        try:
            import w1thermsensor  # noqa: PLC0415 - 可选依赖
        except ImportError as exc:  # pragma: no cover
            raise DriverError("未安装 w1thermsensor，无法使用 AM2302 单总线") from exc
        try:
            sensor = w1thermsensor.W1ThermSensor(
                w1thermsensor.W1ThermSensorType.SL28, self.device_path
            )
            if not sensor.is_valid:
                raise DriverError("AM2302 读数无效（CRC 校验失败）")
            return sensor.temperature_raw  # type: ignore[return-value]
        except DriverError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DriverError(f"AM2302 读取失败：{exc}") from exc
