"""设备驱动层：把物理设备转换成 :mod:`daccs.core.types` 中的标准实体。

本层职责边界（对应 NFR-7 "设备层"）：

* **只做协议解析与原始量读取**，不做任何业务判断（告警、拟合、效率都在上层）；
* 每个驱动都把 "打开 / 读取 / 关闭" 与 "解析" 分离，解析函数是纯函数，
  可离线单测（NFR-7：单元测试覆盖解析与算法）；
* 断线重连策略统一由 :class:`ReconnectPolicy` 提供（FR-1.4）。

协议适配器一览：

======================  ==================================================
适配器                   协议
======================  ==================================================
:mod:`.sds011`          SDS011 UART 9600 8N1，8 字节帧（FR-1）
:mod:`.sht31`           SHT31 I2C 0x44/0x45，命令 0x2C 0x06（FR-2）
:mod:`.am2302`          AM2302 单总线（FR-2）
:mod:`.modbus_rs485`    Modbus RTU（FR-3，选配）
:mod:`.video`           MP4 文件 / UVC 相机（FR-4）
======================  ==================================================
"""

from __future__ import annotations

from .base import Driver, DriverError, ReconnectPolicy, SerialTransport

__all__ = ["Driver", "DriverError", "ReconnectPolicy", "SerialTransport"]
