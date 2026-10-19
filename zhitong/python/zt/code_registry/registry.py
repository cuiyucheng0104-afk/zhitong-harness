# 来源：engine-service/app/engine/code_registry.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""GB50854 工程量清单编码受控码表 —— 查表模块。

设计要点（与本项目 D26 定律一致：能搬进确定性工具层的判断，就不要留给模型）：
  · 纯查表，零 LLM。490 条编码不能指望模型现场背下来。
  · 多版本：文件名约定 gb50854_<version>.yaml，新增省份/年份版本只加文件不改代码。
  · 全部结果带 chapter/chapter_name，供指标引擎直接输出中文章节名。

章节口径（WS08-06，issue #724）：
  · `normalize_code` 把单元格里的编码规范成一种可比较的形状（去空白、全角转半角、
    剥 Z 前缀、补回被 Excel 吃掉的前导 0、识别 xxBxxx 补充码）。
  · `classify_chapter` 是**唯一**的归章函数：costsheet 给每个 item 打章、指标按章汇总、
    投控取附录名，全走它 —— 此前三处各有一张手搓映射表，口径互不一致。
  · 章名依次查：版本码表（zj2025）→ 2013 章名表（gb_chapters_2013.yaml）→「章码 xxxx（章名表里没有）」
    （WS26-h2：原先兜底成「附录名·章码」，查不到的 0602 被说成「矿山工程」）。
    归章结果绝不裸写「其他」：安装 11 章里 10 章叫「其他」、占金额 99.79% 的那种结果，
    等于没归章（铁律 8）。
  · D53：编码版本只用 zj2025；2013 表只提供章名，不参与 lookup()。
