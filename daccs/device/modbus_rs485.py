"""RS485 / Modbus RTU 变送器驱动（FR-3，选配 / SRS 6.3）。

* 物理层：RS485 转 USB（CH340 / CP2102）
* 协议：Modbus RTU，9600 / 19200 baud，8N1，功能码 0x03 / 0x04
* 寄存器地址与量程由变送器手册在配置中给出

本模块提供：

* :func:`build_read_request` —— 构造 0x03/0x04 请求帧（含 CRC16）；
* :func:`parse_response` —— 解析响应帧并做 CRC 校验；
* :class:`ModbusDriver` —— 薄封装，输出标准 :class:`SampleRecord`（风速/压降写入 ``extra`` 字段）。
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import Callable

from ..core.clock import now_ms
from ..core.types import Channel, SampleRecord
from .base import Driver, DriverError, SerialTransport

__all__ = [
    "ModbusDevice",
    "build_read_request",
    "crc16_modbus",
    "parse_response",
    "ModbusDriver",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModbusDevice:
    """一台 Modbus 从站的配置。

    :param kind: 物理量类型，决定写入 :class:`SampleRecord` 的哪个字段：
        ``"wind"`` → ``wind_speed_ms``；``"dp"`` → ``dp_pa``；``"raw"`` → 只读不写。
    """

    name: str
    unit_id: int
    function_code: int = 0x03
    address: int = 0
    count: int = 1
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    kind: str = "raw"

    def value_from_register(self, raw: int) -> float:
        """寄存器原始值转工程量。"""
        return raw * self.scale + self.offset


def crc16_modbus(data: bytes) -> int:
    """Modbus RTU CRC16（多项式 0xA001，初值 0xFFFF）。"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def build_read_request(device: ModbusDevice) -> bytes:
    """构造 0x03/0x04 读寄存器请求帧。"""
    body = struct.pack(
        ">BHH", device.unit_id, device.function_code, device.address, device.count
    )
    return body + struct.pack("<H", crc16_modbus(body))


def parse_response(payload: bytes, device: ModbusDevice) -> float:
    """解析响应并返回工程量。

    :param payload: 完整响应帧
    :param device: 从站配置（用于换算量程）
    :raises DriverError: 帧长非法、CRC 不符或异常码
    """
    if len(payload) < 5:
        raise DriverError("Modbus 响应长度非法")
    if len(payload) >= 3 and payload[1] & 0x80:
        raise DriverError(f"Modbus 异常码 0x{payload[2]:02X}")
    expected = struct.unpack("<H", payload[-2:])[0]
    if crc16_modbus(payload[:-2]) != expected:
        raise DriverError("Modbus CRC 校验失败")
    byte_count = payload[2]
    registers = struct.unpack(f">{byte_count // 2}H", payload[3 : 3 + byte_count])
    raw = registers[0] if registers else 0
    return device.value_from_register(raw)


class ModbusDriver(Driver):
    """RS485 变送器驱动（风速 / 微差压）。

    :param transport: 串口传输抽象
    :param device: 从站配置
    :param channel: 归属支路
    """

    name = "modbus_rs485"

    def __init__(
        self,
        transport: SerialTransport,
        device: ModbusDevice,
        channel: Channel | None = None,
        read_exact: Callable[[SerialTransport, int, float], bytes] | None = None,
    ) -> None:
        super().__init__()
        self.transport = transport
        self.device = device
        self.channel = channel
        self._read_exact = read_exact

    def open(self) -> None:
        self._connected = True

    def read(self) -> list[SampleRecord]:
        if not self._connected:
            raise DriverError("Modbus 链路未打开")
        request = build_read_request(self.device)
        try:
            self.transport.write(request)
            if self._read_exact is not None:
                payload = self._read_exact(self.transport, 5 + 2 * self.device.count, 0.5)
            else:
                payload = self.transport.read(64)
        except Exception as exc:  # noqa: BLE001
            self._connected = False
            raise DriverError(f"Modbus 读取失败: {exc}") from exc
        if not payload:
            return []
        value = parse_response(payload, self.device)
        kwargs: dict[str, float] = {}
        if self.device.kind == "wind":
            kwargs["wind_speed_ms"] = value
        elif self.device.kind == "dp":
            kwargs["dp_pa"] = value
        return [SampleRecord(ts=now_ms(), ch=self.channel or Channel.A, **kwargs)]

    def status(self) -> dict[str, object]:
        return {
            "device": self.device.name,
            "connected": self.connected,
            "unit": self.device.unit,
        }
