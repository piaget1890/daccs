"""真实串口传输实现（pyserial）。

与 :mod:`daccs.device.base` 中的 ``SerialTransport`` 协议一致。
pyserial 是可选依赖：仅在真正打开物理串口时才导入，
保证无串口环境（如 CI、单元测试）可以 import 整个框架。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .base import DriverError, SerialTransport

__all__ = ["PySerialTransport", "list_serial_ports"]

logger = logging.getLogger(__name__)


class PySerialTransport:
    """基于 ``pyserial`` 的串口传输。

    :param port: 串口号，如 ``"COM3"`` / ``"/dev/ttyUSB0"``
    :param baudrate: 波特率，SDS011 为 9600（SRS 6.1）
    :param timeout: 读超时秒数
    """

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 0.2) -> None:
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: Any | None = None

    def open(self) -> None:
        try:
            import serial  # noqa: PLC0415 - 延迟导入可选依赖
        except ImportError as exc:  # pragma: no cover
            raise DriverError("未安装 pyserial，无法使用串口采集") from exc
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001
            raise DriverError(f"打开串口 {self.port} 失败: {exc}") from exc
        logger.info("串口已打开 %s @ %d", self.port, self.baudrate)

    def ensure_open(self) -> None:
        if self._serial is None:
            self.open()

    def read(self, size: int) -> bytes:
        self.ensure_open()
        try:
            waiting = self._serial.in_waiting
            return self._serial.read(size if waiting == 0 else min(size, waiting))
        except Exception as exc:  # noqa: BLE001
            raise DriverError(f"串口读取失败: {exc}") from exc

    def write(self, data: bytes) -> int:
        self.ensure_open()
        try:
            return int(self._serial.write(data))
        except Exception as exc:  # noqa: BLE001
            raise DriverError(f"串口写入失败: {exc}") from exc

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                logger.debug("串口关闭异常", exc_info=True)
        self._serial = None


def list_serial_ports() -> list[dict[str, str]]:
    """枚举可用串口（FR-10.2 启动自检）。"""
    try:
        from serial.tools import list_ports  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return []
    return [
        {"device": p.device, "description": p.description or "", "hwid": p.hwid or ""}
        for p in list_ports.comports()
    ]
