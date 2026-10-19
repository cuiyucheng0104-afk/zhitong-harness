"""生成 `审定单-样例.xlsx`（WS24-j，issue #1002）。合成数据，不对应任何真实项目。

用途两个：
1. tests/test_report_facts.py 的审定单通道夹具（送审 321721.00、审定 319786.00、核减 1935.00、净核减 1935.00）；
2. 生产验收第 2 步上传到测试项目「WS24验收」文件夹的那一份（验完移入回收站）。WS24-k 也沿用它
   （「汇总表」三个分项 + 合计）。

形状照常见的工程造价审定单汇总表：标题行、「工程名称：…  单位：元」抬头、一行表头、三个分项、合计行；
金额是数值格、常规格式（Excel 里显示 321721）。

重新生成：python3 tests/report/fixtures/report_facts/make_sample.py（zt 迁入时只改了这条路径说明）（会覆盖同目录下的 xlsx；数据不变，文件字节会变）。
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).with_name("审定单-样例.xlsx")

ROWS = [
    ("1", "建筑工程", 200000, 198800, 1200, 1200, None),
    ("2", "安装工程", 100000, 99265, 735, 735, None),
    ("3", "零星项目", 21721, 21721, 0, 0, None),
]


def build() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "汇总表"
    ws.append(["工程造价审定单（汇总表）"])
    ws.append(["工程名称：某路综合整治工程（合成样例）", None, None, None, None, None, "单位：元"])
    ws.append(["序号", "项目名称", "送审金额(元)", "审定金额(元)", "核减金额(元)", "净核减金额(元)", "备注"])
    for r in ROWS:
        ws.append(list(r))
    ws.append(["合计", None, sum(r[2] for r in ROWS), sum(r[3] for r in ROWS), sum(r[4] for r in ROWS),
               sum(r[5] for r in ROWS), None])
    return wb


if __name__ == "__main__":
    build().save(OUT)
    print(OUT)
