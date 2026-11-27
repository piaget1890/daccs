"""配置加载与保存（FR-10.1）。

查找顺序：

1. 显式传入的路径；
2. 环境变量 ``DACCS_CONFIG``；
3. 可执行文件同级 ``config/default.json``（打包后布局，SRS 9.2）；
4. 源码树同级 ``config/default.json``（开发态）；
5. 内置默认值（保证任何环境都能启动）。

**配置文件不含敏感信息**（NFR-5）：schema 中没有任何账号/密钥字段。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .schema import AppConfig, ConfigError, dump_json, validate

__all__ = [
    "load_config",
    "save_config",
    "default_config_path",
    "candidate_paths",
    "read_json",
]

logger = logging.getLogger(__name__)

#: 包内默认配置
BUNDLED_DEFAULT = Path(__file__).with_name("default.json")


def read_json(path: str | Path) -> dict[str, Any]:
    """读取 JSON 文件（UTF-8）。"""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件格式非法（应为 JSON 对象）：{path}")
    return data


def candidate_paths(explicit: str | Path | None = None) -> list[Path]:
    """列出配置查找路径（按优先级）。"""
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit))
    env = os.environ.get("DACCS_CONFIG")
    if env:
        paths.append(Path(env))

    exe_dir = Path(sys.executable).parent if getattr(__import__("sys"), "frozen", False) else Path.cwd()
    paths.append(exe_dir / "config" / "default.json")
    paths.append(BUNDLED_DEFAULT)
    paths.append(Path.cwd() / "config" / "default.json")
    return paths


def default_config_path() -> Path:
    """返回最终生效的配置文件路径（不保证存在）。"""
    for path in candidate_paths():
        if path.exists():
            return path
    return BUNDLED_DEFAULT


def load_config(path: str | Path | None = None, *, strict: bool = True) -> AppConfig:
    """加载配置。

    :param path: 显式配置路径
    :param strict: 为 ``True`` 时，配置非法直接抛 :class:`ConfigError`；
        为 ``False`` 时只记录警告并返回可用配置（自检场景）
    :raises ConfigError: 文件损坏或校验不通过
    """
    chosen: Path | None = None
    for candidate in candidate_paths(path):
        if candidate.exists():
            chosen = candidate
            break

    if chosen is None:
        logger.warning("未找到配置文件，使用内置默认配置")
        config = AppConfig.from_dict({})
    else:
        try:
            config = AppConfig.from_dict(read_json(chosen))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"配置文件读取失败：{chosen}（{exc}）") from exc
        logger.info("已加载配置文件：%s", chosen)

    problems = validate(config)
    if problems:
        message = "配置校验未通过：\n  - " + "\n  - ".join(problems)
        if strict:
            raise ConfigError(message)
        logger.warning(message)
    return config


def save_config(config: AppConfig, path: str | Path) -> Path:
    """保存配置到 JSON 文件。"""
    target = dump_json(config, path)
    logger.info("配置已保存：%s", target)
    return target
