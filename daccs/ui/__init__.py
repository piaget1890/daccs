"""界面层（PySide6）。

**唯一允许 import GUI 框架的层**（NFR-7 分层、NFR-3 可移植性）。

界面层与内核之间只通过两条通道交互：

1. **命令方向**：界面调用 :class:`daccs.core.service.ApplicationService`
   的方法完成业务操作；
2. **数据方向**：界面订阅 :class:`daccs.core.events.EventBus`，由
   :mod:`daccs.ui.workers` 把总线事件桥接成 Qt 信号，在 GUI 线程刷新控件。

本包 **不急切导入** 具体控件模块，因此没有安装 PySide6 的环境
（CI、单元测试、文档构建）依然可以 ``import daccs.ui``。

各模块：

======================  ====================================================
模块                     职责
======================  ====================================================
:mod:`.workers`          采集/视频线程与事件总线 → Qt 信号桥接
:mod:`.main_window`      主窗口，A/B 双栏（FR-6.1）
:mod:`.realtime_chart`   60 s 滚动曲线（FR-6.3）
:mod:`.alarm`            告警条，颜色 + 文字双提示（FR-6.2 / NFR-4）
:mod:`.wizards`          标定 / 分流比 / 压降向导（FR-7.1 ~ FR-7.4）
:mod:`.roi_selector`     ROI 选择对话框（FR-4.1）
:mod:`.selfcheck_dialog` 启动自检报告（FR-10.2）
:mod:`.theme`            字号、配色与告警色（FR-6.2 / NFR-4）
======================  ====================================================
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "workers",
    "main_window",
    "realtime_chart",
    "alarm",
    "wizards",
    "roi_selector",
    "selfcheck_dialog",
    "theme",
]


def __getattr__(name: str) -> Any:
    """惰性导入具体控件模块（避免无 PySide6 环境下 import 失败）。"""
    if name in __all__:
        import importlib

        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
