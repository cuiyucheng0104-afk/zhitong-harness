"""迁移自旧仓 engine-service/tests/test_audit_check_stage_flag.py。

「阶段未校验」按文件判（WS23-n，issue #966，06-013 第 4 点，AR-53）。

改前 `degraded` 是清单项级的布尔：命中文件里**任一份**缺阶段就整项挂「阶段未校验」，
不看别的命中文件是否已经校验过。AR-53 的真实形状：清单项「施工图纸」（施工过程），
`弱电设计及施工图说明.docx` 已被人工改标为「施工过程」，`人防电气施工设计说明.docx` 没有阶段 ——
改前整项 `category_only`、`degraded_matches=1`，驾驶舱也跟着写「1 项命中未经阶段校验」。

现在：
  - 每个命中文件各自带 `stage_checked`：两侧都有阶段且一致 → True；只有一侧有阶段（校验被跳过）
    → False；两侧都没有阶段（无从校验）→ None。
  - 清单项的 `matched_by`：撑起这一项结论的命中里（已备项只看 confirmed / strong，待确认项看全部），
    有一份不是「校验被跳过」就是 `stage_and_category`，全都被跳过才是 `category_only`。

夹具刻意覆盖四种组合（有阶段 + 没阶段、只有没阶段、有阶段但不一致、只有弱证据），
外加两条「名字说的性质，夹具够不够得到」的反例：
  - 已备项里只有**弱证据**的那份校验过阶段 —— 它撑不起「已备」，不许把整项洗成已校验；
  - 两侧都没有阶段的旧行为（不算降级）不许被顺手收紧。
"""

from tests.inventory._support import check_checklist_graded

ITEM = {"item_id": "42009", "item_name": "施工图纸", "doc_category": "施工图",
        "stage_code": "施工过程", "requirement_level": "required"}


def _file(fid, stage=None, *, evidence="filename_rule", source="rule", confirm="unconfirmed", name=None):
    d = {"file_id": fid, "file_name": name or f"{fid}.docx", "doc_category": "施工图",
         "evidence": evidence, "source": source, "confirm_state": confirm}
    if stage is not None:
        d["cost_stage"] = stage
    return d


def _manual(fid, stage, name=None):
    return _file(fid, stage, evidence="manual", source="manual", confirm="confirmed", name=name)


def _weak(fid, stage=None):
    return _file(fid, stage, evidence="dir_inference", source="rule")


def _row(g, bucket="covered"):
    rows = g[bucket]
    assert len(rows) == 1, f"{bucket} 应恰好一项，实际 {rows}"
    return rows[0]


def _flags(row):
    return {f["file_id"]: f.get("stage_checked") for f in row["matched_files"]}


# ── 规格点名的四种组合 ────────────────────────────────────────────────────

def test_有阶段的人工确认件与没阶段的强证据件同在_整项算已校验():
    """AR-53 的形状：A 人工给了「施工过程」，B 没有阶段。改前整项 category_only。"""
    g = check_checklist_graded([_manual("A", "施工过程"), _file("B")], [ITEM])
    row = _row(g)
    assert row["matched_by"] == "stage_and_category"
    assert g["degraded_matches"] == 0, "有一份撑得起结论的命中校验过阶段，不该计降级"
    assert _flags(row) == {"A": True, "B": False}, "没校验的那一份要单独标出来（界面上写「未校验阶段」）"


def test_只有没阶段的那份_仍然挂降级():
    g = check_checklist_graded([_file("B")], [ITEM])
    row = _row(g)
    assert row["matched_by"] == "category_only"
    assert g["degraded_matches"] == 1
    assert _flags(row) == {"B": False}


def test_有阶段但不一致的那份不命中_现有行为不变():
    g = check_checklist_graded([_manual("A", "结算"), _file("B")], [ITEM])
    row = _row(g)
    assert set(_flags(row)) == {"B"}, "阶段不一致的文件不是命中"
    assert row["matched_by"] == "category_only"
    assert g["degraded_matches"] == 1


