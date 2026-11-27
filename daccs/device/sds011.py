"""SDS011 颗粒物传感器驱动（FR-1 / SRS 6.1）。

帧格式（8 字节，大端浓度）::

    0      1      2        3        4        5        6     7
    0xAA   0xC0   PM2.5_L  PM2.5_H  PM10_L   PM10_H   ID    checksum

* ``PM2.5 = (PM2.5_H << 8) | PM2.5_L``，单位 μg/m³
* ``PM10  = (PM10_H  << 8) | PM10_L``，单位 μg/m³
* ``checksum = sum(frame[0:6]) & 0xFF``（SRS 6.1 "sum of bytes 1..6" 为 1 基计法）
* 校验失败的帧 **丢弃并计数**（FR-1.2）

解析逻辑实现为纯函数 :func:`parse_frames`，不依赖串口，可离线单测。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..core.clock import now_ms
from ..core.types import Channel, SampleRecord
from .base import Driver, DriverError, SerialTransport

__all__ = [
    "FRAME_LEN",
    "FRAME_HEAD",
    "SDS011Frame",
    "parse_frame",
    "parse_frames",
    "SDS011Driver",
]

logger = logging.getLogger(__name__)

#: 帧长度（字节）
FRAME_LEN = 8

#: 帧头
FRAME_HEAD = (0xAA, 0xC0)


@dataclass(frozen=True, slots=True)
class SDS011Frame:
    """一帧有效的 SDS011 数据。"""

    pm25: float
    pm10: float
    device_id: int
    raw: bytes

    @property
    def checksum_ok(self) -> bool:
        """本帧校验是否通过（构造时已校验，恒为 True，保留以显式表达语义）。"""
        return True


def parse_frame(buf: bytes) -> SDS011Frame | None:
    """解析单个 8 字节帧；非法或校验失败返回 ``None``。

    :param buf: 长度至少 8 的字节串
    """
    if len(buf) < FRAME_LEN:
        return None
    if buf[0] != FRAME_HEAD[0] or buf[1] != FRAME_HEAD[1]:
        return None
    checksum = sum(buf[0:6]) & 0xFF
    if checksum != buf[7]:
        return None
    pm25 = (buf[3] << 8) | buf[2]
    pm10 = (buf[5] << 8) | buf[4]
    return SDS011Frame(pm25=float(pm25), pm10=float(pm10), device_id=buf[6], raw=bytes(buf[:FRAME_LEN]))


def parse_frames(
    buffer: bytes,
) -> tuple[list[SDS011Frame], int, int]:
    """从字节流中提取所有完整帧。

    :param buffer: 串口累积缓冲区
    :return: ``(有效帧列表, 消费的字节数, 校验错误帧数)``

    实现要点：先扫描帧头 ``0xAA 0xC0``，再取 8 字节校验；校验失败时
    跳过 1 字节继续寻找下一帧头，避免一帧坏数据导致后续全部错位。
    """
    frames: list[SDS011Frame] = []
    errors = 0
    i = 0
    n = len(buffer)
    while i + 1 < n:
        if buffer[i] == FRAME_HEAD[0] and buffer[i + 1] == FRAME_HEAD[1]:
            if i + FRAME_LEN > n:
                # 数据不足，保留等待下一批
                break
            chunk = buffer[i : i + FRAME_LEN]
            frame = parse_frame(chunk)
            if frame is not None:
                frames.append(frame)
                i += FRAME_LEN
                continue
            errors += 1
            i += 1
            continue
        i += 1
    return frames, i, errors


class SDS011Driver(Driver):
    """一路 SDS011 串口驱动。

    :param transport: 串口传输抽象（真实实现见 :mod:`daccs.device.serial_port`）
    :param channel: 该路对应的支路（A/B）
    """

    name = "sds011"

    def __init__(self, transport: SerialTransport, channel: Channel) -> None:
        super().__init__()
        self.transport = transport
        self.channel = channel
        self._buffer = bytearray()
        #: 校验错误帧累计计数（FR-1.2 / TC-1 验收判据）
        self.checksum_errors = 0
        #: 解析出的有效帧累计计数
        self.frame_count = 0

    def open(self) -> None:
        """打开串口（由外部注入 transport 的实现负责建立物理链路）。"""
        self._buffer.clear()
        self._connected = True
        logger.info("SDS011(%s) 已打开", self.channel.value)

    def read(self) -> list[SampleRecord]:
        """读取一次串口数据并转换为采样记录。

        串口无新数据时返回空列表（由调度器按 1 Hz 节奏驱动）。
        """
        if not self._connected:
            raise DriverError("SDS011 链路未打开")
        try:
            data = self.transport.read(512)
        except Exception as exc:  # noqa: BLE001 - 统一转成驱动异常
            self._connected = False
            raise DriverError(f"SDS011 读取失败: {exc}") from exc

        if not data:
            return []

        self._buffer.extend(data)
        frames, consumed, errors = parse_frames(bytes(self._buffer))
        if consumed:
            del self._buffer[:consumed]
        self.checksum_errors += errors
        self.frame_count += len(frames)
        if errors:
            logger.warning("SDS011(%s) 丢弃 %d 个校验错误帧，累计 %d",
                           self.channel.value, errors, self.checksum_errors)

        ts = now_ms()
        records: list[SampleRecord] = []
        for frame in frames:
            records.append(
                SampleRecord(
                    ts=ts,
                    ch=self.channel,
                    pm25=frame.pm25,
                    pm10=frame.pm10,
                )
            )
        return records

    def close(self) -> None:
        try:
            self.transport.close()
        except Exception:  # noqa: BLE001 - 关闭失败不阻断重连
            logger.debug("SDS011(%s) 关闭异常", self.channel.value, exc_info=True)
        finally:
            self._connected = False

    def status(self) -> dict[str, object]:
        """自检用状态（FR-10.2）。"""
        return {
            "channel": self.channel.value,
            "connected": self.connected,
            "frames": self.frame_count,
            "checksum_errors": self.checksum_errors,
            "pending_bytes": len(self._buffer),
        }
