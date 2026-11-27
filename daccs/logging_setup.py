"""日志初始化（SRS 9.2：logs/ 目录）。

日志策略：

* 同时输出到控制台与 ``logs/daccs.log``；
* 原始数据只追加不覆盖（安全），日志按日期轮转；
* 日志中不记录敏感信息（NFR-5：配置不含敏感信息）。
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

__all__ = ["setup_logging"]

_CONFIGURED = False


def setup_logging(log_dir: str | Path = "logs", level: int = logging.INFO) -> None:
    """初始化日志（重复调用只会生效一次）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.TimedRotatingFileHandler(
            directory / "daccs.log", when="midnight", backupCount=14, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        root.warning("日志目录不可写，仅使用控制台输出")

    _CONFIGURED = True
