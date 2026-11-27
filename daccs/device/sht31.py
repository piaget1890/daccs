"""温湿度传感器驱动（SHT31 I2C / AM2302 单总线）（FR-2 / SRS 6.2）。

* SHT31：I2C 地址 0x44（或 0x45），单次测量命令 ``0x2C 0x06``
* AM2302：单总线，1 Hz 采样

两者都提供 **纯解析函数** + 薄 I/O 包装，便于离线单测。
"""

from __future__ import annotations

import logging
import struct
from typing import Callable

from ..core.types import Channel, SampleRecord
from .base import Driver, DriverError

__all__ = [
    "SHT31_ADDR_A",
    "SHT31_ADDR_B",
    "SHT31_CMD_MEASURE_HOLDOUT",
    "parse_sht31_payload",
    "SHT31Driver",
    "parse_am2302_frame",
    "AM2302Driver",
]

logger = logging.getLogger(__name__)

#: SHT31 I2C 地址
SHT31_ADDR_A = 0x44
SHT31_ADDR_B = 0x45

#: SHT31 单次测量（clock stretching 关闭）命令
SHT31_CMD_MEASURE_HOLDOUT = bytes((0x2C, 0x06))

#: AM2302 帧结构：00 04 <humidity 16bit> <temp 16bit> <checksum 8bit>
_AM2302_HEAD = bytes((0x00, 0x04))


def parse_sht31_payload(payload: bytes) -> tuple[float, float]:
    """解析 SHT31 返回的 6 字节数据。

    格式：``status(1) | RH_msb | RH_lsb | T_msb | T_lsb | CRC(2)``

    :return: ``(rh_percent, temp_celsius)``
    :raises ValueError: 长度非法
    """
    if len(payload) < 6:
        raise ValueError("SHT31 响应长度非法")
    raw_rh = (payload[1] << 8) | payload[2]
    raw_t = (payload[3] << 8) | payload[4]
    rh = 100.0 * raw_rh / 65535.0
    temp = -45.0 + 175.0 * raw_t / 65535.0
    return rh, temp


def parse_am2302_frame(frame: bytes) -> tuple[float, float] | None:
    """解析 AM2302 单总线帧。

    :param frame: 完整帧（含 0x00 0x04 帧头与校验字节）
    :return: ``(rh_percent, temp_celsius)``；帧非法返回 ``None``
    """
    if len(frame) < 9 or frame[0:2] != _AM2302_HEAD:
        return None
    raw_h = (frame[2] << 8) | frame[3]
    raw_t = (frame[4] << 8) | frame[5]
    checksum = (frame[2] + frame[3] + frame[4] + frame[5]) & 0xFF
    if checksum != frame[8]:
        return None
    rh = raw_h / 10.0
    temp = raw_t / 10.0
    return rh, temp


class SHT31Driver(Driver):
    """SHT31 I2C 驱动。

    :param read_fn: 执行一次测量并返回 6 字节响应的可调用对象
    :param channel: 对应支路
    """

    name = "sht31"

    def __init__(self, read_fn: Callable[[int], bytes], channel: Channel, address: int = SHT31_ADDR_A) -> None:
        super().__init__()
        self.read_fn = read_fn
        self.channel = channel
        self.address = address

    def open(self) -> None:
        self._connected = True

    def read(self) -> list[SampleRecord]:
        from ..core.clock import now_ms

        if not self._connected:
            raise DriverError("SHT31 链路未打开")
        try:
            payload = self.read_fn(self.address)
        except Exception as exc:  # noqa: BLE001
            self._connected = False
            raise DriverError(f"SHT31 读取失败: {exc}") from exc
        rh, temp = parse_sht31_payload(payload)
        return [SampleRecord(ts=now_ms(), ch=self.channel, rh=rh, temp=temp)]

    def status(self) -> dict[str, object]:
        return {"channel": self.channel.value, "connected": self.connected, "address": hex(self.address)}


class AM2302Driver(Driver):
    """AM2302 单总线驱动。

    :param read_frame: 返回原始帧的可调用对象
    :param channel: 对应支路
    """

    name = "am2302"

    def __init__(self, read_frame: Callable[[], bytes], channel: Channel) -> None:
        super().__init__()
        self.read_frame = read_frame
        self.channel = channel

    def open(self) -> None:
        self._connected = True

    def read(self) -> list[SampleRecord]:
        from ..core.clock import now_ms

        if not self._connected:
            raise DriverError("AM2302 链路未打开")
        try:
            frame = self.read_frame()
        except Exception as exc:  # noqa: BLE001
            self._connected = False
            raise DriverError(f"AM2302 读取失败: {exc}") from exc
        parsed = parse_am2302_frame(frame)
        if parsed is None:
            logger.warning("AM2302(%s) 帧校验失败", self.channel.value)
            return []
        rh, temp = parsed
        return [SampleRecord(ts=now_ms(), ch=self.channel, rh=rh, temp=temp)]

    def status(self) -> dict[str, object]:
        return {"channel": self.channel.value, "connected": self.connected}