"""
from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import yaml

_DATA_DIR = Path(__file__).resolve().parent / "data"
_FILE_PREFIX = "gb50854_"
_FILE_SUFFIX = ".yaml"
_CHAPTERS_2013 = _DATA_DIR / "gb_chapters_2013.yaml"

DEFAULT_VERSION = "zj2025"
UNKNOWN_CHAPTER_NAME = "其他"

# classify_chapter 的非国标兜底键。键与名都固定，前端/指标按键分组。
NO_CODE_KEY, NO_CODE_NAME = "00", "无编码项"
NON_GB_KEY, NON_GB_NAME = "NG", "非国标编号项"


def available_versions() -> list[str]:
    """扫描 data 目录，返回所有可用码表版本（按文件名约定推断）。"""
    out = []
    for p in _DATA_DIR.glob(f"{_FILE_PREFIX}*{_FILE_SUFFIX}"):
        out.append(p.name[len(_FILE_PREFIX):-len(_FILE_SUFFIX)])
    return sorted(out)


@functools.lru_cache(maxsize=8)
def _load_doc(version: str) -> dict:
    path = _DATA_DIR / f"{_FILE_PREFIX}{version}{_FILE_SUFFIX}"
    if not path.is_file():
        raise ValueError(
            f"未知码表版本 {version!r}；可用版本：{available_versions()}"
        )
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@functools.lru_cache(maxsize=1)
def _load_2013() -> dict:
    with _CHAPTERS_2013.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    # yaml 里键全部带引号，这里再 str() 一次：防有人手改漏了引号，0108 这类被读成别的类型
    return {
        "appendices": {str(k): v for k, v in (doc.get("appendices") or {}).items()},
        "chapters": {str(k): v for k, v in (doc.get("chapters") or {}).items()},
    }


def chapter_of(code: str) -> str:
    """取编码的 4 位章节码。浙江补充项带 Z 前缀，去掉后再取前 4 位。

    ⚠ 老接口，保留给 load_registry（码表里的键都是规范编码，没有补充码/丢 0 的问题）。
    解析真实单元格一律用 normalize_code / classify_chapter —— 本函数对「01B001」会给出
    伪章节「01B0」，对丢了前导 0 的 11 位编码会给出错位的章。
    """
    c = (code or "").strip()
    if c.startswith(("Z", "z")):
        c = c[1:]
    return c[:4]


@functools.lru_cache(maxsize=8)
def load_registry(version: str = DEFAULT_VERSION) -> dict[str, dict]:
    """返回 {code: {name, features_text, unit, chapter, chapter_name}}。"""
    doc = _load_doc(version)
    chapters = doc.get("chapters") or {}
    out: dict[str, dict] = {}
    for code, item in (doc.get("codes") or {}).items():
        ch = chapter_of(code)
        out[code] = {
            "name": item.get("name", ""),
            "features_text": item.get("features_text", ""),
            "unit": item.get("unit", ""),
            "chapter": ch,
            "chapter_name": chapters.get(ch, UNKNOWN_CHAPTER_NAME),
        }
    return out


def lookup(code: str, version: str = DEFAULT_VERSION) -> dict | None:
    """单码查询。未命中返回 None——调用方必须处理 None，不允许静默当成空字典。"""
    if not code:
        return None
    return load_registry(version).get(code.strip())


def _standard_chapter_name(chapter: str, version: str) -> tuple[Optional[str], Optional[str]]:
    """(章名, 来源)。来源 ∈ version / gb2013；两张表都没有 → (None, None)。"""
    ch = (chapter or "").strip()
    name = (_load_doc(version).get("chapters") or {}).get(ch)
    if name:
        return name, version
    name = _load_2013()["chapters"].get(ch)
    if name:
        return name, "gb2013"
    return None, None


def chapter_name(chapter: str, version: str = DEFAULT_VERSION) -> str:
    """章节码 → 中文名。先查版本码表，再查 2013 章名表；都没有才回「其他」。

    归章请用 classify_chapter（它对查不到的章给「章码 xxxx（章名表里没有）」，不会落「其他」）；
    本函数保留给只关心「这 4 位有没有标准章名」的老调用方（quantity_list）。
    """
    name, _src = _standard_chapter_name(chapter, version)
    return name or UNKNOWN_CHAPTER_NAME


def appendix_name(appendix: str, short: bool = False) -> Optional[str]:
    """附录码（01–09）→ 附录名。short=True 取去掉「工程」的简称（拼「××补充项目」用）。"""
    got = _load_2013()["appendices"].get((appendix or "").strip())
    if not got:
        return None
    return got.get("short" if short else "name")


# ---------------------------------------------------------------- 编码规范化

_Z_PREFIX = re.compile(r"^Z(?=\d)")
_SUPPLEMENT = re.compile(r"^(0[1-9])B\d{3,}$")
_HAS_LETTER = re.compile(r"[A-Z]")
_HAS_DIGIT = re.compile(r"\d")
_HAN = re.compile(r"[一-鿿]")

GB, SUPPLEMENT, NON_GB, NONE, SHORT = "gb", "supplement", "non_gb", "none", "short"


@dataclass(frozen=True)
class NormCode:
    raw: str
    kind: str                   # gb / supplement / non_gb / none / short
    code: str                   # 规范编码（不含 Z 前缀）；none 为空串
    z_prefix: bool = False      # 原编码带浙江补充 Z 前缀
    padded: bool = False        # 补过前导 0（11→12 位、8→9 位）
    appendix: Optional[str] = None   # 01–09；非国标为 None

    @property
    def is_item_code(self) -> bool:
        """够不够格当一条清单行的编码（行分类用）：国标、补充码、字母数字编号都算。"""
        return self.kind in (GB, SUPPLEMENT, NON_GB)

    @property
    def display(self) -> str:
        """带回 Z 前缀的规范编码，跨文件对齐用（Z 项与同号国标项是两条不同的清单）。"""
        return ("Z" if self.z_prefix else "") + self.code


def normalize_code(raw) -> NormCode:
    """单元格里的编码 → NormCode。

    - 去空白、全角转半角（NFKC）、字母转大写；
    - 剥 Z 前缀并记录；
    - 11 位纯数字补齐到 12 位、8 位补齐到 9 位（Excel 把数字格式的编码吃掉了前导 0，
      生产实例：40504001004 → 040504001004，原先被归进「其他」）；补齐后附录码必须落在
      01–09，否则不补、按原样判；
    - 9–12 位纯数字且附录码 01–09 → 国标编码；
    - xxBxxx → 补充码（附录码 + B + 流水号，如 01B047）；
    - 其余含字母且含数字、不含汉字的 → 非国标编号（如门窗 LC2020）；
    - 纯数字但不足 8 位（序号、4 位章码落在编码列）→ short，不当清单编码。
    """
    s = "" if raw is None else str(raw)
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", "", s).upper()
    if not s:
        return NormCode(raw="", kind=NONE, code="")
    if isinstance(raw, float) and s.endswith(".0"):
        s = s[:-2]      # 编码列被存成数字：40504001004.0
    z = False
    if _Z_PREFIX.match(s):
        z, s = True, s[1:]
    if s.isdigit():
        padded = False
        if len(s) in (8, 11) and "01" <= ("0" + s)[:2] <= "09":
            s, padded = "0" + s, True
        if 9 <= len(s) <= 12 and "01" <= s[:2] <= "09":
            return NormCode(raw=str(raw), kind=GB, code=s, z_prefix=z, padded=padded, appendix=s[:2])
        if len(s) < 8:
            return NormCode(raw=str(raw), kind=SHORT, code=s, z_prefix=z)
        return NormCode(raw=str(raw), kind=NON_GB, code=s, z_prefix=z)
    m = _SUPPLEMENT.match(s)
    if m:
        return NormCode(raw=str(raw), kind=SUPPLEMENT, code=s, z_prefix=z, appendix=m.group(1))
    if _HAN.search(s) or not (_HAS_LETTER.search(s) and _HAS_DIGIT.search(s)):
        return NormCode(raw=str(raw), kind=NONE, code="")
    return NormCode(raw=str(raw), kind=NON_GB, code=s, z_prefix=z)


# ---------------------------------------------------------------- 归章

# section（分部标题行文本）里的章码：「0104 砌筑工程」「S.1脚手架工程（编码：011701）」。
# 4 位或 6 位、以 0[1-9] 打头，前后不粘连数字 —— 防「2024年4月」里的 2024 被当章码。
_SECTION_CODE = re.compile(r"(?<!\d)(0[1-9]\d{2})(?:\d{2})?(?!\d)")


def section_chapter(section: Optional[str]) -> Optional[str]:
    if not section:
        return None
    m = _SECTION_CODE.search(unicodedata.normalize("NFKC", str(section)))
    return m.group(1) if m else None


@dataclass(frozen=True)
class ChapterRef:
    key: str                     # 章键：4 位章码 / 「01B」/「00」/「NG」
    name: str                    # 章名（绝不为「其他」）
    appendix: Optional[str]      # 附录码 01–09
    appendix_name: Optional[str]
    source: str                  # version 名 / gb2013 / appendix / supplement / no_code / non_gb

    @property
    def standard(self) -> bool:
        """章名来自标准表（版本码表或 2013 章名表）—— chapter_coverage 只数这一类。"""
        return self.source not in ("appendix", "supplement", "no_code", "non_gb")


def unlisted_chapter_name(chapter: str) -> str:
    """两张章名表都没有的章码 → 章名（WS26-h2，07-010 第 1 项）。"""
    return f"章码 {chapter}（章名表里没有）"


def _named(chapter: str, version: str) -> ChapterRef:
    app = chapter[:2]
    name, src = _standard_chapter_name(chapter, version)
    app_name = appendix_name(app)
    if name:
        return ChapterRef(chapter, name, app, app_name, src)
    # 查不到就写章码（铁律 3）：改前用「附录名·章码」兜底，0602 的预埋铁件显示成「矿山工程·0602」、
    # 0809 的电梯调试显示成「城市轨道交通工程·0809」—— 给了一个确定的专业名，而这一章根本不在表里。
    # 附录名仍在 appendix_name 字段里，不显示成章名。
    return ChapterRef(chapter, unlisted_chapter_name(chapter), app, app_name, "appendix")


def classify_chapter(code, section: Optional[str] = None, version: str = DEFAULT_VERSION) -> ChapterRef:
    """清单编码（+ 所在分部标题）→ ChapterRef。三个端点共用这一个函数（WS08-06）。

    | 编码类型 | 章键 | 章名 |
    | 国标编码 | 前 4 位 | 版本码表 → 2013 章名表 → 章码 xxxx（章名表里没有） |
    | 补充码，section 的章码同附录 | section 章码 | 该章名 |
    | 补充码，其他 | 附录码+B | 附录简称 + 补充项目 |
    | 无编码 | section 解析出的章码，解析不出为 00 | 相应章名 / 无编码项 |
    | 非国标编号 | NG | 非国标编号项 |
    """
    nc = code if isinstance(code, NormCode) else normalize_code(code)
    sec = section_chapter(section)
    if nc.kind == GB:
        return _named(nc.code[:4], version)
    if nc.kind == SUPPLEMENT:
        # 补充码的流水号不是章号：01B047 的「04」不代表砌筑（生产曾被拆进 0104）。
        # 只有它所在的分部标题给出同附录的章码时，才归那一章。
        if sec and sec[:2] == nc.appendix:
            return _named(sec, version)
        short = appendix_name(nc.appendix, short=True) or f"附录{nc.appendix}"
        return ChapterRef(f"{nc.appendix}B", f"{short}补充项目", nc.appendix,
                          appendix_name(nc.appendix), "supplement")
    if nc.kind == NON_GB:
        return ChapterRef(NON_GB_KEY, NON_GB_NAME, None, None, "non_gb")
    # 无编码 / short：看分部标题
    if sec:
        return _named(sec, version)
    return ChapterRef(NO_CODE_KEY, NO_CODE_NAME, None, None, "no_code")


def unique_chapter_labels(chapters: Iterable[dict], name_key: str = "chapter_name",
                          key_key: str = "chapter") -> None:
    """同一次结果里章名重名（市政 0401 与房建 0101 都叫「土石方工程」）时，
    给重名者的 label 追加「（章码）」；不重名的 label 就是章名。原地写 `label`。"""
    chapters = list(chapters)
    counts: dict[str, int] = {}
    for c in chapters:
        counts[c[name_key]] = counts.get(c[name_key], 0) + 1
    for c in chapters:
        n = c[name_key]
        c["label"] = f"{n}（{c[key_key]}）" if counts[n] > 1 else n


def chapter_coverage(items: Iterable[dict]) -> Optional[float]:
    """章名来自标准表的金额占比（按 |amount| 计）。无金额返回 None。

    item 需带 `chapter_source`（costsheet 输出）或 `code`+`section`（现算）。
    """
    total = std = 0.0
    for it in items:
        amt = it.get("amount")
        if not isinstance(amt, (int, float)) or not amt:
            continue
        src = it.get("chapter_source")
        if src is None:
            src = classify_chapter(it.get("code"), it.get("section")).source
        total += abs(amt)
        if src not in ("appendix", "supplement", "no_code", "non_gb"):
            std += abs(amt)
    return round(std / total, 4) if total else None
