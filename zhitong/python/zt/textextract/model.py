"""文本抽取的数据类：失败原因、逐页状态、统一抽取结果 :class:`DocText`。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/textextract.py（数据类部分）与
/home/user/zhitong-cost-ai/engine-service/app/provenance.py（C5 不变量）。
改动：只保留「文字层」与「旁车」两种正文来源，去掉 OCR 服务相关的来源、失败码与缓存标记；
``TextProvenance`` 的 pydantic 校验改成 :class:`DocText` 构造时的断言；扫描页没有旁车时记缺页，
失败码用 ``needs_vision``（让 agent 用 ``read_image`` 看图）。

不变量（构造时断言，违约抛 ``ValueError``）：

- 正文为空 ⇔ ``failure`` 非空；
- 「空串 + text_layer」禁止（失败了就不要声称来自文字层）。

给消费端的规则：``text_source != "text_layer"`` 或 ``complete is False`` 时，结果里的金额与数量
必须标 ``needs_manual``（信封本身恒带 ``needs_manual: true``）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

# 正文来源：文字层 / 旁车 / 试过没取到。旧系统的 ocr_service 在本仓不存在。
TextSource = Literal["text_layer", "ocr_sidecar", "none"]
PageSource = Literal["text_layer", "ocr_sidecar", "blank", "missing"]
PageStatusKind = Literal["usable", "blank", "scanned"]

_DETAIL_MAX = 200


@dataclass(frozen=True)
class ExtractFailure:
    """抽不出正文的原因。code 是机器码（小写 snake_case），detail 给人看。

    =================  ==========================================================
    code               含义
    =================  ==========================================================
    unsupported_format 不支持的格式（附扩展名）
    convert_failed     soffice 转换失败（未安装 / 超时 / 返回码）
    parse_failed       解析异常（附异常类型与消息前 200 字）
    encrypted          文件加密
    undecodable        文本解码不出来
    empty_file         0 字节
    derived_artifact   系统生成物（INDEX.md）
    no_text            解析成功但一个字都没有
    needs_vision       扫描页 / 扫描件，文字层与旁车都没有正文：用 ``read_image`` 看图
    =================  ==========================================================
    """

    code: str
    detail: str
    retryable: bool = False


@dataclass
class PdfPage:
    """pypdf 逐页原料：文字层文本 + 判扫描件用的两个旁证。"""

    no: int
    text: str
    has_image: bool
    content_len: int
    error: Optional[str] = None
    flags: tuple[str, ...] = ()  # 抽取方式标记（layout_table 等）


@dataclass(frozen=True)
class PageStatus:
    """一页文字层的判定结果。"""

    status: PageStatusKind
    flags: tuple[str, ...] = ()
    text: str = ""  # 解 /uniXXXX、去扫描水印之后的文字层


@dataclass
class PageInfo:
    """一页最终取得的正文及来源；``missing`` 页带 ``missing_reason``。"""

    no: int
    source: PageSource
    text: str = ""
    flags: list[str] = field(default_factory=list)
    missing_reason: Optional[str] = None


@dataclass
class DocText:
    """一份文件的正文 + 来源 + 缺页 / 截断 / 失败原因。"""

    text: str
    text_source: TextSource
    pages: list[PageInfo] = field(default_factory=list)
    pages_total: Optional[int] = None
    truncated: bool = False
    quality_flags: list[str] = field(default_factory=list)
    quality_suspect: bool = False
    failure: Optional[ExtractFailure] = None
    hidden_sheets: list[str] = field(default_factory=list)
    ocr_derived: bool = False
    # 旁车与 PDF 页数对不上、整份采用旁车时为 False：页级明细不可信，complete 恒 False
    page_mapped: bool = True

    def __post_init__(self) -> None:
        blank = not self.text.strip()
        if blank:
            if self.text_source == "text_layer":
                raise ValueError("正文为空却标 text_source=text_layer（禁止的组合）")
            if self.failure is None:
                raise ValueError(f"正文为空却没有 failure（text_source={self.text_source}）")
        elif self.failure is not None:
            raise ValueError(f"正文非空却带 failure={self.failure.code}")
        if self.text_source == "none" and self.failure is None:
            raise ValueError("text_source=none（试过、没取到）必须带 failure 说明原因")

    # —— 页级明细 ——
    def _pages_of(self, source: str) -> list[int]:
        return [p.no for p in self.pages if p.source == source]

    @property
    def pages_text_layer(self) -> list[int]:
        """取自文字层的页号。"""
        return self._pages_of("text_layer")

    @property
    def pages_sidecar(self) -> list[int]:
        """取自旁车的页号。"""
        return self._pages_of("ocr_sidecar")

    @property
    def pages_blank(self) -> list[int]:
        """判为真空白页的页号。"""
        return self._pages_of("blank")

    @property
    def pages_missing(self) -> list[int]:
        """没有取得正文的页号（扫描页且无可用旁车）。"""
        return self._pages_of("missing")

    @property
    def pages_ok(self) -> list[int]:
        """取得正文的页号（文字层 + 旁车）。"""
        return sorted(self.pages_text_layer + self.pages_sidecar)

    @property
    def complete(self) -> bool:
        """没有失败、没有截断、没有缺页、页级明细可信。"""
        return (
            self.failure is None
            and not self.truncated
            and not self.pages_missing
            and self.page_mapped
        )

    @property
    def text_source_detail(self) -> str:
        """``text_layer`` / ``ocr_sidecar`` / ``mixed`` / ``none``。"""
        kinds = {p.source for p in self.pages} & {"text_layer", "ocr_sidecar"}
        if len(kinds) > 1:
            return "mixed"
        if len(kinds) == 1:
            return next(iter(kinds))
        return self.text_source

    def provenance(self) -> dict[str, Any]:
        """正文来源摘要（JSON 兼容），放进信封 ``data``。

        :returns: 键集合固定的字典。
        """
        return {
            "text_source": self.text_source,
            "text_source_detail": self.text_source_detail,
            "pages_total": self.pages_total,
            "pages_ok": self.pages_ok,
            "pages_missing": self.pages_missing,
            "pages_text_layer": self.pages_text_layer,
            "pages_sidecar": self.pages_sidecar,
            "pages_blank": self.pages_blank,
            "truncated": self.truncated,
            "complete": self.complete,
            "quality_suspect": self.quality_suspect,
            "quality_flags": list(self.quality_flags),
            "failure_code": self.failure.code if self.failure else None,
            "failure_detail": self.failure.detail if self.failure else None,
            "hidden_sheets": list(self.hidden_sheets),
            "ocr_derived": self.ocr_derived,
        }


def failed_doc(code: str, detail: str, *, retryable: bool = False, **kw: Any) -> DocText:
    """构造「没取到正文」的 :class:`DocText`。

    :param code: :class:`ExtractFailure` 的机器码。
    :param detail: 给人看的说明，超过 400 字截断。
    :param retryable: 重试是否可能成功。
    :param kw: 透传给 :class:`DocText` 的其它字段（pages、quality_flags 等）。
    :returns: ``text=""``、``text_source="none"`` 的结果。
    """
    return DocText(text="", text_source="none",
                   failure=ExtractFailure(code, detail[:_DETAIL_MAX * 2], retryable), **kw)


def exc_detail(e: BaseException) -> str:
    """异常的一行说明：类型名 + 消息前 200 字。

    :param e: 异常对象。
    :returns: ``"TypeName: message"``。
    """
    return f"{type(e).__name__}: {str(e)[:_DETAIL_MAX]}"
