"""界面层入口引导（GUI 启动）。

**本模块是 `daccs` 包中唯一 import PySide6 的地方**（连同 `daccs/ui/` 其余模块）。
装配根 :mod:`daccs.app` 只负责组装对象图并把服务交给本模块，
从而保证 "核心层零 GUI 依赖" 这条分层规则可以被静态检查严格验证：

    grep -rnE "^\\s*(import|from)\\s+PySide6" daccs --include="*.py" | grep -v "^daccs/ui/"
    # 期望输出为空
"""

from __future__ import annotations

import logging

__all__ = ["run"]

logger = logging.getLogger(__name__)


def run(service, argv: list[str] | None = None) -> int:
    """创建 QApplication 并进入事件循环。

    :param service: 应用服务门面
    :param argv: 命令行参数（默认取 ``sys.argv``）
    :return: 进程退出码
    """
    import sys  # noqa: PLC0415

    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    from .main_window import MainWindow  # noqa: PLC0415

    qt_app = QApplication(argv if argv is not None else sys.argv)
    qt_app.setApplicationName("数据采集与计算校准系统")
    qt_app.setApplicationVersion("0.1.0")

    window = MainWindow(service)
    window.show()
    try:
        return qt_app.exec()
    finally:
        service.close()