def test_待确认项看全部命中_其中一份阶段一致就算已校验():
    g = check_checklist_graded([_weak("W1", "施工过程"), _weak("W2")], [ITEM])
    row = _row(g, "pending")
    assert row["best_grade"] == "weak"
    assert row["matched_by"] == "stage_and_category"
    assert g["degraded_matches"] == 0
    assert _flags(row) == {"W1": True, "W2": False}


def test_待确认项全都没阶段_挂降级():
    g = check_checklist_graded([_weak("W1"), _weak("W2")], [ITEM])
    row = _row(g, "pending")
    assert row["matched_by"] == "category_only"
    assert g["degraded_matches"] == 1


# ── 夹具够不够得到：只看「撑得起结论」的命中 ─────────────────────────────

def test_已备项里只有弱证据那份校验过阶段_不许把整项洗成已校验():
    """已备是 confirmed / strong 撑起来的；弱证据不进分子，它校验过阶段不代表已备那份校验过。

    「任一命中校验过就算」的实现在这条上会判成 stage_and_category —— 这条就是为抓它写的。
    """
    g = check_checklist_graded([_file("S"), _weak("W", "施工过程")], [ITEM])
    row = _row(g)
    assert row["best_grade"] == "strong"
    assert row["matched_by"] == "category_only"
    assert g["degraded_matches"] == 1
    assert _flags(row) == {"S": False, "W": True}


# ── 不许顺手收紧的旧行为 ─────────────────────────────────────────────────

def test_两侧都没有阶段_无从校验_不算降级也不标小字():
    item = {**ITEM, "stage_code": None}
    g = check_checklist_graded([_file("B")], [item])
    row = _row(g)
    assert row["matched_by"] == "stage_and_category"
    assert g["degraded_matches"] == 0
    assert _flags(row) == {"B": None}, "None = 无从校验，界面不写「未校验阶段」"


def test_清单项没阶段而文件有阶段_仍是校验被跳过():
    item = {**ITEM, "stage_code": None}
    g = check_checklist_graded([_file("B", "施工过程")], [item])
    row = _row(g)
    assert row["matched_by"] == "category_only"
    assert g["degraded_matches"] == 1
    assert _flags(row) == {"B": False}


# ── AR-53 原样（生产 audit_check_result 2105747863520759808 的「施工图纸」一项）──

def test_AR53_施工图纸_人工改了阶段的两份撑起结论后不再挂阶段未校验():
    files = [
        _manual("weak-elec", "施工过程", name="弱电设计及施工图说明.docx"),
        _manual("struct-2", "施工过程", name="结构说明2.xls"),
        _manual("struct-4", None, name="结构说明4.xls"),
        _file("civil-def", name="人防电气施工设计说明.docx"),
        *[_weak(f"struct-{i}") for i in (1, 5, 6, 7, 8, 9)],
    ]
    g = check_checklist_graded(files, [ITEM])
    row = _row(g)
    assert row["matched_by"] == "stage_and_category"
    assert g["degraded_matches"] == 0
    flags = _flags(row)
    assert flags["weak-elec"] is True and flags["struct-2"] is True
    assert flags["civil-def"] is False, "人防电气说明没有阶段：只在它旁边写「未校验阶段」"
    assert flags["struct-4"] is False


def test_降级计数按项累加_互不串():
    items = [ITEM, {**ITEM, "item_id": "42010", "item_name": "图纸会审记录", "doc_category": "图纸会审"}]
    files = [_manual("A", "施工过程"), _file("B"),
             {**_file("C"), "doc_category": "图纸会审"}]
    g = check_checklist_graded(files, items)
    by = {r["item_id"]: r["matched_by"] for r in g["covered"]}
    assert by == {"42009": "stage_and_category", "42010": "category_only"}
    assert g["degraded_matches"] == 1
