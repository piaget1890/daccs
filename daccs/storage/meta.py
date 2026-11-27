"""实验元数据存储（FR-5.2）。

元数据以 JSON 文件保存，一个实验一个文件::

    data/raw/<expid>/meta.json

好处：

* 只追加不覆盖的原始数据目录里，元数据与采样文件天然同目录，导出报告时
  一并打包即可复现（SRS 9.2）；
* 崩溃后重启可直接从目录结构恢复实验上下文（NFR-2）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..core.types import ExperimentMeta

__all__ = ["ExperimentStore"]

logger = logging.getLogger(__name__)


class ExperimentStore:
    """实验元数据仓库。

    :param root: 数据根目录
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def dir_for(self, expid: str) -> Path:
        """返回某实验的目录路径。"""
        return self.root / expid

    def meta_path(self, expid: str) -> Path:
        """返回某实验元数据文件路径。"""
        return self.dir_for(expid) / "meta.json"

    def save(self, meta: ExperimentMeta) -> Path:
        """保存元数据。"""
        path = self.meta_path(meta.expid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("实验元数据已保存：%s", path)
        return path

    def load(self, expid: str) -> ExperimentMeta | None:
        """读取元数据；不存在返回 ``None``。"""
        path = self.meta_path(expid)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("实验元数据读取失败：%s", path)
            return None
        return ExperimentMeta.from_dict(data)

    def list_experiments(self) -> list[str]:
        """列出所有实验编号（按目录名排序）。"""
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def delete(self, expid: str) -> bool:
        """删除实验目录（仅在用户明确要求时调用）。"""
        import shutil

        target = self.dir_for(expid)
        if not target.exists():
            return False
        shutil.rmtree(target)
        logger.info("实验数据已删除：%s", target)
        return True
