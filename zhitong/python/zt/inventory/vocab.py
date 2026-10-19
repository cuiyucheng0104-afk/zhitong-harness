"""分类器类目 → 清单口径类目的折算。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/category_vocab.py（``canonical`` / ``is_audited``）
与 data/doc_category_map.yaml。改动：映射表由调用方加载后传入，不在导入时读文件；
词表枚举（``vocabulary`` / ``llm_closed_set``）只服务 LLM 兜底，不迁移。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from zt.inventory.data import read_yaml


@dataclass(frozen=True)
class Vocab:
    """类目折算表。

    :ivar mapping: 分类器类目 → 清单口径类目；不在表里的类目原样返回。
    :ivar not_audited: 不参与核查的类目及理由。
    """

    mapping: dict[str, str] = field(default_factory=dict)
    not_audited: dict[str, str] = field(default_factory=dict)

    def canonical(self, cat: Optional[str]) -> Optional[str]:
        """把分类器类目折算成清单口径类目；None / 空串原样返回。

        :param cat: 分类器类目。
        :returns: 清单口径类目。
        """
        if not cat:
            return cat
        return self.mapping.get(cat, cat)

    def is_audited(self, cat: Optional[str]) -> bool:
        """类目是否参与核查。

        :param cat: 分类器类目。
        :returns: 非空且未登记在 ``not_audited`` 时为 True。
        """
        return bool(cat) and cat not in self.not_audited


def load_vocab(path: Path) -> Vocab:
    """加载 doc_category_map.yaml。

    :param path: 文件路径。
    :returns: 折算表。
    """
    raw = read_yaml(path)
    return Vocab(
        mapping={str(k): str(v) for k, v in (raw.get("map") or {}).items()},
        not_audited={str(k): str(v) for k, v in (raw.get("not_audited") or {}).items()},
    )
